from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from email.mime import base
from core.volatility import AtrCalculator


@dataclass
class StrategyConfig:
    ema_fast_period: int = 9
    ema_slow_period: int = 21
    atr_period: int = 14
    atr_min_factor: float = 0.2
    slope_lookback: int = 5
    bb_period: int = 20
    bb_num_std: float = 2.0


class StrategyEngine:
    def __init__(self, config: StrategyConfig | None = None):
        self.config = config or StrategyConfig()
        self.prices: deque[float] = deque(maxlen=3000)
        self.highs: deque[float] = deque(maxlen=3000)
        self.lows: deque[float] = deque(maxlen=3000)
        self.volumes: deque[float] = deque(maxlen=3000)

        self.ema_fast: deque[float] = deque(maxlen=3000)
        self.ema_slow: deque[float] = deque(maxlen=3000)
        self.atr_calc = AtrCalculator(period=self.config.atr_period)

    def update_tick(self, price: float, high: float | None = None, low: float | None = None, volume: float = 0.0) -> None:
        p = float(price)
        if p <= 0:
            return

        h = float(high if high is not None else p)
        l = float(low if low is not None else p)

        self.prices.append(p)
        self.highs.append(h)
        self.lows.append(l)
        self.volumes.append(max(0.0, float(volume)))

        self._update_ema(p)
        self.atr_calc.update(h, l, p)
        print("TICK RECEBIDO:", price)

        p = float(price)
        if p <= 0:
                print("PREÇO INVALIDO")
                return

    def _update_ema(self, price: float) -> None:
        alpha_fast = 2.0 / (self.config.ema_fast_period + 1.0)
        alpha_slow = 2.0 / (self.config.ema_slow_period + 1.0)

        prev_fast = self.ema_fast[-1] if self.ema_fast else price
        prev_slow = self.ema_slow[-1] if self.ema_slow else price

        self.ema_fast.append((price * alpha_fast) + (prev_fast * (1.0 - alpha_fast)))
        self.ema_slow.append((price * alpha_slow) + (prev_slow * (1.0 - alpha_slow)))

    def _slope(self, series: deque[float], lookback: int) -> float | None:
        if len(series) < lookback:
            return None
        return float(series[-1] - series[-lookback])

    def evaluate(self, has_position: bool, selected_mode: str = "auto") -> dict:

        # 1️⃣ checa se já tem dados suficientes
        if len(self.ema_fast) < max(self.config.ema_slow_period, self.config.slope_lookback + 1):
            price = float(self.prices[-1]) if self.prices else 0.0

            return {
                "signal": "none",
                "reason": "dados_insuficientes",
                "price": price,
                "ema9": self.ema_fast[-1] if self.ema_fast else price,
                "ema21": self.ema_slow[-1] if self.ema_slow else price,
            }

        # 2️⃣ cálculo normal da estratégia
        price = float(self.prices[-1])
        ema9 = float(self.ema_fast[-1])
        ema21 = float(self.ema_slow[-1])

        prev_ema9 = float(self.ema_fast[-2]) if len(self.ema_fast) > 1 else ema9
        prev_ema21 = float(self.ema_slow[-2]) if len(self.ema_slow) > 1 else ema21

        slope_ema9 = self._slope(self.ema_fast, self.config.slope_lookback)
        slope_ema21 = self._slope(self.ema_slow, self.config.slope_lookback)

        atr = self.atr_calc.value()

        dist = abs(ema9 - ema21)
        dist_pct = (dist / ema21) if ema21 > 0 else 0.0

        atr_gate = (atr * self.config.atr_min_factor) if atr is not None else None

        regime = "tendencia"

        base = {
            "price": price,
            "ema9": ema9,
            "ema21": ema21,
            "ema9_prev": prev_ema9,
            "ema21_prev": prev_ema21,
            "slope_ema9": slope_ema9,
            "slope_ema21": slope_ema21,
            "atr": atr,
            "atr_gate": atr_gate,
            "distancia_absoluta": dist,
            "distancia_percentual": dist_pct,
            "selected_mode": selected_mode,
            "active_mode": regime,
        }

        print("TICKS EMA:", len(self.ema_fast))

        # 3️⃣ executa estratégia
        if regime == "tendencia":
            return self._evaluate_trend(has_position=has_position, base=base)

        return {"signal": "none", "reason": "regime_indefinido", **base}