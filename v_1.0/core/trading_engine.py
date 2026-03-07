from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from math import sqrt
from statistics import mean, pstdev
from typing import Any

from core.risk_manager import calculate_position_size, scale_position
from core.strategy_engine import StrategyConfig, StrategyEngine


@dataclass
class RiskConfig:
    risk_per_trade_pct_base: float = 2.5
    risk_per_trade_pct_aggressive: float = 4.0
    risk_per_trade_pct_defensive: float = 1.25
    max_exposure_pct: float = 40.0
    min_order_value_brl: float = 35.0


@dataclass
class OvertradingConfig:
    min_seconds_between_trades: int = 180
    max_trades_per_hour: int = 8


@dataclass
class EngineConfig:
    risk: RiskConfig = field(default_factory=RiskConfig)
    overtrading: OvertradingConfig = field(default_factory=OvertradingConfig)
    drawdown_pause_pct: float = 12.0
    take_profit_pct: float = 0.8
    stop_loss_pct: float = 0.4


@dataclass
class PositionPlan:
    quantity: float
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_brl: float
    risk_pct: float
    notional_brl: float
    risk_per_trade_pct: float


@dataclass
class Position:
    entry_price: float
    quantity: float
    stop_loss: float
    take_profit: float
    highest_price: float
    risk_brl: float
    entry_spent_brl: float
    entry_fee_brl: float
    opened_at: datetime


class RiskManager:
    def __init__(self, risk_config: RiskConfig):
        self.initial_alloc_pct = 0.10
        self.scale_step_pct = 0.10
        self.max_position_size = 0.30
        self.position_alloc_pct = self.initial_alloc_pct

    def build_position_plan(
        self,
        equity_brl: float,
        available_brl: float,
        entry_price: float,
        stop_price: float,
        take_price: float,
        max_buy_brl: float,
        risk_per_trade_pct: float,
    ) -> PositionPlan | None:
        if equity_brl <= 0 or available_brl <= 0 or entry_price <= 0:
            return None
        if stop_price <= 0 or stop_price >= entry_price:
            return None
        if take_price <= entry_price:
            return None

        risk_per_unit = entry_price - stop_price
        if risk_per_unit <= 0:
            return None

        risk_value = equity_brl * (risk_per_trade_pct / 100.0)
        max_exposure_value = equity_brl * (self.config.max_exposure_pct / 100.0)
        position_value_from_risk = (risk_value / risk_per_unit) * entry_price

        cap = min(available_brl, max_buy_brl if max_buy_brl > 0 else available_brl, max_exposure_value)
        position_value = min(position_value_from_risk, cap)

        if position_value < self.config.min_order_value_brl:
            return None

        quantity = position_value / entry_price
        risk_brl = quantity * risk_per_unit
        if quantity <= 0 or position_value <= 0:
            return None

        risk_pct = ((entry_price - stop_price) / entry_price) * 100

        return PositionPlan(
            quantity=quantity,
            entry_price=entry_price,
            stop_loss=stop_price,
            take_profit=take_price,
            risk_brl=risk_brl,
            risk_pct=risk_pct,
            notional_brl=position_value,
            risk_per_trade_pct=risk_per_trade_pct,
        )

    def evaluate_exit(self, position: Position, current_price: float) -> tuple[bool, str]:
        if current_price <= position.stop_loss:
            return True, "SL"
        if current_price >= position.take_profit:
            return True, "TP"
        return False, ""


class BaseExecutionAdapter:
    def __init__(self, fee_rate: float = 0.001):
        self.fee_rate = fee_rate
        self.total_fee_paid_brl = 0.0

    def set_initial_balance(self, balance_brl: float) -> None:
        raise NotImplementedError

    def available_brl(self) -> float:
        raise NotImplementedError

    def btc_balance(self) -> float:
        raise NotImplementedError

    def total_balance_brl(self, price_brl: float) -> float:
        raise NotImplementedError

    def buy_quote(self, quote_brl: float, price_brl: float) -> tuple[float, float]:
        raise NotImplementedError

    def sell_quantity(self, quantity_btc: float, price_brl: float) -> tuple[float, float]:
        raise NotImplementedError


class SimulationExecutionAdapter(BaseExecutionAdapter):
    def __init__(self, fee_rate: float = 0.001):
        super().__init__(fee_rate=fee_rate)
        self.balance_brl = 0.0
        self.btc = 0.0

    def set_initial_balance(self, balance_brl: float) -> None:
        self.balance_brl = float(balance_brl)
        self.btc = 0.0
        self.total_fee_paid_brl = 0.0

    def available_brl(self) -> float:
        return self.balance_brl

    def btc_balance(self) -> float:
        return self.btc

    def total_balance_brl(self, price_brl: float) -> float:
        if price_brl <= 0:
            return self.balance_brl
        return self.balance_brl + (self.btc * price_brl)

    def buy_quote(self, quote_brl: float, price_brl: float) -> tuple[float, float]:
        amount = min(float(quote_brl), self.balance_brl)
        if amount <= 0 or price_brl <= 0:
            return 0.0, 0.0

        fee_brl = amount * self.fee_rate
        net_amount = amount - fee_brl
        btc = net_amount / price_brl

        self.balance_brl -= amount
        self.btc += btc
        self.total_fee_paid_brl += fee_brl

        return btc, fee_brl

    def sell_quantity(self, quantity_btc: float, price_brl: float) -> tuple[float, float]:
        qty = min(float(quantity_btc), self.btc)
        if qty <= 0 or price_brl <= 0:
            return 0.0, 0.0

        gross_brl = qty * price_brl
        fee_brl = gross_brl * self.fee_rate
        net_brl = gross_brl - fee_brl

        self.btc -= qty
        self.balance_brl += net_brl
        self.total_fee_paid_brl += fee_brl

        return net_brl, fee_brl


class BinanceExecutionAdapter(BaseExecutionAdapter):
    def __init__(self, client, fee_rate: float = 0.001):
        super().__init__(fee_rate=fee_rate)
        self.client = client

    def set_initial_balance(self, balance_brl: float) -> None:
        self.total_fee_paid_brl = 0.0

    def _asset_total(self, asset: str) -> float:
        info = self.client.get_asset_balance(asset=asset)
        if not info:
            return 0.0
        return float(info.get("free", 0.0)) + float(info.get("locked", 0.0))

    def available_brl(self) -> float:
        return self._asset_total("BRL")

    def btc_balance(self) -> float:
        return self._asset_total("BTC")

    def total_balance_brl(self, price_brl: float) -> float:
        return self.available_brl() + (self.btc_balance() * price_brl)

    def buy_quote(self, quote_brl: float, price_brl: float) -> tuple[float, float]:
        amount = max(0.0, float(quote_brl))
        if amount <= 0 or price_brl <= 0:
            return 0.0, 0.0

        order = self.client.create_order(
            symbol="BTCBRL",
            side="BUY",
            type="MARKET",
            quoteOrderQty=round(amount, 2),
        )
        executed_qty = sum(float(fill.get("qty", 0.0)) for fill in order.get("fills", []))
        if executed_qty <= 0:
            executed_qty = float(order.get("executedQty", 0.0))

        fee_brl = amount * self.fee_rate
        self.total_fee_paid_brl += fee_brl
        return executed_qty, fee_brl

    def sell_quantity(self, quantity_btc: float, price_brl: float) -> tuple[float, float]:
        qty = max(0.0, float(quantity_btc))
        if qty <= 0 or price_brl <= 0:
            return 0.0, 0.0

        order = self.client.create_order(
            symbol="BTCBRL",
            side="SELL",
            type="MARKET",
            quantity=round(qty, 6),
        )
        quote_qty = float(order.get("cummulativeQuoteQty", 0.0))
        fee_brl = quote_qty * self.fee_rate
        self.total_fee_paid_brl += fee_brl
        return max(0.0, quote_qty - fee_brl), fee_brl


class TradingEngine:
    def __init__(
        self,
        mode: str,
        execution: BaseExecutionAdapter,
        trade_manager=None,
        config: EngineConfig | None = None,
    ):
        self.mode = mode
        self.execution = execution
        self.trade_manager = trade_manager
        self.config = config or EngineConfig()

        self.logger = logging.getLogger(__name__)
        self.strategy = StrategyEngine(StrategyConfig())
        self.risk_manager = RiskManager(self.config.risk)

        self.selected_strategy_mode = "auto"
        self.active_strategy_mode = "lateral"
        self.breakout_risk_pct = 30.0
        self.scaling_steps = [0.02, 0.02, 0.03]
        self.max_position_size = 0.30
        self.position_alloc_pct = 0.0

        self.initial_balance_brl = 0.0
        self.max_buy_brl = 0.0
        self.max_sell_brl = 0.0

        self.position: Position | None = None
        self.current_drawdown_pct = 0.0
        self.max_drawdown_pct = 0.0
        self.peak_equity_brl = 0.0
        self.paused_by_drawdown = False
        self.pause_until: datetime | None = None
        self.last_trade_at: datetime | None = None
        self.trade_entries_last_hour: deque[datetime] = deque()
        self._drawdown_alert_sent = False

        self.equity_curve: list[dict[str, float | str]] = []
        self.recent_returns: deque[float] = deque(maxlen=80)
        self.last_trade: dict[str, float | str] | None = None
        self.equity_history: list[float] = []
        self.benchmark_history: list[float] = []
        self.trade_history: list[dict[str, Any]] = []
        self.near_trade_logs: list[dict[str, Any]] = []
        self.last_signal_context: dict[str, Any] = {}

        self.accumulation_mode = False
        self.lucro_hoje_brl = 0.0
        self.safe_reserve_brl = 0.0
        self.current_exposure_brl = 0.0

        self.total_gains_brl = 0.0
        self.total_losses_brl = 0.0
        self.trade_outcomes: deque[bool] = deque(maxlen=20)
        self.consecutive_wins = 0
        self.consecutive_losses = 0
        self.current_risk_per_trade_pct = self.config.risk.risk_per_trade_pct_base
        self.gain_values: list[float] = []
        self.loss_values: list[float] = []

        self.total_cross = 0
        self.cross_filtrados = 0
        self.cross_executados = 0

    def set_sizing_config(
        self,
        risk_per_trade_pct: float,
        breakout_risk_pct: float,
        scaling_steps: list[float] | None = None,
        max_position_size: float = 0.30,
    ) -> None:
        rp = max(0.1, min(3.0, float(risk_per_trade_pct)))
        self.config.risk.risk_per_trade_pct_base = rp
        self.breakout_risk_pct = max(rp, min(100.0, float(breakout_risk_pct)))
        if scaling_steps:
            self.scaling_steps = [max(0.0, float(v)) for v in scaling_steps]
        self.max_position_size = max(0.05, min(1.0, float(max_position_size)))

    def configure(self, initial_balance_brl: float, max_buy_brl: float, max_sell_brl: float) -> None:
        self.initial_balance_brl = float(initial_balance_brl)
        self.max_buy_brl = float(max_buy_brl)
        self.max_sell_brl = float(max_sell_brl)

        self.execution.set_initial_balance(self.initial_balance_brl)

        self.position = None
        self.current_drawdown_pct = 0.0
        self.max_drawdown_pct = 0.0
        self.peak_equity_brl = self.initial_balance_brl
        self.paused_by_drawdown = False
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
        self.total_gains_brl = 0.0
        self.total_losses_brl = 0.0
        self.trade_outcomes.clear()
        self.consecutive_wins = 0
        self.consecutive_losses = 0
        self.current_risk_per_trade_pct = self.config.risk.risk_per_trade_pct_base
        self.gain_values.clear()
        self.loss_values.clear()
        self.total_cross = 0
        self.cross_filtrados = 0
        self.cross_executados = 0
        self.position_alloc_pct = 0.0

    def set_drawdown_limit(self, pct: float) -> None:
        self.config.drawdown_pause_pct = max(0.5, float(pct))

    def set_accumulation_mode(self, enabled: bool) -> None:
        self.accumulation_mode = bool(enabled)

    def set_strategy_mode(self, strategy_mode: str) -> None:
        mode = str(strategy_mode).strip().lower()
        if mode not in {"tendencia", "lateral", "auto"}:
            return
        self.selected_strategy_mode = mode

    def set_risk_profile(self, profile_name: str) -> None:
        key = str(profile_name).strip().lower()
        if key == "conservador":
            self.config.risk = RiskConfig(
                risk_per_trade_pct_base=2.0,
                risk_per_trade_pct_aggressive=3.0,
                risk_per_trade_pct_defensive=1.0,
                max_exposure_pct=30.0,
                min_order_value_brl=35.0,
            )
            self.config.overtrading = OvertradingConfig(min_seconds_between_trades=240, max_trades_per_hour=6)
            self.config.drawdown_pause_pct = 8.0
        elif key == "agressivo":
            self.config.risk = RiskConfig(
                risk_per_trade_pct_base=2.5,
                risk_per_trade_pct_aggressive=4.0,
                risk_per_trade_pct_defensive=1.25,
                max_exposure_pct=40.0,
                min_order_value_brl=35.0,
            )
            self.config.overtrading = OvertradingConfig(min_seconds_between_trades=120, max_trades_per_hour=12)
            self.config.drawdown_pause_pct = 15.0
        else:
            self.config.risk = RiskConfig()
            self.config.overtrading = OvertradingConfig()
            self.config.drawdown_pause_pct = 12.0

        self.risk_manager = RiskManager(self.config.risk)
        self.current_risk_per_trade_pct = self.config.risk.risk_per_trade_pct_base

    def _current_equity_total(self, price_brl: float) -> float:
        return self.execution.total_balance_brl(price_brl)

    def _equity_for_risk(self, price_brl: float) -> float:
        equity_total = self._current_equity_total(price_brl)
        if self.accumulation_mode:
            return max(0.0, equity_total - self.safe_reserve_brl)
        return max(0.0, equity_total)

    def _current_profit_factor(self) -> float:
        if self.total_losses_brl <= 0:
            return float("inf") if self.total_gains_brl > 0 else 0.0
        return self.total_gains_brl / self.total_losses_brl

    def _update_risk_regime(self, signal_ctx: dict[str, Any] | None = None) -> None:
        risk = self.config.risk.risk_per_trade_pct_base
        if self.consecutive_losses >= 3:
            risk = self.config.risk.risk_per_trade_pct_defensive
        else:
            pf = self._current_profit_factor()
            trend_mode = str((signal_ctx or {}).get("active_mode") or "") == "tendencia"
            if pf > 1.3 and trend_mode:
                risk = self.config.risk.risk_per_trade_pct_aggressive
        self.current_risk_per_trade_pct = risk

    def _register_trade_result(self, lucro_brl: float, now: datetime) -> None:
        if lucro_brl > 0:
            self.total_gains_brl += lucro_brl
            self.gain_values.append(lucro_brl)
            self.trade_outcomes.append(True)
            self.consecutive_wins += 1
            self.consecutive_losses = 0
            if self.accumulation_mode:
                self.safe_reserve_brl += lucro_brl * 0.30
        elif lucro_brl < 0:
            loss = abs(lucro_brl)
            self.total_losses_brl += loss
            self.loss_values.append(loss)
            self.trade_outcomes.append(False)
            self.consecutive_losses += 1
            self.consecutive_wins = 0
            if self.consecutive_losses >= 5:
                self.pause_until = now + timedelta(minutes=30)

    def on_price(
        self,
        price_brl: float,
        now: datetime | None = None,
        candle_data: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        price = float(price_brl)
        if price <= 0:
            return {"trade": False, "reason": "preco_invalido"}

        now = now or datetime.utcnow()
        volume = float((candle_data or {}).get("volume", 0.0))
        high = float((candle_data or {}).get("high", price))
        low = float((candle_data or {}).get("low", price))

        self.strategy.update_tick(price=price, high=high, low=low, volume=volume)
        equity_before = self._current_equity_total(price)
        self._update_equity_stats(price, now)

        if self.pause_until is not None and now < self.pause_until:
            return {"trade": False, "reason": "pausa_5_perdas", "resume_at": self.pause_until.isoformat(timespec="seconds")}
        if self.pause_until is not None and now >= self.pause_until:
            self.pause_until = None

        if self.paused_by_drawdown:
            return {"trade": False, "reason": "pausado_drawdown", "drawdown": self.current_drawdown_pct}

        signal_ctx = self.strategy.evaluate(has_position=self.position is not None, selected_mode=self.selected_strategy_mode)
        self.last_signal_context = dict(signal_ctx)
        self.active_strategy_mode = str(signal_ctx.get("active_mode") or self.active_strategy_mode)

        # contabiliza apenas cruzamentos de tendência
        if bool(signal_ctx.get("ema9_prev") is not None and signal_ctx.get("ema21_prev") is not None):
            ema9_prev = float(signal_ctx.get("ema9_prev") or 0.0)
            ema21_prev = float(signal_ctx.get("ema21_prev") or 0.0)
            ema9_now = float(signal_ctx.get("ema9") or 0.0)
            ema21_now = float(signal_ctx.get("ema21") or 0.0)
            if ema9_prev <= ema21_prev and ema9_now > ema21_now:
                self.total_cross += 1

        if self.position:
            should_exit, exit_reason = self.risk_manager.evaluate_exit(self.position, price)
            if should_exit:
                return self._close_position(price, exit_reason, now, technical_reason="saida_por_risco")

            if signal_ctx.get("signal") == "sell":
                return self._close_position(price, "SIGNAL_EXIT", now, technical_reason=str(signal_ctx.get("reason") or "sinal"))

            # Position scaling: adiciona posição gradualmente enquanto tendência segue válida
            if self._can_scale_position(signal_ctx):
                strength = self._signal_strength(signal_ctx)
                new_alloc_pct = scale_position(
                    signal_strength=strength,
                    scaling_steps=self.scaling_steps,
                    current_alloc_pct=self.position_alloc_pct,
                    max_position_size=self.max_position_size,
                )
                add_pct = max(0.0, new_alloc_pct - self.position_alloc_pct)
                if add_pct > 0:
                    capital_total = self.execution.get_equity()
                    add_value = capital_total * add_pct
                    scaled = self._scale_in_position(price, add_value, now, signal_ctx)
                    if scaled.get("trade"):
                        self.position_alloc_pct = new_alloc_pct
                        return scaled

            return {"trade": False, "reason": "posicao_aberta", "drawdown": self.current_drawdown_pct}

        if signal_ctx.get("signal") != "buy":
            self.cross_filtrados += 1
            self._append_near_trade_log(now, signal_ctx)
            return {"trade": False, "reason": str(signal_ctx.get("reason") or "sem_sinal"), "drawdown": self.current_drawdown_pct}

        self._update_risk_regime(signal_ctx)

        if not self._can_open_trade(now):
            self._append_near_trade_log(now, {**signal_ctx, "reason": "filtro_overtrading"})
            return {"trade": False, "reason": "filtro_overtrading", "drawdown": self.current_drawdown_pct}

        # capital total da conta
        capital_total = self.execution.get_equity()

        # posição inicial = 10%
        self.position_alloc_pct = self.initial_alloc_pct

        alloc_pct = self.position_alloc_pct

        # valor em reais da posição
        trade_value = capital_total * alloc_pct

        # cria plano de posição
        plan = self._build_plan_from_value(
            price=price,
            trade_value=trade_value,
            risk_per_trade_pct=self.config.stop_loss_pct,
        )

        if not plan:
            self._append_near_trade_log(now, {**signal_ctx, "reason": "sem_position_size"})
            return {"trade": False, "reason": "sem_position_size", "drawdown": self.current_drawdown_pct}

        self.cross_executados += 1

        return self._open_position(
            plan,
            now,
            saldo_antes=equity_before,
            motivo_entrada=str(signal_ctx.get("reason") or "entry"),
            strategy_context=signal_ctx,
        )

    def force_buy(self, price_brl: float, motivo: str = "manual") -> float:
        if self.position:
            return 0.0

        price = float(price_brl)
        stop_price = price * (1.0 - (self.config.stop_loss_pct / 100.0))
        take_price = price * (1.0 + (self.config.take_profit_pct / 100.0))
        equity = self._equity_for_risk(price)

        signal_ctx = self.strategy.evaluate(has_position=False, selected_mode=self.selected_strategy_mode)
        self._update_risk_regime(signal_ctx)

        plan = self.risk_manager.build_position_plan(
            equity_brl=equity,
            available_brl=self.execution.available_brl(),
            entry_price=price,
            stop_price=stop_price,
            take_price=take_price,
            max_buy_brl=self.max_buy_brl,
            risk_per_trade_pct=self.current_risk_per_trade_pct,
        )
        if not plan:
            return 0.0

        opened = self._open_position(
            plan,
            datetime.utcnow(),
            motivo_entrada=motivo,
            saldo_antes=self.execution.total_balance_brl(price),
            strategy_context=signal_ctx,
        )
        return float(opened.get("btc", 0.0)) if opened.get("trade") else 0.0

    def force_sell(self, price_brl: float, motivo: str = "manual") -> float:
        if not self.position:
            return 0.0
        closed = self._close_position(float(price_brl), motivo, datetime.utcnow(), technical_reason=motivo)
        return float(closed.get("amount_brl", 0.0)) if closed.get("trade") else 0.0

    def _build_plan_from_value(self, price: float, trade_value: float, risk_per_trade_pct: float) -> PositionPlan | None:
        if price <= 0 or trade_value <= 0:
            return None
        stop_price = price * (1.0 - (self.config.stop_loss_pct / 100.0))
        take_price = price * (1.0 + (self.config.take_profit_pct / 100.0))
        qty = trade_value / price
        if qty <= 0:
            return None
        return PositionPlan(
            quantity=qty,
            entry_price=price,
            stop_loss=stop_price,
            take_profit=take_price,
            risk_brl=trade_value * (self.config.stop_loss_pct / 100.0),
            risk_pct=self.config.stop_loss_pct,
            notional_brl=trade_value,
            risk_per_trade_pct=risk_per_trade_pct,
        )

    def _signal_strength(self, signal_ctx: dict[str, Any]) -> float:
        dist = float(signal_ctx.get("distancia_percentual") or 0.0)
        slope = abs(float(signal_ctx.get("slope_ema9") or 0.0))
        atr = float(signal_ctx.get("atr") or 0.0)
        price = float(signal_ctx.get("price") or 1.0)
        score = min(1.0, (dist * 20.0) + (slope / max(price, 1.0) * 200.0) + (atr / max(price, 1.0) * 10.0))
        return max(0.0, score)

    def _is_breakout_context(self, signal_ctx: dict[str, Any]) -> bool:
        ema9 = float(signal_ctx.get("ema9") or 0.0)
        ema21 = float(signal_ctx.get("ema21") or 0.0)
        slope = float(signal_ctx.get("slope_ema9") or 0.0)
        price = float(signal_ctx.get("price") or 1.0)
        dist_pct = abs(ema9 - ema21) / max(ema21, 1.0)
        return bool(
            signal_ctx.get("active_mode") == "tendencia"
            and ema9 > ema21
            and slope > (price * 0.0005)
            and dist_pct > 0.002
        )

    def _can_scale_position(self, signal_ctx: dict[str, Any]) -> bool:
        if self.position is None:
            return False
        if self.position_alloc_pct >= self.max_position_size:
            return False
        if self.last_trade_at is not None:
            delta = datetime.utcnow() - self.last_trade_at
            if delta < timedelta(seconds=max(60, self.config.overtrading.min_seconds_between_trades)):
                return False
        self._prune_trade_window(datetime.utcnow())
        if len(self.trade_entries_last_hour) >= self.config.overtrading.max_trades_per_hour:
            return False
        return (
            str(signal_ctx.get("active_mode") or "") == "tendencia"
            and float(signal_ctx.get("ema9") or 0.0) > float(signal_ctx.get("ema21") or 0.0)
            and float(signal_ctx.get("slope_ema9") or 0.0) > 0
        )

    def _scale_in_position(self, price: float, add_value: float, now: datetime, signal_ctx: dict[str, Any]) -> dict[str, Any]:
        if self.position is None or add_value <= 0:
            return {"trade": False, "reason": "scale_in_invalido"}
        btc, fee_brl = self.execution.buy_quote(add_value, price)
        if btc <= 0:
            return {"trade": False, "reason": "scale_in_sem_execucao"}

        pos = self.position
        old_qty = pos.quantity
        new_qty = old_qty + btc
        avg_entry = ((pos.entry_price * old_qty) + (price * btc)) / max(new_qty, 1e-9)
        pos.entry_price = avg_entry
        pos.quantity = new_qty
        pos.entry_spent_brl += add_value
        pos.entry_fee_brl += fee_brl
        pos.stop_loss = avg_entry * (1.0 - (self.config.stop_loss_pct / 100.0))
        pos.take_profit = avg_entry * (1.0 + (self.config.take_profit_pct / 100.0))
        self.current_exposure_brl += add_value
        self.last_trade_at = now
        self.trade_entries_last_hour.append(now)
        self._prune_trade_window(now)
        self.last_trade = {
            "side": "BUY",
            "price": price,
            "btc": btc,
            "fee_brl": fee_brl,
            "timestamp": now.isoformat(timespec="seconds"),
            "reason": "scale_in",
            "active_mode": str(signal_ctx.get("active_mode") or self.active_strategy_mode),
        }
        return {"trade": True, "side": "BUY", "btc": btc, "entry": price, "reason": "scale_in"}

    def _open_position(
        self,
        plan: PositionPlan,
        now: datetime,
        motivo_entrada: str = "strategy",
        saldo_antes: float | None = None,
        strategy_context: dict | None = None,
    ) -> dict[str, Any]:
        quote_brl = plan.notional_brl
        btc, fee_brl = self.execution.buy_quote(quote_brl, plan.entry_price)
        if btc <= 0:
            return {"trade": False, "reason": "falha_execucao_compra"}

        self.position = Position(
            entry_price=plan.entry_price,
            quantity=btc,
            stop_loss=plan.stop_loss,
            take_profit=plan.take_profit,
            highest_price=plan.entry_price,
            risk_brl=plan.risk_brl,
            entry_spent_brl=quote_brl,
            entry_fee_brl=fee_brl,
            opened_at=now,
        )

        self.last_trade_at = now
        self.trade_entries_last_hour.append(now)
        self._prune_trade_window(now)
        self.current_exposure_brl = quote_brl

        if self.trade_manager:
            self.trade_manager.abrir_trade(
                modo=self.mode,
                preco_entrada=plan.entry_price,
                saldo_antes=float(saldo_antes if saldo_antes is not None else self.execution.total_balance_brl(plan.entry_price)),
                quantidade=btc,
                risco_percentual=plan.risk_pct,
                stop_loss=plan.stop_loss,
                take_profit=plan.take_profit,
                motivo_entrada=motivo_entrada,
                taxa_paga=fee_brl,
            )

        self.last_trade = {
            "side": "BUY",
            "price": plan.entry_price,
            "btc": btc,
            "fee_brl": fee_brl,
            "timestamp": now.isoformat(timespec="seconds"),
            "reason": motivo_entrada,
            "risk_per_trade_pct": plan.risk_per_trade_pct,
            "active_mode": str((strategy_context or {}).get("active_mode") or self.active_strategy_mode),
        }

        return {
            "trade": True,
            "side": "BUY",
            "btc": btc,
            "risk_pct": plan.risk_pct,
            "entry": plan.entry_price,
            "risk_per_trade_pct": plan.risk_per_trade_pct,
            "reason": motivo_entrada,
        }

    def _close_position(
        self,
        price_brl: float,
        motivo_saida: str,
        now: datetime,
        technical_reason: str = "",
    ) -> dict[str, Any]:
        if not self.position:
            return {"trade": False, "reason": "sem_posicao"}

        pos = self.position
        amount_brl, fee_brl = self.execution.sell_quantity(pos.quantity, price_brl)
        if amount_brl <= 0:
            return {"trade": False, "reason": "falha_execucao_venda"}
        self.position_alloc_pct = self.initial_alloc_pct


        pnl_brl = amount_brl - pos.entry_spent_brl
        pnl_pct = (pnl_brl / pos.entry_spent_brl) * 100 if pos.entry_spent_brl > 0 else 0.0
        self.lucro_hoje_brl += pnl_brl
        self._register_trade_result(pnl_brl, now)

        saldo_depois = self.execution.total_balance_brl(price_brl)
        if self.trade_manager:
            self.trade_manager.fechar_trade(
                modo=self.mode,
                preco_saida=price_brl,
                saldo_depois=saldo_depois,
                quantidade=pos.quantity,
                lucro_brl=pnl_brl,
                lucro_percentual=pnl_pct,
                motivo_saida=motivo_saida,
                taxa_paga=fee_brl,
            )

        self.last_trade = {
            "side": "SELL",
            "price": price_brl,
            "btc": pos.quantity,
            "fee_brl": fee_brl,
            "pnl_brl": pnl_brl,
            "pnl_pct": pnl_pct,
            "timestamp": now.isoformat(timespec="seconds"),
            "reason": motivo_saida,
        }
        self.trade_history.append(
            {
                "data": now.isoformat(timespec="seconds"),
                "tipo": "SELL",
                "entrada": pos.entry_price,
                "saida": price_brl,
                "lucro": pnl_brl,
                "lucro_pct": pnl_pct,
                "motivo": motivo_saida,
                "active_mode": self.active_strategy_mode,
                "technical_reason": technical_reason,
            }
        )
        if len(self.trade_history) > 400:
            self.trade_history = self.trade_history[-400:]

        self.position = None
        self.position_alloc_pct = 0.0
        self.current_exposure_brl = 0.0
        self._update_equity_stats(price_brl, now)

        return {
            "trade": True,
            "side": "SELL",
            "amount_brl": amount_brl,
            "pnl_brl": pnl_brl,
            "pnl_pct": pnl_pct,
            "reason": motivo_saida,
            "lucro_hoje_brl": self.lucro_hoje_brl,
        }

    def _can_open_trade(self, now: datetime) -> bool:
        if self.position:
            return False

        self._prune_trade_window(now)
        if len(self.trade_entries_last_hour) >= self.config.overtrading.max_trades_per_hour:
            return False

        if not self.last_trade_at:
            return True

        minimo = max(60, self.config.overtrading.min_seconds_between_trades)
        return (now - self.last_trade_at) >= timedelta(seconds=minimo)

    def _prune_trade_window(self, now: datetime) -> None:
        limit = now - timedelta(hours=1)
        while self.trade_entries_last_hour and self.trade_entries_last_hour[0] < limit:
            self.trade_entries_last_hour.popleft()

    def _append_near_trade_log(self, now: datetime, signal_ctx: dict[str, Any]) -> None:
        self.near_trade_logs.append(
            {
                "data": now.isoformat(timespec="seconds"),
                "price_btc": float(signal_ctx.get("price") or 0.0),
                "ema9": float(signal_ctx.get("ema9") or 0.0),
                "ema21": float(signal_ctx.get("ema21") or 0.0),
                "distancia_percentual": float(signal_ctx.get("distancia_percentual") or 0.0),
                "slope": float(signal_ctx.get("slope_ema9") or 0.0),
                "reason": str(signal_ctx.get("reason") or ""),
                "active_mode": str(signal_ctx.get("active_mode") or self.active_strategy_mode),
                "atr": float(signal_ctx.get("atr") or 0.0),
            }
        )
        if len(self.near_trade_logs) > 500:
            self.near_trade_logs = self.near_trade_logs[-500:]

    def _update_equity_stats(self, price_brl: float, now: datetime) -> None:
        equity = self.execution.total_balance_brl(price_brl)

        if self.peak_equity_brl <= 0:
            self.peak_equity_brl = equity
        elif equity > self.peak_equity_brl:
            self.peak_equity_brl = equity

        if self.peak_equity_brl > 0:
            self.current_drawdown_pct = ((self.peak_equity_brl - equity) / self.peak_equity_brl) * 100
            self.max_drawdown_pct = max(self.max_drawdown_pct, self.current_drawdown_pct)

        if self.current_drawdown_pct >= self.config.drawdown_pause_pct:
            self.paused_by_drawdown = True
            if not self._drawdown_alert_sent:
                self.logger.warning(
                    "[%s] drawdown de %.2f%% atingiu limite de %.2f%%. Trades pausados.",
                    self.mode.upper(),
                    self.current_drawdown_pct,
                    self.config.drawdown_pause_pct,
                )
                self._drawdown_alert_sent = True

        if self.equity_curve:
            prev = float(self.equity_curve[-1]["saldo"])
            if prev > 0:
                self.recent_returns.append((equity - prev) / prev)

        self.equity_curve.append({"data": now.isoformat(timespec="seconds"), "saldo": equity})
        self.equity_history.append(equity)
        self.benchmark_history.append(float(price_brl))
        if len(self.equity_history) > 2000:
            self.equity_history = self.equity_history[-2000:]
        if len(self.benchmark_history) > 2000:
            self.benchmark_history = self.benchmark_history[-2000:]

    def get_sharpe_simplificado(self) -> float:
        if len(self.recent_returns) < 2:
            return 0.0
        avg = mean(self.recent_returns)
        std = pstdev(self.recent_returns)
        if std <= 0:
            return 0.0
        return (avg / std) * sqrt(len(self.recent_returns))

    def get_runtime_snapshot(self, price_brl: float) -> dict[str, Any]:
        equity_total = self.execution.total_balance_brl(price_brl)
        equity_operacional = max(0.0, equity_total - self.safe_reserve_brl)
        profit_factor = self._current_profit_factor()
        profit_factor_value = 999.0 if profit_factor == float("inf") else profit_factor

        exposicao_pct = (self.current_exposure_brl / equity_operacional) * 100.0 if equity_operacional > 0 else 0.0
        total_trades = len(self.gain_values) + len(self.loss_values)
        win_rate = (len(self.gain_values) / total_trades) if total_trades > 0 else 0.0
        avg_gain = (sum(self.gain_values) / len(self.gain_values)) if self.gain_values else 0.0
        avg_loss = (sum(self.loss_values) / len(self.loss_values)) if self.loss_values else 0.0
        expectancy = (win_rate * avg_gain) - ((1.0 - win_rate) * avg_loss)

        ema9 = float(self.last_signal_context.get("ema9") or 0.0)
        ema21 = float(self.last_signal_context.get("ema21") or 0.0)
        slope = float(self.last_signal_context.get("slope_ema9") or 0.0)
        dist_pct = float(self.last_signal_context.get("distancia_percentual") or 0.0)
        atr = float(self.last_signal_context.get("atr") or 0.0)
        atr_gate = float(self.last_signal_context.get("atr_gate") or 0.0)

        confluence = {
            "ema_above_sma": ema9 > ema21 if ema21 > 0 else False,
            "sma_slope_up": slope > 0,
            "low_above_ema": True,
            "distancia_ok": (dist_pct > 0) and (atr > 0) and ((abs(ema9 - ema21)) > atr_gate),
        }
        confluence_ok_count = sum(1 for v in confluence.values() if v)
        confluence["veredito"] = "Confluencia confirmada" if confluence_ok_count >= 3 else "Aguardando confluencia"

        return {
            "mode": self.mode,
            "strategy_mode_selected": self.selected_strategy_mode,
            "strategy_mode_active": self.active_strategy_mode,
            "price": price_brl,
            "saldo_brl": self.execution.available_brl(),
            "btc": self.execution.btc_balance(),
            "equity_brl": equity_total,
            "equity_operacional_brl": equity_operacional,
            "equity_atual_brl": equity_total,
            "fee_total_brl": self.execution.total_fee_paid_brl,
            "drawdown_atual_pct": self.current_drawdown_pct,
            "drawdown_max_pct": self.max_drawdown_pct,
            "paused_by_drawdown": self.paused_by_drawdown,
            "position_open": self.position is not None,
            "stop_loss": self.position.stop_loss if self.position else 0.0,
            "take_profit": self.position.take_profit if self.position else 0.0,
            "entry_price": self.position.entry_price if self.position else 0.0,
            "sharpe_simplificado": self.get_sharpe_simplificado(),
            "last_trade": self.last_trade,
            "accumulation_mode": self.accumulation_mode,
            "lucro_hoje_brl": self.lucro_hoje_brl,
            "safe_reserve_brl": self.safe_reserve_brl,
            "patrimonio_protegido_brl": self.safe_reserve_brl,
            "current_exposure_brl": self.current_exposure_brl,
            "current_exposure_pct": exposicao_pct,
            "profit_factor": profit_factor_value,
            "profit_factor_warning": profit_factor_value < 1.2,
            "current_risk_per_trade_pct": self.current_risk_per_trade_pct,
            "consecutive_wins": self.consecutive_wins,
            "consecutive_losses": self.consecutive_losses,
            "pause_until": self.pause_until.isoformat(timespec="seconds") if self.pause_until else "",
            "equity_history": self.equity_history[-500:],
            "benchmark_history": self.benchmark_history[-500:],
            "trade_history": self.trade_history[-200:],
            "near_trade_logs": self.near_trade_logs[-200:],
            "win_rate": win_rate,
            "avg_gain": avg_gain,
            "avg_loss": avg_loss,
            "expectancy": expectancy,
            "risk_status": "verde" if self.current_drawdown_pct < 6 else "amarelo" if self.current_drawdown_pct < 10 else "vermelho",
            "confluence": confluence,
            "last_signal_context": self.last_signal_context,
            "total_cross": self.total_cross,
            "cross_filtrados": self.cross_filtrados,
            "cross_executados": self.cross_executados,
            "trades_lucrativos": len(self.gain_values),
            "trades_prejuizo": len(self.loss_values),
            "lucro_total_brl": self.lucro_hoje_brl,
        }
