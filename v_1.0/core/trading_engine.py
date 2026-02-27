from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from math import sqrt
from statistics import mean, pstdev


@dataclass
class RiskConfig:
    risk_per_trade_pct: float = 0.5
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
        self.logger = logging.getLogger(__name__)

    def update_price(self, price: float) -> None:
        if price > 0:
            self.prices.append(float(price))

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

    def evaluate_signal(self, has_position: bool) -> dict[str, float | bool | str | None]:
        price = float(self.prices[-1]) if self.prices else 0.0
        short_now = self._sma(self.config.sma_short_period)
        long_now = self._sma(self.config.sma_long_period)
        trend_now = self._sma(self.config.sma_trend_period)

        short_prev = self._sma(self.config.sma_short_period, shift=1)
        long_prev = self._sma(self.config.sma_long_period, shift=1)

        previous_low, previous_high = self._previous_low_high()

        if any(x is None for x in (short_now, long_now, trend_now, short_prev, long_prev)):
            return {
                "signal": "none",
                "reason": "dados_insuficientes",
                "short_sma": short_now,
                "long_sma": long_now,
                "trend_sma": trend_now,
                "trend": "indefinida",
                "price": price,
                "previous_low": previous_low,
                "previous_high": previous_high,
            }

        assert short_now is not None
        assert long_now is not None
        assert trend_now is not None
        assert short_prev is not None
        assert long_prev is not None

        trend = "alta" if price > trend_now else "baixa"
        cross_up = short_prev <= long_prev and short_now > long_now
        cross_down = short_prev >= long_prev and short_now < long_now

        if not has_position:
            if not cross_up:
                reason = "sem_cruzamento_alta"
                if short_now <= long_now:
                    reason = "sma9_abaixo_sma21"
                return {
                    "signal": "none",
                    "reason": reason,
                    "short_sma": short_now,
                    "long_sma": long_now,
                    "trend_sma": trend_now,
                    "trend": trend,
                    "price": price,
                    "previous_low": previous_low,
                    "previous_high": previous_high,
                }

            if price <= trend_now:
                return {
                    "signal": "none",
                    "reason": "filtro_tendencia_compra_bloqueado_preco_abaixo_sma50",
                    "short_sma": short_now,
                    "long_sma": long_now,
                    "trend_sma": trend_now,
                    "trend": trend,
                    "price": price,
                    "previous_low": previous_low,
                    "previous_high": previous_high,
                }

            return {
                "signal": "buy",
                "reason": "cruzamento_sma9_acima_sma21_com_tendencia_alta",
                "short_sma": short_now,
                "long_sma": long_now,
                "trend_sma": trend_now,
                "trend": trend,
                "price": price,
                "previous_low": previous_low,
                "previous_high": previous_high,
            }

        if cross_down and price < trend_now:
            return {
                "signal": "sell",
                "reason": "cruzamento_sma9_abaixo_sma21_com_tendencia_baixa",
                "short_sma": short_now,
                "long_sma": long_now,
                "trend_sma": trend_now,
                "trend": trend,
                "price": price,
                "previous_low": previous_low,
                "previous_high": previous_high,
            }

        return {
            "signal": "none",
            "reason": "manter_posicao",
            "short_sma": short_now,
            "long_sma": long_now,
            "trend_sma": trend_now,
            "trend": trend,
            "price": price,
            "previous_low": previous_low,
            "previous_high": previous_high,
        }


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
    ) -> PositionPlan | None:
        if equity_brl <= 0 or available_brl <= 0 or entry_price <= 0:
            return None
        if stop_price <= 0 or stop_price >= entry_price:
            return None

        risk_per_unit = entry_price - stop_price
        risk_brl = equity_brl * (self.config.risk_per_trade_pct / 100.0)

        quantity = risk_brl / risk_per_unit
        notional_brl = quantity * entry_price

        cap = min(available_brl, max_buy_brl if max_buy_brl > 0 else available_brl)
        if notional_brl > cap and cap > 0:
            quantity = cap / entry_price
            notional_brl = cap
            risk_brl = quantity * risk_per_unit

        if quantity <= 0 or notional_brl <= 0:
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
        self.last_trade_at: datetime | None = None
        self.trade_entries_last_hour: deque[datetime] = deque()

        self.equity_curve: list[dict[str, float | str]] = []
        self.recent_returns: deque[float] = deque(maxlen=80)

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
        self.last_trade_at = None
        self.trade_entries_last_hour.clear()
        self.equity_curve.clear()
        self.recent_returns.clear()

    def set_drawdown_limit(self, pct: float) -> None:
        self.config.drawdown_pause_pct = max(0.5, float(pct))

    def set_risk_profile(self, profile_name: str) -> None:
        key = str(profile_name).strip().lower()
        if key == "conservador":
            self.config.risk = RiskConfig(risk_per_trade_pct=0.3, min_rr=1.8)
            self.config.overtrading = OvertradingConfig(min_seconds_between_trades=240, max_trades_per_hour=6)
            self.config.drawdown_pause_pct = 8.0
        elif key == "agressivo":
            self.config.risk = RiskConfig(risk_per_trade_pct=0.5, min_rr=1.5)
            self.config.overtrading = OvertradingConfig(min_seconds_between_trades=180, max_trades_per_hour=8)
            self.config.drawdown_pause_pct = 15.0
        else:
            self.config.risk = RiskConfig(risk_per_trade_pct=0.5, min_rr=1.5)
            self.config.overtrading = OvertradingConfig(min_seconds_between_trades=180, max_trades_per_hour=8)
            self.config.drawdown_pause_pct = 12.0

        self.risk_manager = RiskManager(self.config.risk)

    def on_price(self, price_brl: float, now: datetime | None = None) -> dict[str, float | str | bool]:
        price = float(price_brl)
        if price <= 0:
            return {"trade": False, "reason": "preco_invalido"}

        now = now or datetime.utcnow()
        self.strategy.update_price(price)
        equity_before = self.execution.total_balance_brl(price)
        self._update_equity_stats(price, now)

        if self.paused_by_drawdown:
            self.logger.info("[%s] pausado por drawdown %.2f%%", self.mode, self.current_drawdown_pct)
            return {"trade": False, "reason": "pausado_drawdown", "drawdown": self.current_drawdown_pct}

        signal_ctx = self.strategy.evaluate_signal(has_position=self.position is not None)
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

        if not self._can_open_trade(now):
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

        plan = self.risk_manager.build_position_plan(
            equity_brl=equity_before,
            available_brl=self.execution.available_brl(),
            entry_price=price,
            stop_price=float(previous_low),
            max_buy_brl=self.max_buy_brl,
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
        equity = self.execution.total_balance_brl(price_brl)
        signal_ctx = self.strategy.evaluate_signal(has_position=False)
        previous_low = signal_ctx.get("previous_low")
        if previous_low is None:
            previous_low = float(price_brl) * 0.995

        plan = self.risk_manager.build_position_plan(
            equity_brl=equity,
            available_brl=self.execution.available_brl(),
            entry_price=float(price_brl),
            stop_price=float(previous_low),
            max_buy_brl=self.max_buy_brl,
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
    ) -> dict[str, float | str | bool]:
        quote_brl = plan.quantity * plan.entry_price
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

        saldo_total = self.execution.total_balance_brl(plan.entry_price)
        short_sma = float((strategy_context or {}).get("short_sma") or 0.0)
        long_sma = float((strategy_context or {}).get("long_sma") or 0.0)
        trend_sma = float((strategy_context or {}).get("trend_sma") or 0.0)

        print(
            f"[{self.mode.upper()}] BUY | entrada={plan.entry_price:.2f} | risco={plan.risk_pct:.2f}% | "
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
        }

    def _close_position(
        self,
        price_brl: float,
        motivo_saida: str,
        now: datetime,
        technical_reason: str = "",
    ) -> dict[str, float | str | bool]:
        if not self.position:
            return {"trade": False, "reason": "sem_posicao"}

        pos = self.position
        amount_brl, fee_brl = self.execution.sell_quantity(pos.quantity, price_brl)
        if amount_brl <= 0:
            return {"trade": False, "reason": "falha_execucao_venda"}

        pnl_brl = amount_brl - pos.entry_spent_brl
        pnl_pct = (pnl_brl / pos.entry_spent_brl) * 100 if pos.entry_spent_brl > 0 else 0.0

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
        self._update_equity_stats(price_brl, now)

        return {
            "trade": True,
            "side": "SELL",
            "amount_brl": amount_brl,
            "pnl_brl": pnl_brl,
            "pnl_pct": pnl_pct,
            "reason": motivo_saida,
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

        if self.equity_curve:
            prev = float(self.equity_curve[-1]["saldo"])
            if prev > 0:
                self.recent_returns.append((equity - prev) / prev)

        self.equity_curve.append({"data": now.isoformat(timespec="seconds"), "saldo": equity})

    def get_sharpe_simplificado(self) -> float:
        if len(self.recent_returns) < 2:
            return 0.0
        avg = mean(self.recent_returns)
        std = pstdev(self.recent_returns)
        if std <= 0:
            return 0.0
        return (avg / std) * sqrt(len(self.recent_returns))

    def get_runtime_snapshot(self, price_brl: float) -> dict[str, float | str | bool]:
        return {
            "mode": self.mode,
            "price": price_brl,
            "saldo_brl": self.execution.available_brl(),
            "btc": self.execution.btc_balance(),
            "equity_brl": self.execution.total_balance_brl(price_brl),
            "fee_total_brl": self.execution.total_fee_paid_brl,
            "drawdown_atual_pct": self.current_drawdown_pct,
            "drawdown_max_pct": self.max_drawdown_pct,
            "paused_by_drawdown": self.paused_by_drawdown,
            "position_open": self.position is not None,
            "stop_loss": self.position.stop_loss if self.position else 0.0,
            "take_profit": self.position.take_profit if self.position else 0.0,
            "entry_price": self.position.entry_price if self.position else 0.0,
            "sharpe_simplificado": self.get_sharpe_simplificado(),
        }
