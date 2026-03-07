from __future__ import annotations


def calculate_position_size(capital: float, risk_percent: float) -> float:
    """Retorna o valor financeiro da posição baseado no risco (% do capital)."""
    c = max(0.0, float(capital))
    rp = max(0.0, float(risk_percent))
    return c * rp


def calculate_quantity_from_value(trade_value: float, price: float) -> float:
    if price <= 0:
        return 0.0
    return max(0.0, float(trade_value) / float(price))


def scale_position(
    signal_strength: float,
    scaling_steps: list[float],
    current_alloc_pct: float,
    max_position_size: float,
) -> float:
    """
    Retorna novo percentual de alocação acumulado após scaling.
    """
    steps = list(scaling_steps or [0.02, 0.02, 0.03])
    current = max(0.0, float(current_alloc_pct))
    max_alloc = max(0.01, float(max_position_size))
    strength = max(0.0, min(1.0, float(signal_strength)))

    idx = min(len(steps) - 1, int(strength * len(steps)))
    add_pct = max(0.0, float(steps[idx]))
    return min(max_alloc, current + add_pct)
