from __future__ import annotations

import math
from typing import Any


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
    scaling_steps: int,
    current_alloc_pct: float,
    max_position_size: float,
) -> float:
    """
    Calcula nova alocação de capital ao escalar posição.
    
    signal_strength -> força do sinal (0 a 1)
    scaling_steps -> quantos passos de escala existem
    current_alloc_pct -> alocação atual (% capital)
    max_position_size -> limite máximo (% capital)
    """

    strength = max(0.0, min(1.0, float(signal_strength)))
    steps = max(1, int(scaling_steps))

    step_size = max_position_size / steps

    # aumenta posição proporcional à força do sinal
    new_alloc = current_alloc_pct + (step_size * strength)

    return min(new_alloc, max_position_size)