from __future__ import annotations


def detect_market_regime(
    atr: float | None,
    ema21_slope: float | None,
    price: float,
    atr_trend_threshold_pct: float = 0.003,
    slope_threshold_pct: float = 0.0008,
) -> str:
    """
    Detecta regime com base em volatilidade (ATR) e inclinação da EMA21.

    Retorna:
    - "tendencia"
    - "lateral"
    """
    if price <= 0 or atr is None or ema21_slope is None:
        return "lateral"

    atr_pct = atr / price
    slope_pct = abs(ema21_slope) / price

    if atr_pct >= atr_trend_threshold_pct and slope_pct >= slope_threshold_pct:
        return "tendencia"
    return "lateral"
