from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from math import sqrt
from statistics import mean, pstdev
from typing import Any


@dataclass
class RiskConfig:
    risk_per_trade_pct_base: float = 2.5
    risk_per_trade_pct_aggressive: float = 4.0
    risk_per_trade_pct_defensive: float = 1.25
    max_exposure_pct: float = 40.0
    min_order_value_brl: float = 35.0
    min_rr: float = 1.5


@dataclass
class OvertradingConfig:
    min_seconds_between_trades: int = 180
    max_trades_per_hour: int = 8


@dataclass
class EngineConfig:
    risk: RiskConfig = field(default_factory=RiskConfig)
    overtrading: OvertradingConfig = field(default_factory=OvertradingConfig)
    drawdown_pause_pct: float = 12.0
    sma_short_period: int = 9
    sma_long_period: int = 21
    sma_trend_period: int = 50
    stop_lookback: int = 6


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


class SmaCrossoverStrategy:
    def __init__(self, config: EngineConfig):
        self.config = config
        self.prices: deque[float] = deque(maxlen=1000)
        self.volumes: deque[float] = deque(maxlen=1000)
        self.logger = logging.getLogger(__name__)

    def update_price(self, price: float, volume: float | None = None) -> None:
        if price > 0:
            self.prices.append(float(price))
            self.volumes.append(max(0.0, float(volume or 0.0)))

    def _sma(self, period: int, shift: int = 0) -> float | None:
        arr = list(self.prices)
        if len(arr) < period + shift:
            return None
        if shift == 0:
            sample = arr[-period:]
        else:
            sample = arr[-(period + shift) : -shift]
        return sum(sample) / len(sample)

    def _previous_low_high(self) -> tuple[float | None, float | None]:
        arr = list(self.prices)
        lookback = self.config.stop_lookback
        if len(arr) <= lookback:
            return None, None
        sample = arr[-(lookback + 1) : -1]
        if not sample:
            return None, None
        return min(sample), max(sample)

    @staticmethod
    def _stddev(values: list[float]) -> float:
        if len(values) < 2:
            return 0.0
        return pstdev(values)

    def _rsi(self, period: int = 14) -> float | None:
        prices = list(self.prices)
        if len(prices) < period + 1:
            return None
        gains: list[float] = []
        losses: list[float] = []
        for idx in range(-period, 0):
            delta = prices[idx] - prices[idx - 1]
            if delta >= 0:
                gains.append(delta)
            else:
                losses.append(abs(delta))
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        if avg_loss <= 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def _bollinger(self, period: int = 20, num_std: float = 2.0) -> tuple[float | None, float | None]:
        prices = list(self.prices)
        if len(prices) < period:
            return None, None
        sample = prices[-period:]
        center = sum(sample) / period
        std = self._stddev(sample)
        return center + (num_std * std), center - (num_std * std)

    def _mean_volume(self, period: int = 10) -> float | None:
        vols = list(self.volumes)
        if len(vols) < period:
            return None
        sample = vols[-period:]
        if not sample:
            return None
        return sum(sample) / len(sample)

    def evaluate_signal(self, has_position: bool) -> dict[str, float | bool | str | None]:
        if len(self.prices) < 50:
            return {
                "signal": "none",
                "reason": "dados_insuficientes",
                "slope_sma9": None,
                "distancia_percentual": None,
                "rsi": None,
                "volume_status": "indefinido",
            }

        price = float(self.prices[-1]) if self.prices else 0.0
        short_now = self._sma(self.config.sma_short_period)
        long_now = self._sma(self.config.sma_long_period)
        trend_now = self._sma(self.config.sma_trend_period)
        trend_prev = self._sma(self.config.sma_trend_period, shift=3)
        short_prev = self._sma(self.config.sma_short_period, shift=1)
        long_prev = self._sma(self.config.sma_long_period, shift=1)
        long_prev2 = self._sma(self.config.sma_long_period, shift=3)
        rsi = self._rsi(period=14)
        bb_upper, bb_lower = self._bollinger(period=20, num_std=2.0)
        volume_avg = self._mean_volume(period=10)
        volume_current = float(self.volumes[-1]) if self.volumes else 0.0
        previous_low, previous_high = self._previous_low_high()

        if any(
            x is None
            for x in (
                short_now,
                long_now,
                trend_now,
                trend_prev,
                short_prev,
                long_prev,
                long_prev2,
                rsi,
                bb_lower,
                volume_avg,
            )
        ):
            return {
                "signal": "none",
                "reason": "dados_insuficientes",
                "slope_sma9": None,
                "distancia_percentual": None,
                "rsi": rsi,
                "volume_status": "indefinido",
            }

        assert short_now is not None
        assert long_now is not None
        assert trend_now is not None
        assert trend_prev is not None
        assert short_prev is not None
        assert long_prev is not None
        assert long_prev2 is not None
        assert rsi is not None
        assert bb_lower is not None
        assert bb_upper is not None
        assert volume_avg is not None

        trend = "alta" if price > trend_now else "baixa"
        cross_up = short_prev <= long_prev and short_now > long_now
        cross_down = short_prev >= long_prev and short_now < long_now
        sma21_slope_positive = long_now > long_prev2
        sma50_slope_positive = trend_now > trend_prev
        trend_strength_up = price > trend_now and sma50_slope_positive
        dist_percent = abs(short_now - long_now) / long_now if long_now > 0 else 0.0
        slope_sma9 = short_now - short_prev
        volume_status = "alto" if volume_current > (volume_avg * 1.2) else "baixo"

        base = {
            "short_sma": short_now,
            "long_sma": long_now,
            "trend_sma": trend_now,
            "trend": trend,
            "price": price,
            "previous_low": previous_low,
            "previous_high": previous_high,
            "rsi": rsi,
            "bb_upper": bb_upper,
            "bb_lower": bb_lower,
            "volume_avg": volume_avg,
            "volume_current": volume_current,
            "dist_percent": dist_percent,
            "distancia_percentual": dist_percent,
            "trend_strength_up": trend_strength_up,
            "sma50_slope_positive": sma50_slope_positive,
            "slope_sma9": slope_sma9,
            "volume_status": volume_status,
        }

        if not has_position:
            if short_now <= long_now:
                return {"signal": "none", "reason": "sma9_abaixo_sma21", **base}
            if price <= trend_now:
                return {"signal": "none", "reason": "preco_abaixo_sma50", **base}
            if not sma21_slope_positive:
                return {"signal": "none", "reason": "sma21_sem_inclinacao_positiva", **base}
            if dist_percent < 0.003:
                return {"signal": "none", "reason": "distancia_sma_insuficiente", **base}

            score = 0
            if cross_up:
                score += 1
            if rsi < 40.0:
                score += 1
            if price <= bb_lower:
                score += 1
            if volume_current > (volume_avg * 1.2):
                score += 1
            if score < 3:
                return {"signal": "none", "reason": "confluencia_insuficiente", "score": score, **base}
            return {"signal": "buy", "reason": "entrada_confluencia_forte", "score": score, **base}

        if cross_down and price < trend_now:
            return {"signal": "sell", "reason": "cruzamento_sma9_abaixo_sma21_com_tendencia_baixa", **base}

        return {"signal": "none", "reason": "manter_posicao", **base}


class RiskManager:
    def __init__(self, risk_config: RiskConfig):
        self.config = risk_config

    def build_position_plan(
        self,
        equity_brl: float,
        available_brl: float,
        entry_price: float,
        stop_price: float,
        max_buy_brl: float,
        risk_per_trade_pct: float,
    ) -> PositionPlan | None:
        if equity_brl <= 0 or available_brl <= 0 or entry_price <= 0:
            return None
        if stop_price <= 0 or stop_price >= entry_price:
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

        take_profit = entry_price + (entry_price - stop_price) * self.config.min_rr
        risk_pct = ((entry_price - stop_price) / entry_price) * 100

        return PositionPlan(
            quantity=quantity,
            entry_price=entry_price,
            stop_loss=stop_price,
            take_profit=take_profit,
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
        brl = self.available_brl()
        btc = self.btc_balance()
        return brl + (btc * price_brl)

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

        step_qty = round(qty, 6)
        order = self.client.create_order(
            symbol="BTCBRL",
            side="SELL",
            type="MARKET",
            quantity=step_qty,
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

        self.strategy = SmaCrossoverStrategy(self.config)
        self.risk_manager = RiskManager(self.config.risk)

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

    def set_drawdown_limit(self, pct: float) -> None:
        self.config.drawdown_pause_pct = max(0.5, float(pct))

    def set_accumulation_mode(self, enabled: bool) -> None:
        self.accumulation_mode = bool(enabled)

    def set_risk_profile(self, profile_name: str) -> None:
        key = str(profile_name).strip().lower()
        if key == "conservador":
            self.config.risk = RiskConfig(
                risk_per_trade_pct_base=2.0,
                risk_per_trade_pct_aggressive=3.2,
                risk_per_trade_pct_defensive=1.0,
                max_exposure_pct=30.0,
                min_order_value_brl=35.0,
                min_rr=1.8,
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
                min_rr=1.5,
            )
            self.config.overtrading = OvertradingConfig(min_seconds_between_trades=180, max_trades_per_hour=8)
            self.config.drawdown_pause_pct = 15.0
        else:
            self.config.risk = RiskConfig()
            self.config.overtrading = OvertradingConfig(min_seconds_between_trades=180, max_trades_per_hour=8)
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
        if self.consecutive_losses >= 5:
            risk = self.config.risk.risk_per_trade_pct_defensive
        elif self.consecutive_losses >= 3:
            risk = self.config.risk.risk_per_trade_pct_defensive
        else:
            pf = self._current_profit_factor()
            last3_wins = len(self.trade_outcomes) >= 3 and all(list(self.trade_outcomes)[-3:])
            trend_strong = bool((signal_ctx or {}).get("trend_strength_up"))
            if pf > 1.4 and last3_wins and trend_strong:
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
                reserva = lucro_brl * 0.30
                self.safe_reserve_brl += reserva
        elif lucro_brl < 0:
            loss = abs(lucro_brl)
            self.total_losses_brl += loss
            self.loss_values.append(loss)
            self.trade_outcomes.append(False)
            self.consecutive_losses += 1
            self.consecutive_wins = 0
            if self.consecutive_losses >= 5:
                self.pause_until = now + timedelta(minutes=30)
                self.logger.warning(
                    "[%s] 5 perdas consecutivas: pausando novas entradas ate %s",
                    self.mode.upper(),
                    self.pause_until.isoformat(timespec="seconds"),
                )

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
        self.strategy.update_price(price, volume=volume)
        equity_before = self._current_equity_total(price)
        self._update_equity_stats(price, now)

        if self.pause_until is not None and now < self.pause_until:
            return {"trade": False, "reason": "pausa_5_perdas", "resume_at": self.pause_until.isoformat(timespec="seconds")}
        if self.pause_until is not None and now >= self.pause_until:
            self.pause_until = None

        if self.paused_by_drawdown:
            self.logger.info("[%s] pausado por drawdown %.2f%%", self.mode, self.current_drawdown_pct)
            return {"trade": False, "reason": "pausado_drawdown", "drawdown": self.current_drawdown_pct}

        signal_ctx = self.strategy.evaluate_signal(has_position=self.position is not None)
        self.last_signal_context = dict(signal_ctx)
        short_sma = float(signal_ctx.get("short_sma") or 0.0)
        long_sma = float(signal_ctx.get("long_sma") or 0.0)
        trend_sma = float(signal_ctx.get("trend_sma") or 0.0)
        trend = str(signal_ctx.get("trend") or "indefinida")

        if self.position:
            should_exit, exit_reason = self.risk_manager.evaluate_exit(self.position, price)
            if should_exit:
                return self._close_position(price, exit_reason, now, technical_reason="saida_por_risco")

            if signal_ctx.get("signal") == "sell":
                return self._close_position(price, "SMA_EXIT", now, technical_reason=str(signal_ctx.get("reason") or "sma"))

            self.logger.info(
                "[%s] NAO VENDEU | motivo=%s | sma9=%.2f | sma21=%.2f | sma50=%.2f | tendencia=%s",
                self.mode.upper(),
                str(signal_ctx.get("reason") or "manter_posicao"),
                short_sma,
                long_sma,
                trend_sma,
                trend,
            )
            print(
                f"[{self.mode.upper()}] NO-SELL | motivo={str(signal_ctx.get('reason') or 'manter_posicao')} | "
                f"sma9={short_sma:.2f} sma21={long_sma:.2f} sma50={trend_sma:.2f} | tendencia={trend}"
            )
            return {"trade": False, "reason": "posicao_aberta", "drawdown": self.current_drawdown_pct}

        if signal_ctx.get("signal") != "buy":
            self._append_near_trade_log(now, signal_ctx)
            self.logger.info(
                "[%s] NAO COMPROU | motivo=%s | sma9=%.2f | sma21=%.2f | sma50=%.2f | tendencia=%s",
                self.mode.upper(),
                str(signal_ctx.get("reason") or "sem_sinal"),
                short_sma,
                long_sma,
                trend_sma,
                trend,
            )
            print(
                f"[{self.mode.upper()}] NO-BUY | motivo={str(signal_ctx.get('reason') or 'sem_sinal')} | "
                f"sma9={short_sma:.2f} sma21={long_sma:.2f} sma50={trend_sma:.2f} | tendencia={trend}"
            )
            return {"trade": False, "reason": str(signal_ctx.get("reason") or "sem_sinal"), "drawdown": self.current_drawdown_pct}

        self._update_risk_regime(signal_ctx)

        if not self._can_open_trade(now):
            self._append_near_trade_log(now, signal_ctx)
            self.logger.info(
                "[%s] NAO COMPROU | motivo=filtro_overtrading | sma9=%.2f | sma21=%.2f | sma50=%.2f | tendencia=%s",
                self.mode.upper(),
                short_sma,
                long_sma,
                trend_sma,
                trend,
            )
            return {"trade": False, "reason": "filtro_overtrading", "drawdown": self.current_drawdown_pct}

        previous_low = signal_ctx.get("previous_low")
        if previous_low is None:
            return {"trade": False, "reason": "sem_stop_minima_anterior", "drawdown": self.current_drawdown_pct}

        equity_for_risk = self._equity_for_risk(price)
        plan = self.risk_manager.build_position_plan(
            equity_brl=equity_for_risk,
            available_brl=self.execution.available_brl(),
            entry_price=price,
            stop_price=float(previous_low),
            max_buy_brl=self.max_buy_brl,
            risk_per_trade_pct=self.current_risk_per_trade_pct,
        )
        if not plan:
            return {"trade": False, "reason": "sem_position_size", "drawdown": self.current_drawdown_pct}

        return self._open_position(
            plan,
            now,
            saldo_antes=equity_before,
            motivo_entrada=str(signal_ctx.get("reason") or "sma_entry"),
            strategy_context=signal_ctx,
        )

    def force_buy(self, price_brl: float, motivo: str = "manual") -> float:
        equity = self._equity_for_risk(price_brl)
        signal_ctx = self.strategy.evaluate_signal(has_position=False)
        previous_low = signal_ctx.get("previous_low")
        if previous_low is None:
            previous_low = float(price_brl) * 0.995

        self._update_risk_regime(signal_ctx)
        plan = self.risk_manager.build_position_plan(
            equity_brl=equity,
            available_brl=self.execution.available_brl(),
            entry_price=float(price_brl),
            stop_price=float(previous_low),
            max_buy_brl=self.max_buy_brl,
            risk_per_trade_pct=self.current_risk_per_trade_pct,
        )
        if not plan or self.position:
            return 0.0

        opened = self._open_position(
            plan,
            datetime.utcnow(),
            motivo_entrada=motivo,
            saldo_antes=self.execution.total_balance_brl(float(price_brl)),
            strategy_context=signal_ctx,
        )
        return float(opened.get("btc", 0.0)) if opened.get("trade") else 0.0

    def force_sell(self, price_brl: float, motivo: str = "manual") -> float:
        if not self.position:
            return 0.0
        closed = self._close_position(float(price_brl), motivo, datetime.utcnow(), technical_reason=motivo)
        return float(closed.get("amount_brl", 0.0)) if closed.get("trade") else 0.0

    def _open_position(
        self,
        plan: PositionPlan,
        now: datetime,
        motivo_entrada: str = "sma_crossover",
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
        }

        saldo_total = self.execution.total_balance_brl(plan.entry_price)
        short_sma = float((strategy_context or {}).get("short_sma") or 0.0)
        long_sma = float((strategy_context or {}).get("long_sma") or 0.0)
        trend_sma = float((strategy_context or {}).get("trend_sma") or 0.0)

        print(
            f"[{self.mode.upper()}] BUY | entrada={plan.entry_price:.2f} | risco={plan.risk_pct:.2f}% "
            f"| alocacao={quote_brl:.2f} | risco_trade={plan.risk_per_trade_pct:.2f}% | "
            f"stop={plan.stop_loss:.2f} | tp={plan.take_profit:.2f} | taxa={fee_brl:.2f} | saldo={saldo_total:.2f}"
        )
        self.logger.info(
            "[%s] ENTRADA | motivo=%s | sma9=%.2f | sma21=%.2f | sma50=%.2f | tendencia=%s",
            self.mode.upper(),
            motivo_entrada,
            short_sma,
            long_sma,
            trend_sma,
            str((strategy_context or {}).get("trend") or "indefinida"),
        )

        return {
            "trade": True,
            "side": "BUY",
            "btc": btc,
            "risk_pct": plan.risk_pct,
            "entry": plan.entry_price,
            "risk_per_trade_pct": plan.risk_per_trade_pct,
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

        pnl_brl = amount_brl - pos.entry_spent_brl
        pnl_pct = (pnl_brl / pos.entry_spent_brl) * 100 if pos.entry_spent_brl > 0 else 0.0
        lucro = pnl_brl
        self.lucro_hoje_brl += lucro
        self._register_trade_result(lucro, now)

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
                "motivo": motivo_saida,
            }
        )
        if len(self.trade_history) > 400:
            self.trade_history = self.trade_history[-400:]

        print(
            f"[{self.mode.upper()}] SELL | saida={price_brl:.2f} | lucro={pnl_pct:+.2f}% | "
            f"motivo={motivo_saida} | taxa={fee_brl:.2f} | saldo={saldo_depois:.2f}"
        )
        self.logger.info(
            "[%s] SAIDA | motivo=%s | tecnico=%s | pnl_brl=%.2f | pnl_pct=%.2f%%",
            self.mode.upper(),
            motivo_saida,
            technical_reason,
            pnl_brl,
            pnl_pct,
        )

        self.position = None
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

        minimo = max(180, self.config.overtrading.min_seconds_between_trades)
        delta = now - self.last_trade_at
        return delta >= timedelta(seconds=minimo)

    def _prune_trade_window(self, now: datetime) -> None:
        limit = now - timedelta(hours=1)
        while self.trade_entries_last_hour and self.trade_entries_last_hour[0] < limit:
            self.trade_entries_last_hour.popleft()

    def _append_near_trade_log(self, now: datetime, signal_ctx: dict[str, Any]) -> None:
        self.near_trade_logs.append(
            {
                "data": now.isoformat(timespec="seconds"),
                "reason": str(signal_ctx.get("reason") or ""),
                "sma9": float(signal_ctx.get("short_sma") or 0.0),
                "sma21": float(signal_ctx.get("long_sma") or 0.0),
                "sma50": float(signal_ctx.get("trend_sma") or 0.0),
                "rsi": float(signal_ctx.get("rsi") or 0.0),
                "volume_status": str(signal_ctx.get("volume_status") or "indefinido"),
                "distancia_percentual": float(signal_ctx.get("distancia_percentual") or 0.0),
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
        if profit_factor == float("inf"):
            profit_factor_value = 999.0
        else:
            profit_factor_value = profit_factor
        exposicao_pct = (self.current_exposure_brl / equity_operacional) * 100.0 if equity_operacional > 0 else 0.0
        total_trades = len(self.gain_values) + len(self.loss_values)
        win_rate = (len(self.gain_values) / total_trades) if total_trades > 0 else 0.0
        avg_gain = (sum(self.gain_values) / len(self.gain_values)) if self.gain_values else 0.0
        avg_loss = (sum(self.loss_values) / len(self.loss_values)) if self.loss_values else 0.0
        expectancy = (win_rate * avg_gain) - ((1.0 - win_rate) * avg_loss)
        if self.current_drawdown_pct < 6.0:
            risk_status = "verde"
        elif self.current_drawdown_pct < 10.0:
            risk_status = "amarelo"
        else:
            risk_status = "vermelho"

        confluence = {
            "rsi_ok": float(self.last_signal_context.get("rsi") or 100.0) < 40.0,
            "distancia_ok": float(self.last_signal_context.get("distancia_percentual") or 0.0) >= 0.003,
            "volume_ok": str(self.last_signal_context.get("volume_status") or "baixo") == "alto",
            "bollinger_ok": float(self.last_signal_context.get("price") or 0.0) <= float(self.last_signal_context.get("bb_lower") or 0.0),
        }
        confluence_ok_count = sum(1 for v in confluence.values() if v)
        confluence["veredito"] = "Confluência confirmada" if confluence_ok_count >= 3 else "Aguardando confluência"

        return {
            "mode": self.mode,
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
            "risk_status": risk_status,
            "confluence": confluence,
            "last_signal_context": self.last_signal_context,
        }
