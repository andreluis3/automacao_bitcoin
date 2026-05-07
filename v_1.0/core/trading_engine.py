"""
trading_engine.py — Engine de trading completo.

MUDANÇAS v4:
- set_risk_profile("agressivo"): max_exposure 40% → 65%, min_order 35 → 20
- initial_alloc_pct: 0.10 → 0.40 (posição 4x maior imediatamente)
- max_position_size: 0.30 → 0.65
- take_profit_pct padrão: 2.5% → 4.0%
- stop_loss_pct padrão: 1.0% → 1.5%
- trailing_activation_pct: 1.0% → 0.5% (protege lucro mais cedo)
- trailing_distance_pct: 0.7% → 0.5% (trailing mais apertado)
- min_seconds_between_trades agressivo: 120 → 60 (mais oportunidades)
- _build_plan_from_value: usa signal_strength + is_breakout para sizing
- Breakout → position sizing reduzido (60%) = mais seguro em lateral
- Log estruturado com todos os campos de decisão
"""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from math import sqrt
from statistics import mean, pstdev
from typing import Any, Optional

from core.risk_manager import (
    RiskConfig, RiskManager, Position, PositionPlan, scale_position,
)
from core.strategy_engine import StrategyConfig, StrategyEngine

try:
    from core.bot_logger import BotLogger
    _HAS_BOTLOGGER = True
except ImportError:
    _HAS_BOTLOGGER = False


@dataclass
class OvertradingConfig:
    min_seconds_between_trades: int = 60    # era 180 — mais oportunidades
    max_trades_per_hour: int = 15           # era 8


@dataclass
class EngineConfig:
    risk: RiskConfig = field(default_factory=RiskConfig)
    overtrading: OvertradingConfig = field(default_factory=OvertradingConfig)
    drawdown_pause_pct: float = 12.0
    take_profit_pct:    float = 4.0   # era 2.5 — lucro maior por trade
    stop_loss_pct:      float = 1.5   # era 1.0 — menos stops por ruído


# ─── Adapters ─────────────────────────────────────────────────────────────────
class BaseExecutionAdapter:
    def __init__(self, fee_rate: float = 0.001):
        self.fee_rate = fee_rate
        self.total_fee_paid_brl = 0.0

    def set_initial_balance(self, balance_brl: float) -> None: raise NotImplementedError
    def available_brl(self) -> float: raise NotImplementedError
    def btc_balance(self) -> float: raise NotImplementedError
    def total_balance_brl(self, price_brl: float) -> float: raise NotImplementedError
    def get_equity(self, price_brl: float) -> float: return self.total_balance_brl(price_brl)
    def buy_quote(self, quote_brl: float, price_brl: float) -> tuple[float, float]: raise NotImplementedError
    def sell_quantity(self, quantity_btc: float, price_brl: float) -> tuple[float, float]: raise NotImplementedError


class SimulationExecutionAdapter(BaseExecutionAdapter):
    def __init__(self, fee_rate: float = 0.001):
        super().__init__(fee_rate=fee_rate)
        self.balance_brl: float = 0.0
        self.btc: float = 0.0

    def set_initial_balance(self, balance_brl: float) -> None:
        self.balance_brl = float(balance_brl)
        self.btc = 0.0
        self.total_fee_paid_brl = 0.0

    def available_brl(self) -> float: return self.balance_brl
    def btc_balance(self) -> float: return self.btc

    def total_balance_brl(self, price_brl: float) -> float:
        return self.balance_brl + (self.btc * price_brl if price_brl > 0 else 0.0)

    def get_equity(self, price_brl: float) -> float:
        return self.total_balance_brl(price_brl)

    def buy_quote(self, quote_brl: float, price_brl: float) -> tuple[float, float]:
        amount = min(float(quote_brl), self.balance_brl)
        if amount <= 0 or price_brl <= 0:
            return 0.0, 0.0
        fee_brl = amount * self.fee_rate
        btc = (amount - fee_brl) / price_brl
        self.balance_brl -= amount
        self.btc += btc
        self.total_fee_paid_brl += fee_brl
        return btc, fee_brl

    def sell_quantity(self, quantity_btc: float, price_brl: float) -> tuple[float, float]:
        qty = min(float(quantity_btc), self.btc)
        if qty <= 0 or price_brl <= 0:
            return 0.0, 0.0
        gross_brl = qty * price_brl
        fee_brl   = gross_brl * self.fee_rate
        net_brl   = gross_brl - fee_brl
        self.btc -= qty
        self.balance_brl += net_brl
        self.total_fee_paid_brl += fee_brl
        return net_brl, fee_brl


class BinanceExecutionAdapter(BaseExecutionAdapter):
    def __init__(self, client: Any, fee_rate: float = 0.001):
        super().__init__(fee_rate=fee_rate)
        self.client = client

    def set_initial_balance(self, balance_brl: float) -> None:
        self.total_fee_paid_brl = 0.0

    def _asset_total(self, asset: str) -> float:
        info = self.client.get_asset_balance(asset=asset)
        if not info:
            return 0.0
        return float(info.get("free", 0.0)) + float(info.get("locked", 0.0))

    def available_brl(self) -> float: return self._asset_total("BRL")
    def btc_balance(self) -> float: return self._asset_total("BTC")

    def total_balance_brl(self, price_brl: float) -> float:
        return self.available_brl() + (self.btc_balance() * price_brl)

    def get_equity(self, price_brl: float) -> float:
        return self.total_balance_brl(price_brl)

    def buy_quote(self, quote_brl: float, price_brl: float) -> tuple[float, float]:
        amount = max(0.0, float(quote_brl))
        if amount <= 0 or price_brl <= 0:
            return 0.0, 0.0
        order = self.client.create_order(symbol="BTCBRL", side="BUY", type="MARKET",
                                         quoteOrderQty=round(amount, 2))
        qty = sum(float(f.get("qty", 0)) for f in order.get("fills", []))
        if qty <= 0:
            qty = float(order.get("executedQty", 0.0))
        fee_brl = amount * self.fee_rate
        self.total_fee_paid_brl += fee_brl
        return qty, fee_brl

    def sell_quantity(self, quantity_btc: float, price_brl: float) -> tuple[float, float]:
        qty = max(0.0, float(quantity_btc))
        if qty <= 0 or price_brl <= 0:
            return 0.0, 0.0
        order = self.client.create_order(symbol="BTCBRL", side="SELL", type="MARKET",
                                         quantity=round(qty, 6))
        quote_qty = float(order.get("cummulativeQuoteQty", 0.0))
        fee_brl = quote_qty * self.fee_rate
        self.total_fee_paid_brl += fee_brl
        return max(0.0, quote_qty - fee_brl), fee_brl


# ─── TradingEngine ─────────────────────────────────────────────────────────────
class TradingEngine:
    def __init__(self, mode: str, execution: BaseExecutionAdapter,
                 trade_manager: Any = None, config: Optional[EngineConfig] = None,
                 log_dir: str = "logs"):
        self.mode = mode
        self.execution = execution
        self.trade_manager = trade_manager
        self.config = config or EngineConfig()
        self.logger = logging.getLogger(__name__)
        self.strategy = StrategyEngine(StrategyConfig())
        self.risk_manager = RiskManager(self.config.risk)

        self.bot_log: Optional[Any] = None
        if _HAS_BOTLOGGER:
            try:
                self.bot_log = BotLogger(base_dir=log_dir)
            except Exception:
                pass

        self.selected_strategy_mode = "auto"
        self.active_strategy_mode   = "lateral"
        self.breakout_risk_pct      = 30.0
        self.scaling_steps: list[float] = [0.05, 0.05, 0.10]  # era [0.02, 0.02, 0.03]
        self.max_position_size      = 0.65   # era 0.30
        self.position_alloc_pct     = 0.0
        self.trailing_activation_pct = 0.5   # era 1.0 — protege lucro mais cedo
        self.trailing_distance_pct   = 0.5   # era 0.7 — trailing mais apertado
        self.initial_balance_brl = 0.0
        self.max_buy_brl  = 0.0
        self.max_sell_brl = 0.0
        self.position: Optional[Position] = None
        self.current_drawdown_pct = 0.0
        self.max_drawdown_pct     = 0.0
        self.peak_equity_brl      = 0.0
        self.paused_by_drawdown   = False
        self.pause_until: Optional[datetime] = None
        self.last_trade_at: Optional[datetime] = None
        self.trade_entries_last_hour: deque[datetime] = deque()
        self._drawdown_alert_sent = False
        self.equity_curve: list[dict]        = []
        self.recent_returns: deque[float]    = deque(maxlen=80)
        self.last_trade: Optional[dict]      = None
        self.equity_history:    list[float]  = []
        self.benchmark_history: list[float]  = []
        self.trade_history:     list[dict]   = []
        self.near_trade_logs:   list[dict]   = []
        self.last_signal_context: dict       = {}
        self.accumulation_mode    = False
        self.lucro_hoje_brl       = 0.0
        self.safe_reserve_brl     = 0.0
        self.current_exposure_brl = 0.0
        self.total_gains_brl  = 0.0
        self.total_losses_brl = 0.0
        self.trade_outcomes: deque[bool] = deque(maxlen=20)
        self.consecutive_wins   = 0
        self.consecutive_losses = 0
        self.current_risk_per_trade_pct = self.config.risk.risk_per_trade_pct_base
        self.gain_values: list[float] = []
        self.loss_values: list[float] = []
        self.total_cross     = 0
        self.cross_filtrados = 0
        self.cross_executados = 0
        self._position_open_time: Optional[datetime] = None

    # ─── Configuração ──────────────────────────────────────────────────────────
    def set_sizing_config(self, risk_per_trade_pct: float, breakout_risk_pct: float,
                          scaling_steps: Optional[list[float]] = None,
                          max_position_size: float = 0.65) -> None:
        rp = max(0.1, min(10.0, float(risk_per_trade_pct)))
        self.config.risk.risk_per_trade_pct_base = rp
        self.breakout_risk_pct = max(rp, min(100.0, float(breakout_risk_pct)))
        if scaling_steps:
            self.scaling_steps = [max(0.0, float(v)) for v in scaling_steps]
        self.max_position_size = max(0.05, min(1.0, float(max_position_size)))

    def configure(self, initial_balance_brl: float, max_buy_brl: float, max_sell_brl: float) -> None:
        self.initial_balance_brl = float(initial_balance_brl)
        self.max_buy_brl  = float(max_buy_brl)
        self.max_sell_brl = float(max_sell_brl)
        self.execution.set_initial_balance(self.initial_balance_brl)
        self._reset_state()

    def _reset_state(self) -> None:
        self.position = None
        self.current_drawdown_pct = 0.0
        self.max_drawdown_pct     = 0.0
        self.peak_equity_brl      = self.initial_balance_brl
        self.paused_by_drawdown   = False
        self.pause_until = None
        self.last_trade_at = None
        self.trade_entries_last_hour.clear()
        self.equity_curve.clear()
        self.recent_returns.clear()
        self.last_trade = None
        self.equity_history.clear()
        self.benchmark_history.clear()
        self.trade_history.clear()
        self.near_trade_logs.clear()
        self.last_signal_context = {}
        self._drawdown_alert_sent = False
        self.lucro_hoje_brl = 0.0
        self.safe_reserve_brl = 0.0
        self.current_exposure_brl = 0.0
        self.total_gains_brl  = 0.0
        self.total_losses_brl = 0.0
        self.trade_outcomes.clear()
        self.consecutive_wins   = 0
        self.consecutive_losses = 0
        self.current_risk_per_trade_pct = self.config.risk.risk_per_trade_pct_base
        self.gain_values.clear()
        self.loss_values.clear()
        self.total_cross     = 0
        self.cross_filtrados = 0
        self.cross_executados = 0
        self.position_alloc_pct   = 0.0
        self._position_open_time  = None

    def set_drawdown_limit(self, pct: float) -> None:
        self.config.drawdown_pause_pct = max(0.5, float(pct))

    def set_accumulation_mode(self, enabled: bool) -> None:
        self.accumulation_mode = bool(enabled)

    def set_strategy_mode(self, strategy_mode: str) -> None:
        mode = str(strategy_mode).strip().lower()
        if mode in {"tendencia", "lateral", "auto"}:
            self.selected_strategy_mode = mode

    def set_aggressive_mode(self, enabled: bool) -> None:
        self.strategy.set_aggressive_mode(bool(enabled))

    def set_lateral_scalping(self, enabled: bool) -> None:
        self.strategy.set_lateral_scalping(bool(enabled))

    def set_block_lateral(self, enabled: bool) -> None:
        self.strategy.set_block_lateral(bool(enabled))

    def set_regime_threshold(self, threshold: float) -> None:
        self.strategy.set_regime_threshold(threshold)

    def set_eval_throttle(self, seconds: float) -> None:
        self.strategy.set_eval_throttle(seconds)

    def set_min_dist_pct(self, pct: float) -> None:
        self.strategy.set_min_dist_pct(pct)

    def set_risk_profile(self, profile_name: str) -> None:
        key = str(profile_name).strip().lower()
        if key == "conservador":
            self.config.risk = RiskConfig(
                risk_per_trade_pct_base=2.0,
                risk_per_trade_pct_aggressive=3.0,
                risk_per_trade_pct_defensive=1.0,
                max_exposure_pct=35.0,
                min_order_value_brl=20.0,
            )
            self.config.overtrading = OvertradingConfig(
                min_seconds_between_trades=120,
                max_trades_per_hour=8,
            )
            self.config.drawdown_pause_pct = 8.0
            self.config.take_profit_pct = 2.5
            self.config.stop_loss_pct   = 1.0
            self.max_position_size = 0.35
            self.risk_manager.initial_alloc_pct = 0.20
            self.trailing_activation_pct = 0.8
            self.trailing_distance_pct   = 0.6

        elif key == "agressivo":
            # Calibrado para R$ 300: posição grande, take maior
            self.config.risk = RiskConfig(
                risk_per_trade_pct_base=5.0,        # era 2.5
                risk_per_trade_pct_aggressive=7.0,  # era 4.0
                risk_per_trade_pct_defensive=2.5,   # era 1.25
                max_exposure_pct=65.0,              # era 40.0
                min_order_value_brl=20.0,           # era 35.0
            )
            self.config.overtrading = OvertradingConfig(
                min_seconds_between_trades=60,      # era 120
                max_trades_per_hour=15,             # era 12
            )
            self.config.drawdown_pause_pct = 15.0
            self.config.take_profit_pct = 4.0       # era 2.5
            self.config.stop_loss_pct   = 1.5       # era 1.0
            self.max_position_size = 0.65           # era 0.30
            self.risk_manager.initial_alloc_pct = 0.40  # era 0.10 — principal mudança
            self.trailing_activation_pct = 0.5     # era 1.0
            self.trailing_distance_pct   = 0.5     # era 0.7

        else:
            # Padrão balanceado
            self.config.risk = RiskConfig(
                risk_per_trade_pct_base=3.0,
                risk_per_trade_pct_aggressive=5.0,
                risk_per_trade_pct_defensive=1.5,
                max_exposure_pct=50.0,
                min_order_value_brl=20.0,
            )
            self.config.overtrading = OvertradingConfig(
                min_seconds_between_trades=90,
                max_trades_per_hour=12,
            )
            self.config.drawdown_pause_pct = 12.0
            self.config.take_profit_pct = 3.0
            self.config.stop_loss_pct   = 1.2
            self.max_position_size = 0.50
            self.risk_manager.initial_alloc_pct = 0.30
            self.trailing_activation_pct = 0.7
            self.trailing_distance_pct   = 0.55

        self.risk_manager = RiskManager(self.config.risk)
        self.risk_manager.max_position_size = self.max_position_size
        self.current_risk_per_trade_pct = self.config.risk.risk_per_trade_pct_base

    # ─── Helpers ───────────────────────────────────────────────────────────────
    def _current_equity_total(self, price_brl: float) -> float:
        return self.execution.total_balance_brl(price_brl)

    def _equity_for_risk(self, price_brl: float) -> float:
        eq = self._current_equity_total(price_brl)
        return max(0.0, eq - self.safe_reserve_brl) if self.accumulation_mode else max(0.0, eq)

    def _current_profit_factor(self) -> float:
        if self.total_losses_brl <= 0:
            return float("inf") if self.total_gains_brl > 0 else 0.0
        return self.total_gains_brl / self.total_losses_brl

    def _update_risk_regime(self, signal_ctx: Optional[dict] = None) -> None:
        risk = self.config.risk.risk_per_trade_pct_base
        if self.consecutive_losses >= 3:
            risk = self.config.risk.risk_per_trade_pct_defensive
        elif (self._current_profit_factor() > 1.3
              and str((signal_ctx or {}).get("active_mode") or "") == "tendencia_forte"):
            risk = self.config.risk.risk_per_trade_pct_aggressive
        self.current_risk_per_trade_pct = risk

    def _register_trade_result(self, lucro_brl: float, now: datetime) -> None:
        if lucro_brl > 0:
            self.total_gains_brl += lucro_brl
            self.gain_values.append(lucro_brl)
            self.trade_outcomes.append(True)
            self.consecutive_wins  += 1
            self.consecutive_losses = 0
            if self.accumulation_mode:
                self.safe_reserve_brl += lucro_brl * 0.30
        elif lucro_brl < 0:
            self.total_losses_brl += abs(lucro_brl)
            self.loss_values.append(abs(lucro_brl))
            self.trade_outcomes.append(False)
            self.consecutive_losses += 1
            self.consecutive_wins    = 0
            if self.consecutive_losses >= 5:
                self.pause_until = now + timedelta(minutes=30)

    # ─── Loop principal ────────────────────────────────────────────────────────
    def on_price(self, price_brl: float, now: Optional[datetime] = None,
                 candle_data: Optional[dict] = None) -> dict[str, Any]:
        price = float(price_brl)
        if price <= 0:
            return {"trade": False, "reason": "preco_invalido"}

        now    = now or datetime.utcnow()
        volume = float((candle_data or {}).get("volume", 0.0))
        high   = float((candle_data or {}).get("high", price))
        low    = float((candle_data or {}).get("low",  price))

        self.strategy.update_tick(price=price, high=high, low=low, volume=volume)
        equity_before = self._current_equity_total(price)
        self._update_equity_stats(price, now)

        if self.pause_until is not None:
            if now < self.pause_until:
                return {"trade": False, "reason": "pausa_5_perdas",
                        "resume_at": self.pause_until.isoformat(timespec="seconds")}
            self.pause_until = None

        if self.paused_by_drawdown:
            return {"trade": False, "reason": "pausado_drawdown", "drawdown": self.current_drawdown_pct}

        signal_ctx = self.strategy.evaluate(has_position=self.position is not None,
                                            selected_mode=self.selected_strategy_mode)
        self.last_signal_context = dict(signal_ctx)
        self.active_strategy_mode = str(signal_ctx.get("active_mode") or self.active_strategy_mode)

        e9p  = float(signal_ctx.get("ema9_prev") or 0.0)
        e21p = float(signal_ctx.get("ema21_prev") or 0.0)
        e9   = float(signal_ctx.get("ema9") or 0.0)
        e21  = float(signal_ctx.get("ema21") or 0.0)
        if e9p > 0 and e21p > 0 and e9p <= e21p and e9 > e21:
            self.total_cross += 1

        if self.bot_log:
            try:
                self.bot_log.market(price=price, volume=volume, ema9=e9, ema21=e21,
                                    atr=signal_ctx.get("atr"), regime=self.active_strategy_mode,
                                    timestamp=now)
            except Exception:
                pass

        # Posição aberta: trailing + exit check
        if self.position:
            self.risk_manager.update_trailing_stop(
                self.position, price,
                activation_pct=self.trailing_activation_pct,
                distance_pct=self.trailing_distance_pct,
            )
            should_exit, exit_reason = self.risk_manager.evaluate_exit(self.position, price)
            if should_exit:
                return self._close_position(price, exit_reason, now, technical_reason="saida_por_risco")
            if signal_ctx.get("signal") == "sell":
                return self._close_position(price, "SIGNAL_EXIT", now,
                                            technical_reason=str(signal_ctx.get("reason") or "sinal"))
            if self._can_scale_position(signal_ctx):
                strength = float(signal_ctx.get("signal_strength") or 0.0)
                new_alloc = scale_position(
                    signal_strength=strength, scaling_steps=self.scaling_steps,
                    current_alloc_pct=self.position_alloc_pct,
                    max_position_size=self.max_position_size,
                )
                add_pct = max(0.0, new_alloc - self.position_alloc_pct)
                if add_pct > 0:
                    scaled = self._scale_in_position(
                        price, self.execution.get_equity(price) * add_pct, now, signal_ctx)
                    if scaled.get("trade"):
                        self.position_alloc_pct = new_alloc
                        return scaled
            return {"trade": False, "reason": "posicao_aberta", "drawdown": self.current_drawdown_pct}

        # Sem posição
        if signal_ctx.get("signal") != "buy":
            self.cross_filtrados += 1
            self._append_near_trade_log(now, signal_ctx)
            if self.bot_log and self.cross_filtrados % 20 == 0:
                try:
                    self.bot_log.decision(
                        price=price, ema9=e9, ema21=e21,
                        slope=float(signal_ctx.get("slope_ema9") or 0.0),
                        dist_pct=float(signal_ctx.get("distancia_percentual") or 0.0),
                        atr=signal_ctx.get("atr"), atr_gate=signal_ctx.get("atr_gate"),
                        volume=volume, avg_volume=float(signal_ctx.get("avg_volume") or 0.0),
                        regime=self.active_strategy_mode, signal="none",
                        reason=str(signal_ctx.get("reason") or ""),
                    )
                except Exception:
                    pass
            return {"trade": False, "reason": str(signal_ctx.get("reason") or "sem_sinal"),
                    "drawdown": self.current_drawdown_pct}

        self._update_risk_regime(signal_ctx)
        if not self._can_open_trade(now):
            self._append_near_trade_log(now, {**signal_ctx, "reason": "filtro_overtrading"})
            return {"trade": False, "reason": "filtro_overtrading", "drawdown": self.current_drawdown_pct}

        capital_total = self.execution.get_equity(price)

        # Breakout → posição reduzida (60%) para ser mais conservador em lateral
        is_breakout = bool(signal_ctx.get("is_breakout", False))
        alloc_base  = self.risk_manager.initial_alloc_pct
        alloc = alloc_base * 0.6 if is_breakout else alloc_base
        self.position_alloc_pct = alloc

        trade_value = capital_total * alloc
        signal_strength = float(signal_ctx.get("signal_strength") or 0.5)

        plan = self._build_plan_from_value(
            price, trade_value, self.current_risk_per_trade_pct,
            signal_strength, is_breakout=is_breakout,
        )
        if not plan:
            self._append_near_trade_log(now, {**signal_ctx, "reason": "sem_position_size"})
            return {"trade": False, "reason": "sem_position_size", "drawdown": self.current_drawdown_pct}

        self.cross_executados += 1
        if self.bot_log:
            try:
                self.bot_log.decision(
                    price=price, ema9=e9, ema21=e21,
                    slope=float(signal_ctx.get("slope_ema9") or 0.0),
                    dist_pct=float(signal_ctx.get("distancia_percentual") or 0.0),
                    atr=signal_ctx.get("atr"), atr_gate=signal_ctx.get("atr_gate"),
                    volume=volume, avg_volume=float(signal_ctx.get("avg_volume") or 0.0),
                    regime=self.active_strategy_mode, signal="buy",
                    reason=str(signal_ctx.get("reason") or ""),
                )
            except Exception:
                pass

        return self._open_position(
            plan, now, saldo_antes=equity_before,
            motivo_entrada=str(signal_ctx.get("reason") or "entry"),
            strategy_context=signal_ctx,
        )

    # ─── Position sizing (CAMADA 4) ────────────────────────────────────────────
    def _build_plan_from_value(self, price: float, trade_value: float,
                               risk_per_trade_pct: float,
                               signal_strength: float = 0.5,
                               is_breakout: bool = False) -> Optional[PositionPlan]:
        if price <= 0 or trade_value <= 0:
            return None

        # Multiplicador por força do sinal
        if is_breakout:
            mult = 0.6   # breakout em lateral → mais conservador
        elif signal_strength >= 0.8:
            mult = 1.5   # sinal muito forte → 150%
        elif signal_strength >= 0.6:
            mult = 1.2   # sinal forte → 120%
        elif signal_strength >= 0.4:
            mult = 1.0   # sinal médio → 100%
        else:
            mult = 0.7   # sinal fraco → 70%

        adjusted = trade_value * mult

        # Limitar ao disponível
        available = self.execution.available_brl()
        adjusted = min(adjusted, available * 0.95)  # nunca usa 100% do saldo

        if adjusted < self.config.risk.min_order_value_brl:
            return None

        stop_price = price * (1.0 - self.config.stop_loss_pct  / 100.0)
        take_price = price * (1.0 + self.config.take_profit_pct / 100.0)
        qty = adjusted / price
        if qty <= 0:
            return None

        return PositionPlan(
            quantity=qty,
            entry_price=price,
            stop_loss=stop_price,
            take_profit=take_price,
            risk_brl=adjusted * (self.config.stop_loss_pct / 100.0),
            risk_pct=self.config.stop_loss_pct,
            notional_brl=adjusted,
            risk_per_trade_pct=risk_per_trade_pct,
        )

    # ─── Operações ─────────────────────────────────────────────────────────────
    def _open_position(self, plan: PositionPlan, now: datetime,
                       motivo_entrada: str = "strategy", saldo_antes: Optional[float] = None,
                       strategy_context: Optional[dict] = None) -> dict[str, Any]:
        btc, fee_brl = self.execution.buy_quote(plan.notional_brl, plan.entry_price)
        if btc <= 0:
            return {"trade": False, "reason": "falha_execucao_compra"}

        self.position = Position(
            side="BUY", entry_price=plan.entry_price, quantity=btc,
            stop_loss=plan.stop_loss, take_profit=plan.take_profit,
            risk_brl=plan.risk_brl, entry_spent_brl=plan.notional_brl,
            entry_fee_brl=fee_brl, opened_at=now,
        )
        self._position_open_time = now
        self.last_trade_at = now
        self.trade_entries_last_hour.append(now)
        self._prune_trade_window(now)
        self.current_exposure_brl = plan.notional_brl

        if self.trade_manager:
            try:
                self.trade_manager.abrir_trade(
                    modo=self.mode, preco_entrada=plan.entry_price,
                    saldo_antes=float(saldo_antes or self.execution.total_balance_brl(plan.entry_price)),
                    quantidade=btc, risco_percentual=plan.risk_pct,
                    stop_loss=plan.stop_loss, take_profit=plan.take_profit,
                    motivo_entrada=motivo_entrada, taxa_paga=fee_brl)
            except Exception as exc:
                self.logger.warning("trade_manager.abrir_trade: %s", exc)

        if self.bot_log:
            try:
                self.bot_log.order(side="BUY", price=plan.entry_price, qty_btc=btc,
                                   value_brl=plan.notional_brl, fee_brl=fee_brl,
                                   reason=motivo_entrada, status="EXECUTADA")
            except Exception:
                pass

        self.last_trade = {
            "side": "BUY", "price": plan.entry_price, "btc": btc, "fee_brl": fee_brl,
            "timestamp": now.isoformat(timespec="seconds"), "reason": motivo_entrada,
            "risk_per_trade_pct": plan.risk_per_trade_pct,
            "notional_brl": plan.notional_brl,
            "stop_loss": plan.stop_loss, "take_profit": plan.take_profit,
            "active_mode": str((strategy_context or {}).get("active_mode") or self.active_strategy_mode),
        }
        return {"trade": True, "side": "BUY", "btc": btc, "risk_pct": plan.risk_pct,
                "entry": plan.entry_price, "risk_per_trade_pct": plan.risk_per_trade_pct,
                "notional_brl": plan.notional_brl, "reason": motivo_entrada}

    def _close_position(self, price_brl: float, motivo_saida: str, now: datetime,
                        technical_reason: str = "") -> dict[str, Any]:
        if not self.position:
            return {"trade": False, "reason": "sem_posicao"}

        pos = self.position
        amount_brl, fee_brl = self.execution.sell_quantity(pos.quantity, price_brl)
        if amount_brl <= 0:
            return {"trade": False, "reason": "falha_execucao_venda"}

        pnl_brl = amount_brl - pos.entry_spent_brl
        pnl_pct = (pnl_brl / pos.entry_spent_brl * 100) if pos.entry_spent_brl > 0 else 0.0
        self.lucro_hoje_brl += pnl_brl
        self._register_trade_result(pnl_brl, now)

        saldo_depois = self.execution.total_balance_brl(price_brl)
        duration_min = ((now - self._position_open_time).total_seconds() / 60.0
                        ) if self._position_open_time else 0.0

        if self.trade_manager:
            try:
                self.trade_manager.fechar_trade(
                    modo=self.mode, preco_saida=price_brl,
                    saldo_depois=saldo_depois, quantidade=pos.quantity,
                    lucro_brl=pnl_brl, lucro_percentual=pnl_pct,
                    motivo_saida=motivo_saida, taxa_paga=fee_brl)
            except Exception as exc:
                self.logger.warning("trade_manager.fechar_trade: %s", exc)

        if self.bot_log:
            try:
                self.bot_log.order(side="SELL", price=price_brl, qty_btc=pos.quantity,
                                   value_brl=amount_brl, fee_brl=fee_brl,
                                   reason=motivo_saida, status="EXECUTADA")
                self.bot_log.result(entry_price=pos.entry_price, exit_price=price_brl,
                                    qty_btc=pos.quantity, pnl_brl=pnl_brl, pnl_pct=pnl_pct,
                                    duration_min=duration_min, exit_reason=motivo_saida,
                                    total_equity=saldo_depois)
            except Exception:
                pass

        self.last_trade = {
            "side": "SELL", "price": price_brl, "btc": pos.quantity,
            "fee_brl": fee_brl, "pnl_brl": pnl_brl, "pnl_pct": pnl_pct,
            "timestamp": now.isoformat(timespec="seconds"), "reason": motivo_saida,
        }
        self.trade_history.append({
            "data": now.isoformat(timespec="seconds"), "tipo": "SELL",
            "entrada": pos.entry_price, "saida": price_brl,
            "lucro": pnl_brl, "lucro_pct": pnl_pct, "motivo": motivo_saida,
            "active_mode": self.active_strategy_mode, "technical_reason": technical_reason,
            "duration_min": round(duration_min, 1),
        })
        if len(self.trade_history) > 400:
            self.trade_history = self.trade_history[-400:]

        self.position = None
        self.position_alloc_pct   = 0.0
        self.current_exposure_brl = 0.0
        self._position_open_time  = None
        self._update_equity_stats(price_brl, now)

        return {"trade": True, "side": "SELL", "amount_brl": amount_brl,
                "pnl_brl": pnl_brl, "pnl_pct": pnl_pct, "reason": motivo_saida,
                "lucro_hoje_brl": self.lucro_hoje_brl}

    def _scale_in_position(self, price: float, add_value: float, now: datetime,
                           signal_ctx: dict) -> dict[str, Any]:
        if self.position is None or add_value <= 0:
            return {"trade": False, "reason": "scale_in_invalido"}
        btc, fee_brl = self.execution.buy_quote(add_value, price)
        if btc <= 0:
            return {"trade": False, "reason": "scale_in_sem_execucao"}
        pos = self.position
        new_qty = pos.quantity + btc
        avg = ((pos.entry_price * pos.quantity) + (price * btc)) / max(new_qty, 1e-9)
        pos.entry_price     = avg
        pos.quantity        = new_qty
        pos.entry_spent_brl += add_value
        pos.entry_fee_brl   += fee_brl
        pos.stop_loss   = avg * (1.0 - self.config.stop_loss_pct  / 100.0)
        pos.take_profit = avg * (1.0 + self.config.take_profit_pct / 100.0)
        self.current_exposure_brl += add_value
        self.last_trade_at = now
        self.trade_entries_last_hour.append(now)
        self._prune_trade_window(now)
        self.last_trade = {
            "side": "BUY", "price": price, "btc": btc, "fee_brl": fee_brl,
            "timestamp": now.isoformat(timespec="seconds"), "reason": "scale_in",
            "active_mode": str(signal_ctx.get("active_mode") or self.active_strategy_mode),
        }
        return {"trade": True, "side": "BUY", "btc": btc, "entry": price, "reason": "scale_in"}

    def force_buy(self, price_brl: float, motivo: str = "manual") -> float:
        if self.position:
            return 0.0
        price = float(price_brl)
        stop_price = price * (1.0 - self.config.stop_loss_pct  / 100.0)
        take_price = price * (1.0 + self.config.take_profit_pct / 100.0)
        equity = self._equity_for_risk(price)
        signal_ctx = self.strategy.evaluate(has_position=False, selected_mode=self.selected_strategy_mode)
        self._update_risk_regime(signal_ctx)
        plan = self.risk_manager.build_position_plan(
            equity_brl=equity, available_brl=self.execution.available_brl(),
            entry_price=price, stop_price=stop_price, take_price=take_price,
            max_buy_brl=self.max_buy_brl, risk_per_trade_pct=self.current_risk_per_trade_pct)
        if not plan:
            return 0.0
        opened = self._open_position(plan, datetime.utcnow(), motivo_entrada=motivo,
                                     saldo_antes=self.execution.total_balance_brl(price),
                                     strategy_context=signal_ctx)
        return float(opened.get("btc", 0.0)) if opened.get("trade") else 0.0

    def force_sell(self, price_brl: float, motivo: str = "manual") -> float:
        if not self.position:
            return 0.0
        closed = self._close_position(float(price_brl), motivo, datetime.utcnow(),
                                      technical_reason=motivo)
        return float(closed.get("amount_brl", 0.0)) if closed.get("trade") else 0.0

    # ─── Utilidades ────────────────────────────────────────────────────────────
    def _can_open_trade(self, now: datetime) -> bool:
        if self.position:
            return False
        self._prune_trade_window(now)
        if len(self.trade_entries_last_hour) >= self.config.overtrading.max_trades_per_hour:
            return False
        if not self.last_trade_at:
            return True
        min_sec = max(30, self.config.overtrading.min_seconds_between_trades)
        return (now - self.last_trade_at) >= timedelta(seconds=min_sec)

    def _can_scale_position(self, signal_ctx: dict) -> bool:
        if self.position is None or self.position_alloc_pct >= self.max_position_size:
            return False
        if self.last_trade_at and (datetime.utcnow() - self.last_trade_at) < timedelta(
                seconds=max(30, self.config.overtrading.min_seconds_between_trades)):
            return False
        self._prune_trade_window(datetime.utcnow())
        if len(self.trade_entries_last_hour) >= self.config.overtrading.max_trades_per_hour:
            return False
        return (str(signal_ctx.get("active_mode") or "") in ("tendencia_forte",)
                and float(signal_ctx.get("ema9") or 0.0) > float(signal_ctx.get("ema21") or 0.0)
                and float(signal_ctx.get("slope_ema9") or 0.0) > 0)

    def _prune_trade_window(self, now: datetime) -> None:
        limit = now - timedelta(hours=1)
        while self.trade_entries_last_hour and self.trade_entries_last_hour[0] < limit:
            self.trade_entries_last_hour.popleft()

    def _append_near_trade_log(self, now: datetime, signal_ctx: dict) -> None:
        reason     = str(signal_ctx.get("reason") or "")
        warming_up = bool(signal_ctx.get("warming_up"))
        buf_len    = int(signal_ctx.get("buffer_len") or 0)
        req        = int(signal_ctx.get("required_periods") or 0)
        if warming_up and req > 0:
            reason = f"buffer={buf_len}/{req} warming_up"
        self.near_trade_logs.append({
            "data": now.isoformat(timespec="seconds"),
            "price_btc":  float(signal_ctx.get("price") or 0.0),
            "ema9":  float(signal_ctx.get("ema9")  or 0.0),
            "ema21": float(signal_ctx.get("ema21") or 0.0),
            "ema38": float(signal_ctx.get("ema38") or 0.0),
            "distancia_percentual": float(signal_ctx.get("distancia_percentual") or 0.0),
            "slope": float(signal_ctx.get("slope_ema9") or 0.0),
            "reason": reason,
            "active_mode": str(signal_ctx.get("active_mode") or self.active_strategy_mode),
            "atr":    float(signal_ctx.get("atr") or 0.0),
            "cascade_bull":    bool(signal_ctx.get("cascade_bull", False)),
            "is_pullback":     bool(signal_ctx.get("is_pullback", False)),
            "is_breakout":     bool(signal_ctx.get("is_breakout", False)),
            "signal_strength": float(signal_ctx.get("signal_strength") or 0.0),
            "buffer_len": buf_len, "required_periods": req, "warming_up": warming_up,
        })
        if len(self.near_trade_logs) > 500:
            self.near_trade_logs = self.near_trade_logs[-500:]

    def _update_equity_stats(self, price_brl: float, now: datetime) -> None:
        equity = self.execution.total_balance_brl(price_brl)
        if self.peak_equity_brl <= 0:
            self.peak_equity_brl = equity
        elif equity > self.peak_equity_brl:
            self.peak_equity_brl = equity
        if self.peak_equity_brl > 0:
            self.current_drawdown_pct = (self.peak_equity_brl - equity) / self.peak_equity_brl * 100
            self.max_drawdown_pct = max(self.max_drawdown_pct, self.current_drawdown_pct)
        if self.current_drawdown_pct >= self.config.drawdown_pause_pct:
            self.paused_by_drawdown = True
            if not self._drawdown_alert_sent:
                self.logger.warning("[%s] drawdown %.2f%% atingiu limite %.2f%%.",
                                    self.mode.upper(), self.current_drawdown_pct,
                                    self.config.drawdown_pause_pct)
                self._drawdown_alert_sent = True
        if self.equity_curve:
            prev = float(self.equity_curve[-1]["saldo"])
            if prev > 0:
                self.recent_returns.append((equity - prev) / prev)
        self.equity_curve.append({"data": now.isoformat(timespec="seconds"), "saldo": equity})
        self.equity_history.append(equity)
        self.benchmark_history.append(float(price_brl))
        if len(self.equity_history)    > 2000: self.equity_history    = self.equity_history[-2000:]
        if len(self.benchmark_history) > 2000: self.benchmark_history = self.benchmark_history[-2000:]

    def get_sharpe_simplificado(self) -> float:
        if len(self.recent_returns) < 2:
            return 0.0
        avg = mean(self.recent_returns)
        std = pstdev(self.recent_returns)
        return (avg / std) * sqrt(len(self.recent_returns)) if std > 0 else 0.0

    def get_runtime_snapshot(self, price_brl: float) -> dict[str, Any]:
        eq    = self.execution.total_balance_brl(price_brl)
        eq_op = max(0.0, eq - self.safe_reserve_brl)
        pf_raw = self._current_profit_factor()
        pf = 999.0 if pf_raw == float("inf") else pf_raw
        exp_pct = (self.current_exposure_brl / eq_op * 100.0) if eq_op > 0 else 0.0
        total_t = len(self.gain_values) + len(self.loss_values)
        wr   = len(self.gain_values) / total_t if total_t > 0 else 0.0
        ag   = sum(self.gain_values) / len(self.gain_values) if self.gain_values else 0.0
        al   = sum(self.loss_values) / len(self.loss_values) if self.loss_values else 0.0
        exp_ = (wr * ag) - ((1.0 - wr) * al)

        ctx    = self.last_signal_context
        ema9   = float(ctx.get("ema9")   or 0.0)
        ema21  = float(ctx.get("ema21")  or 0.0)
        ema38  = float(ctx.get("ema38")  or 0.0)
        slope9  = float(ctx.get("slope_ema9")  or 0.0)
        slope38 = float(ctx.get("slope_ema38") or 0.0)
        dist    = float(ctx.get("distancia_percentual") or 0.0)
        atr     = float(ctx.get("atr")      or 0.0)
        gate    = float(ctx.get("atr_gate") or 0.0)
        cascade_bull = bool(ctx.get("cascade_bull", False))
        cascade_bear = bool(ctx.get("cascade_bear", False))
        regime_pct   = float(ctx.get("regime_slope_pct") or 0.0)
        sig_strength = float(ctx.get("signal_strength") or 0.0)

        conf = {
            "ema_above_sma":  ema9 > ema21 if ema21 > 0 else False,
            "sma_slope_up":   slope9 > 0,
            "cascata_bull":   cascade_bull,
            "distancia_ok":   dist >= self.strategy.config.min_dist_pct,
            "ema38_slope_ok": slope38 > 0,
        }
        conf["veredito"] = ("Confluencia confirmada"
                            if sum(v for k, v in conf.items() if k != "veredito") >= 4
                            else "Aguardando confluencia")

        strategy_debug = self.strategy.get_debug_info()

        return {
            "mode": self.mode,
            "strategy_mode_selected": self.selected_strategy_mode,
            "strategy_mode_active":   self.active_strategy_mode,
            "price": price_brl,
            "saldo_brl":              self.execution.available_brl(),
            "btc":                    self.execution.btc_balance(),
            "equity_brl":             eq,
            "equity_operacional_brl": eq_op,
            "equity_atual_brl":       eq,
            "fee_total_brl":          self.execution.total_fee_paid_brl,
            "drawdown_atual_pct":     self.current_drawdown_pct,
            "drawdown_max_pct":       self.max_drawdown_pct,
            "paused_by_drawdown":     self.paused_by_drawdown,
            "position_open":          self.position is not None,
            "stop_loss":    self.position.stop_loss    if self.position else 0.0,
            "take_profit":  self.position.take_profit  if self.position else 0.0,
            "entry_price":  self.position.entry_price  if self.position else 0.0,
            "sharpe_simplificado":    self.get_sharpe_simplificado(),
            "last_trade":             self.last_trade,
            "accumulation_mode":      self.accumulation_mode,
            "lucro_hoje_brl":         self.lucro_hoje_brl,
            "safe_reserve_brl":       self.safe_reserve_brl,
            "patrimonio_protegido_brl": self.safe_reserve_brl,
            "current_exposure_brl":   self.current_exposure_brl,
            "current_exposure_pct":   exp_pct,
            "profit_factor":          pf,
            "profit_factor_warning":  pf < 1.2,
            "current_risk_per_trade_pct": self.current_risk_per_trade_pct,
            "consecutive_wins":   self.consecutive_wins,
            "consecutive_losses": self.consecutive_losses,
            "pause_until": self.pause_until.isoformat(timespec="seconds") if self.pause_until else "",
            "equity_history":    self.equity_history[-500:],
            "benchmark_history": self.benchmark_history[-500:],
            "trade_history":     self.trade_history[-200:],
            "near_trade_logs":   self.near_trade_logs[-200:],
            "win_rate": wr, "avg_gain": ag, "avg_loss": al, "expectancy": exp_,
            "risk_status": ("verde"   if self.current_drawdown_pct < 6
                            else "amarelo" if self.current_drawdown_pct < 10 else "vermelho"),
            "confluence":          conf,
            "last_signal_context": self.last_signal_context,
            "strategy_debug":      strategy_debug,
            "ema9": ema9, "ema21": ema21, "ema38": ema38,
            "slope9": slope9, "slope38": slope38,
            "distancia_percentual": dist,
            "cascade_bull":     cascade_bull,
            "cascade_bear":     cascade_bear,
            "regime_slope_pct": regime_pct,
            "signal_strength":  sig_strength,
            "total_cross":        self.total_cross,
            "cross_filtrados":    self.cross_filtrados,
            "cross_executados":   self.cross_executados,
            "trades_lucrativos":  len(self.gain_values),
            "trades_prejuizo":    len(self.loss_values),
            "lucro_total_brl":    self.lucro_hoje_brl,
            # Novos campos de debug v4
            "is_pullback":  bool(ctx.get("is_pullback", False)),
            "is_breakout":  bool(ctx.get("is_breakout", False)),
            "initial_alloc_pct":  self.risk_manager.initial_alloc_pct,
            "max_position_size":  self.max_position_size,
            "take_profit_pct":    self.config.take_profit_pct,
            "stop_loss_pct":      self.config.stop_loss_pct,
            "trailing_activation": self.trailing_activation_pct,
        }