from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class RiskConfig:
    risk_per_trade_pct_base: float = 2.5
    risk_per_trade_pct_aggressive: float = 4.0
    risk_per_trade_pct_defensive: float = 1.25
    max_exposure_pct: float = 40.0
    min_order_value_brl: float = 35.0


def calculate_position_size(capital: float, risk_percent: float) -> float:
    """Retorna o valor financeiro da posição baseado no risco (% do capital)."""
    c = max(0.0, float(capital))
    rp = max(0.0, float(risk_percent))
    return c * rp


def calculate_quantity_from_value(trade_value: float, price: float) -> float:
    """Converte valor financeiro da posição em quantidade do ativo."""
    if price <= 0:
        return 0.0
    return max(0.0, float(trade_value) / float(price))


def scale_position(
    signal_strength: float,
    scaling_steps: list,
    current_alloc_pct: float,
    max_position_size: float,
) -> float:
    """
    Calcula nova alocação de capital ao escalar posição.

    signal_strength   → força do sinal (0 a 1)
    scaling_steps     → lista de passos de escala (ex: [0.02, 0.02, 0.03])
    current_alloc_pct → alocação atual (% do capital, ex: 0.10)
    max_position_size → limite máximo (% do capital, ex: 0.30)
    """
    strength = max(0.0, min(1.0, float(signal_strength)))

    if not scaling_steps:
        return current_alloc_pct

    # Encontra o próximo passo disponível
    steps = [max(0.0, float(s)) for s in scaling_steps]
    step_size = steps[0] if steps else 0.02

    new_alloc = current_alloc_pct + (step_size * strength)
    return min(new_alloc, float(max_position_size))


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


class Position:
    """Representa uma posição aberta."""

    def __init__(
        self,
        side: str,
        entry_price: float,
        quantity: float,
        stop_loss: float,
        take_profit: float,
        risk_brl: float = 0.0,
        entry_spent_brl: float = 0.0,
        entry_fee_brl: float = 0.0,
        opened_at=None,
    ):
        from datetime import datetime

        self.side = side
        self.entry_price = float(entry_price)
        self.quantity = float(quantity)
        self.stop_loss = float(stop_loss)
        self.take_profit = float(take_profit)
        self.risk_brl = float(risk_brl)
        self.entry_spent_brl = float(entry_spent_brl)
        self.entry_fee_brl = float(entry_fee_brl)
        self.opened_at = opened_at or datetime.utcnow()

        # Usado pelo trailing stop
        self.highest_price = float(entry_price)


class RiskManager:
    """Gerencia tamanho de posição, stops e avaliação de saída."""

    def __init__(self, risk_config: Optional[RiskConfig] = None):
        # FIX: armazena config corretamente
        self.config = risk_config or RiskConfig()

        self.initial_alloc_pct = 0.10
        self.scale_step_pct = 0.10
        self.max_position_size = 0.30
        self.position_alloc_pct = self.initial_alloc_pct
        self.trailing_activation_pct = 1.0
        self.trailing_distance_pct = 0.7

    def build_position_plan(
        self,
        equity_brl: float,
        available_brl: float,
        entry_price: float,
        stop_price: float,
        take_price: float,
        max_buy_brl: float,
        risk_per_trade_pct: float,
    ) -> Optional[PositionPlan]:
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
        # FIX: usa self.config corretamente
        max_exposure_value = equity_brl * (self.config.max_exposure_pct / 100.0)
        position_value_from_risk = (risk_value / risk_per_unit) * entry_price

        cap = min(
            available_brl,
            max_buy_brl if max_buy_brl > 0 else available_brl,
            max_exposure_value,
        )
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
        """Verifica stop loss e take profit."""
        if current_price <= position.stop_loss:
            return True, "SL"
        if current_price >= position.take_profit:
            return True, "TP"
        return False, ""

    def update_trailing_stop(
        self,
        position: Position,
        current_price: float,
        activation_pct: float = 1.0,
        distance_pct: float = 0.7,
    ) -> None:
        """Atualiza trailing stop se preço subiu suficientemente."""
        if current_price > position.highest_price:
            position.highest_price = current_price

        profit_pct = (current_price - position.entry_price) / position.entry_price * 100

        if profit_pct >= activation_pct:
            new_stop = position.highest_price * (1 - distance_pct / 100)
            if new_stop > position.stop_loss:
                position.stop_loss = new_stop