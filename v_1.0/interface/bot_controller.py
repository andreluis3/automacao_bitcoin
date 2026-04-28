from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
import logging
import os
import zipfile
from pathlib import Path
import threading
from typing import Any, Callable

from database.connection import DatabaseManager, StructuredTradeLogger
from core.logger import ProfessionalLogger
from core.trading_engine import (
    BinanceExecutionAdapter,
    EngineConfig,
    SimulationExecutionAdapter,
    TradingEngine,
)
from core.valorbtc import BTCPriceFeed
from interface.config_store import load_config, save_config


PROFILE_PRESETS: dict[str, dict[str, float]] = {
    "Conservador": {"stop": 0.6, "take": 1.2, "valor_trade": 5.0, "drawdown": 12.0},
    "Agressivo":   {"stop": 1.2, "take": 2.5, "valor_trade": 15.0, "drawdown": 12.0},
}


class BotController:
    def __init__(self, market_data, log_callback: Callable[[str], None]):
        self.market_data  = market_data
        self.log_callback = log_callback

        self.config = load_config()
        self.config.setdefault("trading_mode", "auto")
        self.bot_state = "parado"
        self.engine: TradingEngine | None = None

        self.latest_price_usdt = 0.0
        self.latest_price_brl  = 0.0
        self.preco_anterior    = 0.0
        self.last_event: dict[str, Any] | None = None

        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="engine-worker")
        self._pending_on_price: Future | None = None
        self._tick_lock = threading.Lock()
        self._latest_tick_price_brl = 0.0
        self._latest_tick_volume    = 0.0

        # Banco de dados
        self.db  = DatabaseManager()
        self.structured_log = StructuredTradeLogger(self.db)

        self.session_id: int | None = None
        self._open_trade_context: dict[str, Any] | None = None
        self._last_visual_signal   = ""
        self._last_trading_log_key = ""

        # Pasta de logs
        self._logs_dir = Path(__file__).resolve().parents[1] / "logs"
        self._logs_dir.mkdir(parents=True, exist_ok=True)

        self._trading_logger, self._performance_logger = self._setup_file_loggers()

        self.report_logger = ProfessionalLogger(self._logs_dir)

        self.feed = BTCPriceFeed(
            symbol="BTCBRL",
            rest_interval_sec=1.0,
            prefer_websocket=True,
            simulation_fallback=True,
            callback_on_tick=self._on_tick,
            callback_on_log=lambda msg: self.log(f"[FEED] {msg}"),
        )

        self.real_api_available = self._check_real_api_available()

    # ─── Loggers de arquivo ───────────────────────────────────────────────────

    def _setup_file_loggers(self) -> tuple[logging.Logger, logging.Logger]:
        trading_logger     = logging.getLogger("bot.trading")
        performance_logger = logging.getLogger("bot.performance")
        trading_logger.setLevel(logging.INFO)
        performance_logger.setLevel(logging.INFO)
        trading_logger.propagate     = False
        performance_logger.propagate = False

        if not trading_logger.handlers:
            h = logging.FileHandler(self._logs_dir / "trading.log", encoding="utf-8")
            h.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
            trading_logger.addHandler(h)

        if not performance_logger.handlers:
            h = logging.FileHandler(self._logs_dir / "performance.log", encoding="utf-8")
            h.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
            performance_logger.addHandler(h)

        return trading_logger, performance_logger

    # ─── Helpers básicos ─────────────────────────────────────────────────────

    def initial_equity_reference(self) -> float:
        if self.engine is not None:
            return float(self.engine.initial_balance_brl)
        return float(self.config.get("saldo_inicial", 0.0))

    def _check_real_api_available(self) -> bool:
        try:
            return getattr(self.market_data, "client", None) is not None
        except Exception:
            return False

    def log(self, msg: str) -> None:
        self.log_callback(msg)

    # ─── Ciclo de vida ────────────────────────────────────────────────────────

    def shutdown(self) -> None:
        if self.engine is not None and self.session_id is not None:
            snap = self.engine.get_runtime_snapshot(max(self.latest_price_brl, 1.0))
            self.db.end_session(
                self.session_id,
                saldo_final=float(snap.get("equity_brl", 0.0)),
                trades_executados=int(snap.get("trades_lucrativos", 0)) + int(snap.get("trades_prejuizo", 0)),
            )
            self.session_id = None
        try:
            self.feed.stop()
        except Exception:
            pass
        try:
            self._executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass

    # ─── Configurações ────────────────────────────────────────────────────────

    def set_mode(self, mode: str) -> None:
        mode_norm = "real" if str(mode).strip().lower() == "real" else "simulacao"
        self.config["modo"] = mode_norm
        save_config(self.config)
        self.log(f"Modo alterado para: {mode_norm.upper()}")

    def set_trading_mode(self, strategy_mode: str) -> None:
        mode_norm = str(strategy_mode).strip().lower()
        if mode_norm not in {"tendencia", "lateral", "auto"}:
            mode_norm = "auto"
        self.config["trading_mode"] = mode_norm
        save_config(self.config)
        if self.engine is not None:
            self.engine.set_strategy_mode(mode_norm)
        self.log(f"Modo de trading: {mode_norm.upper()}")

    def set_accumulation_mode(self, enabled: bool) -> None:
        is_enabled = bool(enabled)
        self.config["acumular_saldo"] = is_enabled
        save_config(self.config)
        if self.engine is not None:
            self.engine.set_accumulation_mode(is_enabled)
        self.log(f"Modo acumulação: {'ATIVO' if is_enabled else 'INATIVO'}")

    def apply_profile(self, profile: str) -> None:
        profile_name = "Agressivo" if str(profile).strip().lower() == "agressivo" else "Conservador"
        self.config["perfil"] = profile_name
        self.config.update(PROFILE_PRESETS[profile_name])
        save_config(self.config)
        self.log(f"Perfil aplicado: {profile_name}")

    def update_config(self, partial: dict[str, Any]) -> None:
        for key, value in partial.items():
            self.config[key] = value
        if "saldo_inicial" in partial:
            self.config["capital_total"] = float(partial["saldo_inicial"])
        if "valor_trade" in partial:
            self.config["risk_per_trade"] = max(0.01, min(0.03, float(partial["valor_trade"]) / 100.0))
        save_config(self.config)
        self.log("Configuração salva.")

    # ─── Iniciar bot ──────────────────────────────────────────────────────────

    def start_bot(self) -> tuple[bool, str]:
        print("START_BOT EXECUTANDO")
        if self.bot_state != "parado":
            return False, "Bot já está em execução."

        modo = self.config.get("modo", "simulacao")
        if modo == "real" and not self.real_api_available:
            self.log("Erro: modo REAL bloqueado. API indisponível/sem credenciais.")
            return False, "Modo real bloqueado: API indisponível"

        try:
            fee_rate = float(self.config.get("binance_fee", 0.001))
            if modo == "real":
                execution = BinanceExecutionAdapter(self.market_data.client, fee_rate=fee_rate)
                state = "real"
            else:
                execution = SimulationExecutionAdapter(fee_rate=fee_rate)
                state = "simulando"

            engine_cfg = EngineConfig(
                take_profit_pct=float(self.config.get("take", 0.8)),
                stop_loss_pct=float(self.config.get("stop", 0.4)),
            )
            self.engine = TradingEngine(
                mode=modo,
                execution=execution,
                config=engine_cfg,
                log_dir=str(self._logs_dir),
            )
            print("ENGINE CRIADO")

            # Perfil de risco
            profile = str(self.config.get("perfil", "Conservador"))
            self.engine.set_risk_profile(profile)
            self.engine.set_drawdown_limit(float(self.config.get("drawdown", 12.0)))
            self.engine.set_accumulation_mode(bool(self.config.get("acumular_saldo", False)))
            self.engine.set_strategy_mode(str(self.config.get("trading_mode", "auto")))

            # ── NOVOS modos de operação ────────────────────────────────────
            # Modo agressivo: entra se EMA9 > EMA21 sem exigir crossover
            self.engine.set_aggressive_mode(bool(self.config.get("aggressive_mode", True)))
            # Scalping Bollinger em mercado lateral
            self.engine.set_lateral_scalping(bool(self.config.get("lateral_scalping", True)))
            # Sensibilidade do detector de regime (padrão calibrado para ticks 1-2s BTC/BRL)
            self.engine.set_regime_threshold(float(self.config.get("regime_threshold", 0.000003)))

            # Sizing
            saldo_inicial = float(self.config.get("capital_total", self.config.get("saldo_inicial", 300.0)))
            risk_pct      = float(self.config.get("risk_per_trade", 0.02)) * 100.0
            breakout_pct  = float(self.config.get("breakout_risk", 0.30)) * 100.0
            scaling       = list(self.config.get("position_scaling", [0.02, 0.02, 0.03]))
            max_pos       = float(self.config.get("max_position_size", 0.30))
            self.engine.set_sizing_config(
                risk_per_trade_pct=risk_pct,
                breakout_risk_pct=breakout_pct,
                scaling_steps=scaling,
                max_position_size=max_pos,
            )
            valor_trade_pct = max(0.1, risk_pct)
            max_buy  = max(1.0, saldo_inicial * (valor_trade_pct / 100.0))
            self.engine.configure(
                initial_balance_brl=saldo_inicial,
                max_buy_brl=max_buy,
                max_sell_brl=max_buy,
            )

            self.report_logger.reset_session()
            self.session_id = self.db.start_session(saldo_inicio=saldo_inicial)
            self._open_trade_context = None
            self._last_trading_log_key = ""
            self.bot_state = state
            print("BOT ESTADO:", self.bot_state)
            self._pending_on_price = None
            self.feed.simulation_fallback = (modo != "real")
            self.feed.start()
            print("FEED INICIADO")
            self.log(f"Bot iniciado em modo {self.bot_state.upper()}.")
            return True, "Bot iniciado"

        except Exception as exc:
            self.engine = None
            self.bot_state = "parado"
            self.log(f"Erro ao iniciar bot: {exc}")
            return False, str(exc)

    def start(self) -> tuple[bool, str]:
        print("BOTCONTROLLER START CHAMADO")
        return self.start_bot()

    # ─── Parar bot ────────────────────────────────────────────────────────────

    def stop_bot(self) -> tuple[bool, str]:
        if self.bot_state == "parado":
            return False, "Bot já está parado"
        if self.engine is not None and self.session_id is not None:
            snap = self.engine.get_runtime_snapshot(max(self.latest_price_brl, 1.0))
            self.db.end_session(
                self.session_id,
                saldo_final=float(snap.get("equity_brl", 0.0)),
                trades_executados=int(snap.get("trades_lucrativos", 0)) + int(snap.get("trades_prejuizo", 0)),
            )
            self.session_id = None
        self.bot_state = "parado"
        self._pending_on_price = None
        self.feed.stop()
        self.log("Bot parado.")
        return True, "Bot parado"

    # ─── Download de logs ─────────────────────────────────────────────────────

    def download_logs_report(self) -> tuple[bool, str]:
        """
        Gera um arquivo ZIP com TODOS os logs do sistema:
          - logs/trading.log
          - logs/performance.log
          - logs/decisions/*.log
          - logs/market/*.log
          - logs/orders/*.log
          - logs/results/*.log
          - logs/errors/*.log
          - logs/state/*.log
          - logs/strategy/*.log
          - logs/daily/*.log
          - relatorio_sessao.txt  (snapshot da sessão atual)

        Retorna (True, caminho_do_zip) em caso de sucesso.
        """
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            zip_path  = self._logs_dir / f"relatorio_{timestamp}.zip"

            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:

                # 1. Todos os arquivos .log dentro de logs/ (recursivo)
                for log_file in self._logs_dir.rglob("*.log"):
                    # Evita incluir o próprio zip se por acaso tiver extensão .log
                    if log_file.suffix == ".log":
                        arcname = log_file.relative_to(self._logs_dir.parent)
                        zf.write(log_file, arcname)

                # 2. Relatório de sessão atual (snapshot em texto)
                session_txt = self._build_session_report()
                zf.writestr(f"relatorio_sessao_{timestamp}.txt", session_txt)

                # 3. Trade logs do banco de dados (CSV inline)
                trade_logs_csv = self._build_trade_logs_csv()
                zf.writestr(f"trade_logs_{timestamp}.csv", trade_logs_csv)

            self.log(f"Logs exportados: {zip_path.name}")
            return True, str(zip_path)

        except Exception as exc:
            self.log(f"Erro ao exportar logs: {exc}")
            return False, str(exc)

    def _build_session_report(self) -> str:
        """Monta relatório de texto da sessão atual."""
        lines: list[str] = []
        lines.append("=" * 60)
        lines.append("  RELATÓRIO DE SESSÃO — Automação Bitcoin")
        lines.append(f"  Gerado em: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("=" * 60)

        if self.engine is None:
            lines.append("\nEngine não inicializado.")
            return "\n".join(lines)

        price = max(self.latest_price_brl, 1.0)
        snap  = self.engine.get_runtime_snapshot(price)

        strategy_mode = str(snap.get("strategy_mode_selected", "auto")).upper()
        active_mode   = str(snap.get("strategy_mode_active", "lateral")).upper()
        debug         = dict(snap.get("strategy_debug", {}))

        total_trades  = int(snap.get("trades_lucrativos", 0)) + int(snap.get("trades_prejuizo", 0))
        win_rate      = float(snap.get("win_rate", 0.0)) * 100
        lucro_total   = float(snap.get("lucro_total_brl", 0.0))
        drawdown_max  = float(snap.get("drawdown_max_pct", 0.0))
        equity        = float(snap.get("equity_brl", 0.0))
        profit_factor = float(snap.get("profit_factor", 0.0))
        sharpe        = float(snap.get("sharpe_simplificado", 0.0))

        lines.append(f"\n  MODO BOT      : {self.bot_state.upper()}")
        lines.append(f"  ESTRATÉGIA    : {strategy_mode} (ativo: {active_mode})")
        lines.append(f"  PERFIL        : {self.config.get('perfil', 'Conservador')}")
        lines.append(f"  MODO AGRESSIVO: {debug.get('aggressive_no_crossover', False)}")
        lines.append(f"  SCALPING LAT. : {debug.get('lateral_scalping', False)}")
        lines.append(f"  REGIME THRESH : {debug.get('regime_threshold', 0.000005)}")
        lines.append("")
        lines.append("  ── INDICADORES ───────────────────────────────────")
        lines.append(f"  BTC/BRL       : R$ {price:,.2f}")
        lines.append(f"  EMA9          : {debug.get('ema9', 0.0):.2f}")
        lines.append(f"  EMA21         : {debug.get('ema21', 0.0):.2f}")
        lines.append(f"  Slope EMA9    : {debug.get('slope9', 0.0):+.4f}")
        lines.append(f"  ATR           : {debug.get('atr', 'N/A')}")
        lines.append(f"  BB Upper      : {debug.get('bb_upper', 'N/A')}")
        lines.append(f"  BB Lower      : {debug.get('bb_lower', 'N/A')}")
        lines.append(f"  Regime atual  : {debug.get('regime', 'N/A').upper()}")
        lines.append("")
        lines.append("  ── PERFORMANCE ───────────────────────────────────")
        lines.append(f"  Equity        : R$ {equity:.4f}")
        lines.append(f"  Lucro hoje    : R$ {lucro_total:+.4f}")
        lines.append(f"  Drawdown máx. : {drawdown_max:.2f}%")
        lines.append(f"  Total trades  : {total_trades}")
        lines.append(f"  Win rate      : {win_rate:.1f}%")
        lines.append(f"  Profit factor : {profit_factor:.2f}")
        lines.append(f"  Sharpe simpl. : {sharpe:.4f}")
        lines.append("")
        lines.append("  ── CONFLUÊNCIA ATUAL ─────────────────────────────")
        conf = dict(snap.get("confluence", {}))
        for k, v in conf.items():
            if k == "veredito":
                continue
            mark = "✔" if v else "✖"
            lines.append(f"  {mark} {k}")
        lines.append(f"  → {conf.get('veredito', 'N/A')}")
        lines.append("")
        lines.append("  ── ÚLTIMOS TRADES ────────────────────────────────")
        trade_history = list(snap.get("trade_history", []))[-10:]
        if not trade_history:
            lines.append("  Nenhum trade nesta sessão.")
        for t in trade_history:
            sinal = "+" if float(t.get("lucro", 0)) >= 0 else ""
            lines.append(
                f"  {t.get('data','')} | {t.get('tipo','')} | "
                f"Entrada R${float(t.get('entrada',0)):,.2f} → "
                f"Saída R${float(t.get('saida',0)):,.2f} | "
                f"PnL {sinal}R${float(t.get('lucro',0)):.4f} | "
                f"{t.get('motivo','')}"
            )
        lines.append("")
        lines.append("=" * 60)
        return "\n".join(lines)

    def _build_trade_logs_csv(self) -> str:
        """Exporta trade_logs do banco em formato CSV."""
        rows = self.db.listar_trade_logs(limit=1000)
        if not rows:
            return "Sem registros em trade_logs.\n"

        header = "data_hora,tipo,preco,quantidade,lucro,saldo_apos_trade,motivo_entrada,regime_mercado,distancia_media_percentual,desvio_padrao_atual"
        lines  = [header]
        for r in rows:
            lines.append(
                f"{r.get('data_hora','')},"
                f"{r.get('tipo','')},"
                f"{r.get('preco',0.0):.2f},"
                f"{r.get('quantidade',0.0):.8f},"
                f"{r.get('lucro',0.0):.4f},"
                f"{r.get('saldo_apos_trade',0.0):.4f},"
                f"{r.get('motivo_entrada','')},"
                f"{r.get('regime_mercado','')},"
                f"{r.get('distancia_media_percentual',0.0):.6f},"
                f"{r.get('desvio_padrao_atual',0.0):.4f}"
            )
        return "\n".join(lines)

    # ─── Tick handler ────────────────────────────────────────────────────────

    def _on_tick(self, price: float, volume: float) -> None:
        with self._tick_lock:
            self._latest_tick_price_brl = float(price)
            self._latest_tick_volume    = float(volume)

        if self.bot_state not in {"simulando", "real"} or self.engine is None:
            return

        if self._pending_on_price is None or self._pending_on_price.done():
            self._pending_on_price = self._executor.submit(
                self.engine.on_price,
                float(price),
                datetime.utcnow(),
                {"volume": float(volume), "high": float(price), "low": float(price)},
            )

    def _get_prices(self) -> tuple[float, float]:
        with self._tick_lock:
            price_brl = float(self._latest_tick_price_brl)
        price_usdt = float(self.market_data.get_price_safe("BTCUSDT") or 0.0)
        if price_brl <= 0:
            price_brl = float(self.feed.get_last_price() or 0.0)
        if price_usdt <= 0 and price_brl > 0:
            price_usdt = price_brl
        if price_brl <= 0 and price_usdt > 0:
            usdt_brl  = float(self.market_data.get_price_safe("USDTBRL") or 0.0)
            price_brl = price_usdt * usdt_brl if usdt_brl > 0 else price_usdt
        return price_usdt, price_brl

    # ─── Snapshot ─────────────────────────────────────────────────────────────

    def get_runtime_snapshot(self) -> dict[str, Any]:
        try:
            self.latest_price_usdt, self.latest_price_brl = self._get_prices()
            if self.latest_price_usdt <= 0:
                self.latest_price_usdt = float(self.market_data.get_last_price_safe() or 0.0)
            if self.latest_price_brl <= 0:
                self.latest_price_brl = self.latest_price_usdt
        except Exception as exc:
            self.log(f"Erro ao obter preço: {exc}")
            return self._empty_snapshot()

        variacao_pct = 0.0
        if self.preco_anterior > 0:
            variacao_pct = ((self.latest_price_usdt - self.preco_anterior) / self.preco_anterior) * 100.0
        self.preco_anterior = self.latest_price_usdt

        snapshot = self._empty_snapshot()
        snapshot.update(
            {
                "price_usdt": self.latest_price_usdt,
                "price_brl": self.latest_price_brl,
                "variation_pct": variacao_pct,
                "mode": self.config.get("modo", "simulacao"),
                "state": self.bot_state,
            }
        )

        if self.engine is None:
            return snapshot

        trade_event = None
        if self.bot_state in {"simulando", "real"} and self.engine is not None:
            if self._pending_on_price is not None and self._pending_on_price.done():
                try:
                    result = self._pending_on_price.result()
                except Exception as exc:
                    result = {"trade": False, "reason": f"erro_on_price: {exc}"}
                    self.log(f"Erro no engine.on_price: {exc}")

                if result.get("trade"):
                    side   = str(result.get("side", "?"))
                    reason = str(result.get("reason", ""))
                    price  = float(result.get("entry") or result.get("price") or self.latest_price_brl)

                    self.report_logger.add_event("trade", {
                        "side": side, "reason": reason, "price": price,
                        "pnl_pct": float(result.get("pnl_pct", 0.0)),
                    })

                    if side == "BUY":
                        self._open_trade_context = {
                            "simbolo":     str(self.config.get("symbol", "BTCUSDT")),
                            "entry_price": float(price),
                            "quantidade":  float(result.get("btc", 0.0)),
                            "hora_entrada": datetime.now().isoformat(timespec="seconds"),
                            "taxa_entrada": 0.0,
                        }
                        self.log(f"Entrada realizada | motivo: {reason}")

                        # StructuredTradeLogger — registra compra
                        try:
                            snap_now = self.engine.get_runtime_snapshot(self.latest_price_brl)
                            ctx_sig  = dict(snap_now.get("last_signal_context", {}))
                            self.structured_log.registrar_trade(
                                tipo="BUY",
                                preco=float(price),
                                quantidade=float(result.get("btc", 0.0)),
                                lucro=0.0,
                                saldo_apos_trade=float(snap_now.get("equity_brl", 0.0)),
                                motivo_entrada=reason,
                                regime_mercado=str(snap_now.get("strategy_mode_active", "auto")),
                                distancia_media_percentual=float(ctx_sig.get("distancia_percentual", 0.0)),
                                desvio_padrao_atual=float(ctx_sig.get("atr") or 0.0),
                            )
                        except Exception:
                            pass

                    elif side == "SELL":
                        if self._open_trade_context is not None:
                            ctx = dict(self._open_trade_context)
                            lucro          = float(result.get("pnl_brl", 0.0))
                            profit_percent = float(result.get("pnl_pct", 0.0))
                            exit_price     = float(result.get("price") or self.latest_price_brl)
                            hora_saida     = datetime.now().isoformat(timespec="seconds")
                            taxa           = float(result.get("fee_brl", 0.0))

                            self.db.insert_trade(
                                simbolo=str(ctx.get("simbolo", "BTCUSDT")),
                                lado="BUY",
                                entry_price=float(ctx.get("entry_price", 0.0)),
                                exit_price=exit_price,
                                quantidade=float(ctx.get("quantidade", 0.0)),
                                hora_entrada=str(ctx.get("hora_entrada", hora_saida)),
                                hora_saida=hora_saida,
                                taxa=taxa,
                                lucro=lucro,
                                profit_percent=profit_percent,
                            )
                            self.db.add_fee(hora_saida, taxa)

                            day = datetime.now().strftime("%Y-%m-%d")
                            saldo_final = float(
                                self.engine.get_runtime_snapshot(self.latest_price_brl).get("equity_brl", 0.0)
                            )
                            self.db.upsert_daily_performance(
                                day, lucro_delta=lucro, saldo_final=saldo_final, trade_delta=1
                            )
                            self._performance_logger.info(
                                "TRADE_CLOSE | lucro=%.4f | lucro_pct=%.4f | saldo_final=%.4f",
                                lucro, profit_percent, saldo_final,
                            )

                            # StructuredTradeLogger — registra venda
                            try:
                                snap_now = self.engine.get_runtime_snapshot(self.latest_price_brl)
                                ctx_sig  = dict(snap_now.get("last_signal_context", {}))
                                self.structured_log.registrar_trade(
                                    tipo="SELL",
                                    preco=float(exit_price),
                                    quantidade=float(ctx.get("quantidade", 0.0)),
                                    lucro=lucro,
                                    saldo_apos_trade=saldo_final,
                                    motivo_entrada=reason,
                                    regime_mercado=str(snap_now.get("strategy_mode_active", "auto")),
                                    distancia_media_percentual=float(ctx_sig.get("distancia_percentual", 0.0)),
                                    desvio_padrao_atual=float(ctx_sig.get("atr") or 0.0),
                                )
                            except Exception:
                                pass

                            self._open_trade_context = None

                        if reason == "SL":
                            self.log("Stop loss acionado")
                        elif reason == "TP":
                            self.log("Take profit acionado")
                        else:
                            self.log(f"Saída realizada | motivo: {reason}")

                else:
                    reason = str(result.get("reason", ""))
                    if reason in {"pausado_drawdown", "filtro_overtrading"}:
                        self.log(f"Ação bloqueada: {reason}")

                trade_event = result
                self.last_event = result
                self._pending_on_price = None

        if self.engine is not None:
            snap = self.engine.get_runtime_snapshot(self.latest_price_brl)
            self.report_logger.add_event(
                "tick",
                {
                    "price": self.latest_price_brl,
                    "ema9": float(snap.get("last_signal_context", {}).get("ema9") or 0.0),
                    "ema21": float(snap.get("last_signal_context", {}).get("ema21") or 0.0),
                    "signal": str(snap.get("last_signal_context", {}).get("signal") or "none"),
                },
            )
            self._write_trading_log(snap.get("last_signal_context", {}), snap)

        snapshot.update(
            {
                "trade_event": trade_event,
                "equity_brl": float(snap.get("equity_brl", 0.0)),
                "current_drawdown_pct": float(snap.get("drawdown_atual_pct", 0.0)),
                "drawdown_max_pct": float(snap.get("drawdown_max_pct", 0.0)),
                "paused_by_drawdown": bool(snap.get("paused_by_drawdown", False)),
                "position_open": bool(snap.get("position_open", False)),
                "last_trade": snap.get("last_trade"),
                "lucro_hoje_brl": float(snap.get("lucro_hoje_brl", 0.0)),
                "safe_reserve_brl": float(snap.get("safe_reserve_brl", 0.0)),
                "current_exposure_brl": float(snap.get("current_exposure_brl", 0.0)),
                "current_exposure_pct": float(snap.get("current_exposure_pct", 0.0)),
                "profit_factor": float(snap.get("profit_factor", 0.0)),
                "profit_factor_warning": bool(snap.get("profit_factor_warning", False)),
                "patrimonio_protegido_brl": float(snap.get("patrimonio_protegido_brl", 0.0)),
                "equity_history": list(snap.get("equity_history", [])),
                "benchmark_history": list(snap.get("benchmark_history", [])),
                "trade_history": list(snap.get("trade_history", [])),
                "near_trade_logs": list(snap.get("near_trade_logs", [])),
                "win_rate": float(snap.get("win_rate", 0.0)),
                "avg_gain": float(snap.get("avg_gain", 0.0)),
                "avg_loss": float(snap.get("avg_loss", 0.0)),
                "expectancy": float(snap.get("expectancy", 0.0)),
                "risk_status": str(snap.get("risk_status", "verde")),
                "confluence": dict(snap.get("confluence", {})),
                "last_signal_context": dict(snap.get("last_signal_context", {})),
                "strategy_debug": dict(snap.get("strategy_debug", {})),
                "total_cross": int(snap.get("total_cross", 0) or 0),
                "cross_filtrados": int(snap.get("cross_filtrados", 0) or 0),
                "cross_executados": int(snap.get("cross_executados", 0) or 0),
                "trades_lucrativos": int(snap.get("trades_lucrativos", 0) or 0),
                "trades_prejuizo": int(snap.get("trades_prejuizo", 0) or 0),
                "total_trades": len(snap.get("trade_history", [])),
                "lucro_liquido_brl": float(sum(float(t.get("lucro", 0)) for t in snap.get("trade_history", []))),
                "strategy_mode_selected": str(snap.get("strategy_mode_selected", self.config.get("trading_mode", "auto"))),
                "strategy_mode_active": str(snap.get("strategy_mode_active", "lateral")),
                "fees_paid_brl": self.db.get_total_fees(),
                "position_indicator": self._position_indicator(bool(snap.get("position_open", False))),
                "sessions_count": self.db.sessions_count(),
                "best_day": self.db.best_day(),
                "worst_day": self.db.worst_day(),
                "monthly_profit": self.db.monthly_profit(datetime.now().strftime("%Y-%m")),
                "trades_count_db": self.db.trades_count(),
            }
        )

        return snapshot

    # ─── Helpers de snapshot ─────────────────────────────────────────────────

    def _empty_snapshot(self) -> dict[str, Any]:
        return {
            "price_usdt": 0.0, "price_brl": 0.0, "variation_pct": 0.0,
            "equity_brl": float(self.config.get("saldo_inicial", 0.0)),
            "current_drawdown_pct": 0.0, "drawdown_max_pct": 0.0,
            "paused_by_drawdown": False, "position_open": False,
            "last_trade": None, "mode": self.bot_state, "state": self.bot_state,
            "trade_event": None, "lucro_hoje_brl": 0.0, "safe_reserve_brl": 0.0,
            "current_exposure_brl": 0.0, "current_exposure_pct": 0.0,
            "profit_factor": 0.0, "profit_factor_warning": False,
            "patrimonio_protegido_brl": 0.0, "equity_history": [],
            "benchmark_history": [], "trade_history": [], "near_trade_logs": [],
            "win_rate": 0.0, "avg_gain": 0.0, "avg_loss": 0.0, "expectancy": 0.0,
            "risk_status": "verde", "confluence": {}, "last_signal_context": {},
            "strategy_debug": {}, "total_cross": 0, "cross_filtrados": 0,
            "cross_executados": 0, "trades_lucrativos": 0, "trades_prejuizo": 0,
            "total_trades": 0, "lucro_liquido_brl": 0.0,
            "strategy_mode_selected": self.config.get("trading_mode", "auto"),
            "strategy_mode_active": "lateral",
            "fees_paid_brl": 0.0, "position_indicator": "NONE",
            "sessions_count": 0, "best_day": 0.0, "worst_day": 0.0,
            "monthly_profit": 0.0, "trades_count_db": 0,
        }

    def _position_indicator(self, position_open: bool) -> str:
        if position_open:
            return "BUY"
        if isinstance(self.last_event, dict) and str(self.last_event.get("side", "")).upper() == "SELL":
            return "SELL"
        return "NONE"

    def _write_trading_log(self, signal_ctx: dict[str, Any], snap: dict[str, Any]) -> None:
        signal   = str(signal_ctx.get("signal") or "none").upper()
        price    = float(signal_ctx.get("price") or self.latest_price_brl)
        ema9     = float(signal_ctx.get("ema9")  or 0.0)
        ema21    = float(signal_ctx.get("ema21") or 0.0)
        pos_size = float(snap.get("current_exposure_brl", 0.0))
        lucro    = float(snap.get("lucro_hoje_brl", 0.0))
        regime   = str(snap.get("strategy_mode_active", ""))
        key = f"{signal}|{round(ema9,2)}|{round(ema21,2)}|{round(pos_size,2)}"
        if key == self._last_trading_log_key:
            return
        self._last_trading_log_key = key
        self._trading_logger.info(
            "BTC %.2f | EMA9 %.2f | EMA21 %.2f | SINAL %s | REGIME %s | POS %.6f | LUCRO %.4f",
            price, ema9, ema21, signal, regime.upper(),
            pos_size / price if price > 0 else 0.0,
            lucro,
        )
