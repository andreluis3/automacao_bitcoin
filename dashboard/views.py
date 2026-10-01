"""Ponte Django <-> BotController (o mesmo controller usado pela UI Tkinter)."""
import json
import sys
import threading
from collections import deque
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

# Pasta v_1.0 (onde ficam core/, interface/, database/, api/). Configure BOT_ROOT no settings.py se mudar.
BOT_ROOT = Path(getattr(settings, "BOT_ROOT", Path(settings.BASE_DIR) / "v_1.0"))
sys.path.insert(0, str(BOT_ROOT))

_lock = threading.Lock()
_logs = deque(maxlen=500)          # (seq, "[HH:MM:SS] mensagem")
_seq = 0
_ctl = None
_market = None


def _push_log(msg: str) -> None:
    global _seq
    _seq += 1
    _logs.append((_seq, f"[{datetime.now():%H:%M:%S}] {msg}"))


def get_controller():
    """Cria MarketData + BotController uma única vez por processo."""
    global _ctl, _market
    with _lock:
        if _ctl is None:
            from api.market_data import MarketDataClient
            from interface.bot_controller import BotController

            client = None
            try:
                from api.binance_client import BinanceClient
                client = BinanceClient().get_client()
            except Exception as exc:
                _push_log(f"[SISTEMA] Binance indisponível ({exc}); só simulação.")
            _market = MarketDataClient(client=client)
            _market.start()
            _ctl = BotController(_market, log_callback=_push_log)
            _push_log("[SISTEMA] Dashboard web conectado ao BotController.")
        return _ctl


@ensure_csrf_cookie
def index(request):
    return render(request, "dashboard/index.html")


def _daily_rows(ctl, limit=31):
    with ctl.db._connect() as conn:
        rows = conn.execute(
            "SELECT data, lucro_dia, saldo_final, total_trades FROM daily_performance "
            "ORDER BY data DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows][::-1]


@require_GET
def api_state(request):
    ctl = get_controller()
    since = int(request.GET.get("since", 0) or 0)
    full = request.GET.get("full") == "1"
    with _lock:
        snap = ctl.get_runtime_snapshot()          # tem efeitos colaterais: 1 chamada por poll
    snap.pop("trade_event", None)
    snap["sharpe"] = 0.0
    if ctl.engine is not None:
        try:
            es = ctl.engine.get_runtime_snapshot(max(ctl.latest_price_brl, 1.0))
            snap["sharpe"] = float(es.get("sharpe_simplificado", 0.0))
        except Exception:
            pass
    if full:
        snap["trade_history"] = snap["trade_history"][-60:]
        snap["near_trade_logs"] = snap["near_trade_logs"][-40:]
        snap["daily"] = _daily_rows(ctl)
    else:
        for k in ("equity_history", "benchmark_history", "trade_history", "near_trade_logs"):
            snap[k] = []
    snap["config"] = {k: ctl.config.get(k) for k in ("modo", "trading_mode", "perfil", "acumular_saldo")}
    snap["real_api_available"] = ctl.real_api_available
    snap["offline"] = bool(getattr(_market, "offline_mode", False))
    snap["logs"] = [{"seq": s, "text": t} for s, t in _logs if s > since]
    snap["last_seq"] = _seq
    return JsonResponse(snap, json_dumps_params={"default": str})


@require_POST
def api_action(request):
    ctl = get_controller()
    try:
        body = json.loads(request.body or "{}")
    except ValueError:
        return JsonResponse({"ok": False, "msg": "JSON inválido"}, status=400)
    action, value = body.get("action"), body.get("value")
    ok, msg = True, "ok"
    if action == "start":
        ok, msg = ctl.start_bot()
    elif action == "stop":
        ok, msg = ctl.stop_bot()
    elif action == "mode":
        if ctl.bot_state != "parado":
            return JsonResponse({"ok": False, "msg": "Pare o bot antes de trocar o modo."})
        ctl.set_mode(value)
    elif action == "trading_mode":
        ctl.set_trading_mode(value)
    elif action == "profile":
        ctl.apply_profile(value)
    elif action == "accumulate":
        ctl.set_accumulation_mode(bool(value))
    else:
        return JsonResponse({"ok": False, "msg": "Ação desconhecida"}, status=400)
    return JsonResponse({"ok": bool(ok), "msg": msg})


@require_GET
def api_download_logs(request):
    ok, path = get_controller().download_logs_report()
    if not ok:
        return JsonResponse({"ok": False, "msg": path}, status=500)
    return FileResponse(open(path, "rb"), as_attachment=True, filename=Path(path).name)
