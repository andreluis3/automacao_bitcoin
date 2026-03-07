from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
import threading
from typing import Any, Callable

from core.logger import ProfessionalLogger
from core.trading_engine import BinanceExecutionAdapter, EngineConfig, SimulationExecutionAdapter, TradingEngine
from core.valorbtc import BTCPriceFeed
from interface.config_store import load_config, save_config

PROFILE_PRESETS: dict[str, dict[str, float]] = {
    "Conservador": {"stop": 0.6, "take": 1.2, "valor_trade": 5.0, "drawdown": 12.0},
    "Agressivo": {"stop": 1.2, "take": 2.5, "valor_trade": 15.0, "drawdown": 12.0},
}


class BotController:
    def __init__(self, market_data, log_callback: Callable[[str], None]):
        self.market_data = market_data
        self.log_callback = log_callback

        self.config = load_config()
        self.config.setdefault("trading_mode", "auto")
        self.bot_state = "parado"
        self.engine: TradingEngine | None = None

        self.latest_price_usdt = 0.0
        self.latest_price_brl = 0.0
        self.preco_anterior = 0.0
        self.last_event: dict[str, Any] | None = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="engine-worker")
        self._pending_on_price: Future | None = None
        self._tick_lock = threading.Lock()
        self._latest_tick_price_brl = 0.0
        self._latest_tick_volume = 0.0

        self.report_logger = ProfessionalLogger(Path(__file__).resolve().parents[1] / "logs")

        self.feed = BTCPriceFeed(
            symbol="BTCBRL",
            rest_interval_sec=1.0,
            prefer_websocket=True,
            simulation_fallback=True,
            callback_on_tick=self._on_tick,
            callback_on_log=lambda msg: self.log(f"[FEED] {msg}"),
        )

        self.real_api_available = self._check_real_api_available()

    def initial_equity_reference(self) -> float:
        if self.engine is not None:
            return float(self.engine.initial_balance_brl)
        return float(self.config.get("saldo_inicial", 0.0))

    def _check_real_api_available(self) -> bool:
        try:
            client = getattr(self.market_data, "client", None)
            return client is not None
        except Exception:
            return False

    def shutdown(self) -> None:
        try:
            self.feed.stop()
        except Exception:
            pass
        try:
            self._executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass

    def log(self, msg: str) -> None:
        self.log_callback(msg)

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
        save_config(self.config)
        self.log("Configuração salva.")

    def start_bot(self) -> tuple[bool, str]:
        if self.bot_state != "parado":
            return False, "Bot já está em execução."

        modo = self.config.get("modo", "simulacao")
        if modo == "real" and not self.real_api_available:
            self.log("Erro: modo REAL bloqueado. API indisponível/sem credenciais.")
            return False, "Modo real bloqueado: API indisponível"

        try:
            if modo == "real":
                execution = BinanceExecutionAdapter(self.market_data.client)
                state = "real"
            else:
                execution = SimulationExecutionAdapter()
                state = "simulando"

            engine_cfg = EngineConfig(
                take_profit_pct=0.8,
                stop_loss_pct=0.4,
            )
            self.engine = TradingEngine(mode=modo, execution=execution, config=engine_cfg)

            profile = str(self.config.get("perfil", "Conservador"))
            self.engine.set_risk_profile(profile)
            self.engine.set_drawdown_limit(float(self.config.get("drawdown", 12.0)))
            self.engine.set_accumulation_mode(bool(self.config.get("acumular_saldo", False)))
            self.engine.set_strategy_mode(str(self.config.get("trading_mode", "auto")))

            saldo_inicial = float(self.config.get("saldo_inicial", 10000.0))
            valor_trade_pct = float(self.config.get("valor_trade", 5.0))
            max_buy = max(1.0, saldo_inicial * (valor_trade_pct / 100.0))
            max_sell = max_buy
            self.engine.configure(initial_balance_brl=saldo_inicial, max_buy_brl=max_buy, max_sell_brl=max_sell)

            self.report_logger.reset_session()
            self.bot_state = state
            self._pending_on_price = None
            self.feed.simulation_fallback = (modo != "real")
            self.feed.start()
            self.log(f"Bot iniciado em modo {self.bot_state.upper()}.")
            return True, "Bot iniciado"
        except Exception as exc:
            self.engine = None
            self.bot_state = "parado"
            self.log(f"Erro ao iniciar bot: {exc}")
            return False, str(exc)

    def start(self) -> tuple[bool, str]:
        return self.start_bot()

    def stop_bot(self) -> tuple[bool, str]:
        if self.bot_state == "parado":
            return False, "Bot já está parado"
        self.bot_state = "parado"
        self._pending_on_price = None
        self.feed.stop()
        self.log("Bot parado.")
        return True, "Bot parado"

    def download_logs_report(self) -> tuple[bool, str]:
        if self.engine is None:
            return False, "Engine não inicializado"

        snap = self.engine.get_runtime_snapshot(self.latest_price_brl if self.latest_price_brl > 0 else 1.0)
        strategy_mode = str(snap.get("strategy_mode_selected", self.config.get("trading_mode", "auto"))).capitalize()
        strategy_desc = "EMA9 / EMA21 + ATR + Slope + Bollinger"
        stats = {
            "total_trades": int(snap.get("trades_lucrativos", 0)) + int(snap.get("trades_prejuizo", 0)),
            "win_rate": float(snap.get("win_rate", 0.0)),
            "lucro_total_brl": float(snap.get("lucro_total_brl", 0.0)),
            "drawdown_max_pct": float(snap.get("drawdown_max_pct", 0.0)),
        }
        path = self.report_logger.export_report(
            mode_label=strategy_mode,
            strategy_label=strategy_desc,
            stats=stats,
        )
        return True, str(path)

    def _on_tick(self, price: float, volume: float) -> None:
        with self._tick_lock:
            self._latest_tick_price_brl = float(price)
            self._latest_tick_volume = float(volume)

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
            usdt_brl = float(self.market_data.get_price_safe("USDTBRL") or 0.0)
            price_brl = price_usdt * usdt_brl if usdt_brl > 0 else price_usdt
        return price_usdt, price_brl

    def get_runtime_snapshot(self) -> dict[str, Any]:
        try:
            self.latest_price_usdt, self.latest_price_brl = self._get_prices()
            if self.latest_price_usdt <= 0:
                self.latest_price_usdt = float(self.market_data.get_last_price_safe() or 0.0)
            if self.latest_price_brl <= 0:
                self.latest_price_brl = self.latest_price_usdt
        except Exception as exc:
            self.log(f"Erro ao obter preço: {exc}")
            return {
                "price_usdt": 0.0,
                "price_brl": 0.0,
                "equity_brl": 0.0,
                "current_drawdown_pct": 0.0,
                "paused_by_drawdown": False,
                "position_open": False,
                "last_trade": None,
                "mode": self.bot_state,
                "state": self.bot_state,
                "trade_event": None,
                "lucro_hoje_brl": 0.0,
                "safe_reserve_brl": 0.0,
                "current_exposure_brl": 0.0,
                "current_exposure_pct": 0.0,
                "profit_factor": 0.0,
                "profit_factor_warning": False,
                "patrimonio_protegido_brl": 0.0,
                "equity_history": [],
                "strategy_mode_selected": self.config.get("trading_mode", "auto"),
                "strategy_mode_active": "lateral",
            }

        variacao_pct = 0.0
        if self.preco_anterior > 0:
            variacao_pct = ((self.latest_price_usdt - self.preco_anterior) / self.preco_anterior) * 100.0
        self.preco_anterior = self.latest_price_usdt

        trade_event = None
        if self.bot_state in {"simulando", "real"} and self.engine is not None:
            if self._pending_on_price is not None and self._pending_on_price.done():
                try:
                    result = self._pending_on_price.result()
                except Exception as exc:
                    result = {"trade": False, "reason": f"erro_on_price: {exc}"}
                    self.log(f"Erro no engine.on_price: {exc}")

                if result.get("trade"):
                    side = str(result.get("side", "?"))
                    reason = str(result.get("reason", ""))
                    price = float(result.get("entry") or result.get("price") or self.latest_price_brl)
                    self.report_logger.add_event(
                        "trade",
                        {
                            "side": side,
                            "reason": reason,
                            "price": price,
                            "pnl_pct": float(result.get("pnl_pct", 0.0)),
                        },
                    )
                    if side == "BUY":
                        self.log(f"Entrada realizada | motivo: {reason}")
                    elif side == "SELL":
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
            equity = float(snap.get("equity_brl", 0.0))
            drawdown = float(snap.get("drawdown_atual_pct", 0.0))
            drawdown_max = float(snap.get("drawdown_max_pct", 0.0))
            paused = bool(snap.get("paused_by_drawdown", False))
            position_open = bool(snap.get("position_open", False))
            last_trade = snap.get("last_trade")
            lucro_hoje = float(snap.get("lucro_hoje_brl", 0.0))
            safe_reserve = float(snap.get("safe_reserve_brl", 0.0))
            exposicao_brl = float(snap.get("current_exposure_brl", 0.0))
            exposicao_pct = float(snap.get("current_exposure_pct", 0.0))
            profit_factor = float(snap.get("profit_factor", 0.0))
            pf_warning = bool(snap.get("profit_factor_warning", False))
            patrimonio_protegido = float(snap.get("patrimonio_protegido_brl", 0.0))
            equity_history = list(snap.get("equity_history", []))
            benchmark_history = list(snap.get("benchmark_history", []))
            trade_history = list(snap.get("trade_history", []))
            near_trade_logs = list(snap.get("near_trade_logs", []))
            win_rate = float(snap.get("win_rate", 0.0))
            avg_gain = float(snap.get("avg_gain", 0.0))
            avg_loss = float(snap.get("avg_loss", 0.0))
            expectancy = float(snap.get("expectancy", 0.0))
            risk_status = str(snap.get("risk_status", "verde"))
            confluence = dict(snap.get("confluence", {}))
            last_signal_context = dict(snap.get("last_signal_context", {}))
            total_cross = int(snap.get("total_cross", 0) or 0)
            cross_filtrados = int(snap.get("cross_filtrados", 0) or 0)
            cross_executados = int(snap.get("cross_executados", 0) or 0)
            trades_lucrativos = int(snap.get("trades_lucrativos", 0) or 0)
            trades_prejuizo = int(snap.get("trades_prejuizo", 0) or 0)
            total_trades = len(trade_history)
            lucro_liquido = float(sum(float(t.get("lucro", 0.0)) for t in trade_history))
            strategy_mode_selected = str(snap.get("strategy_mode_selected", self.config.get("trading_mode", "auto")))
            strategy_mode_active = str(snap.get("strategy_mode_active", "lateral"))

            self.report_logger.add_event(
                "tick",
                {
                    "price": self.latest_price_brl,
                    "ema9": float(last_signal_context.get("ema9") or 0.0),
                    "ema21": float(last_signal_context.get("ema21") or 0.0),
                    "signal": str(last_signal_context.get("signal") or "none"),
                },
            )
        else:
            equity = float(self.config.get("saldo_inicial", 0.0))
            drawdown = 0.0
            drawdown_max = 0.0
            paused = False
            position_open = False
            last_trade = None
            lucro_hoje = 0.0
            safe_reserve = 0.0
            exposicao_brl = 0.0
            exposicao_pct = 0.0
            profit_factor = 0.0
            pf_warning = False
            patrimonio_protegido = 0.0
            equity_history = []
            benchmark_history = []
            trade_history = []
            near_trade_logs = []
            win_rate = 0.0
            avg_gain = 0.0
            avg_loss = 0.0
            expectancy = 0.0
            risk_status = "verde"
            confluence = {}
            last_signal_context = {}
            total_cross = 0
            cross_filtrados = 0
            cross_executados = 0
            trades_lucrativos = 0
            trades_prejuizo = 0
            total_trades = 0
            lucro_liquido = 0.0
            strategy_mode_selected = str(self.config.get("trading_mode", "auto"))
            strategy_mode_active = "lateral"

        return {
            "price_usdt": self.latest_price_usdt,
            "price_brl": self.latest_price_brl,
            "variation_pct": variacao_pct,
            "equity_brl": equity,
            "current_drawdown_pct": drawdown,
            "drawdown_max_pct": drawdown_max,
            "paused_by_drawdown": paused,
            "position_open": position_open,
            "last_trade": last_trade,
            "mode": self.config.get("modo", "simulacao"),
            "state": self.bot_state,
            "trade_event": trade_event,
            "lucro_hoje_brl": lucro_hoje,
            "safe_reserve_brl": safe_reserve,
            "current_exposure_brl": exposicao_brl,
            "current_exposure_pct": exposicao_pct,
            "profit_factor": profit_factor,
            "profit_factor_warning": pf_warning,
            "patrimonio_protegido_brl": patrimonio_protegido,
            "equity_history": equity_history,
            "benchmark_history": benchmark_history,
            "trade_history": trade_history,
            "near_trade_logs": near_trade_logs,
            "win_rate": win_rate,
            "avg_gain": avg_gain,
            "avg_loss": avg_loss,
            "expectancy": expectancy,
            "risk_status": risk_status,
            "confluence": confluence,
            "last_signal_context": last_signal_context,
            "total_cross": total_cross,
            "cross_filtrados": cross_filtrados,
            "cross_executados": cross_executados,
            "trades_lucrativos": trades_lucrativos,
            "trades_prejuizo": trades_prejuizo,
            "total_trades": total_trades,
            "lucro_liquido_brl": lucro_liquido,
            "strategy_mode_selected": strategy_mode_selected,
            "strategy_mode_active": strategy_mode_active,
        }
