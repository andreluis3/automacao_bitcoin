from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from statistics import pstdev

from core.market_regime import detect_market_regime
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

    def _update_ema(self, price: float) -> None:
        alpha_fast = 2.0 / (self.config.ema_fast_period + 1.0)
        alpha_slow = 2.0 / (self.config.ema_slow_period + 1.0)

        prev_fast = self.ema_fast[-1] if self.ema_fast else price
        prev_slow = self.ema_slow[-1] if self.ema_slow else price

        self.ema_fast.append((price * alpha_fast) + (prev_fast * (1.0 - alpha_fast)))
        self.ema_slow.append((price * alpha_slow) + (prev_slow * (1.0 - alpha_slow)))

    def _bollinger(self) -> tuple[float | None, float | None, float | None]:
        arr = list(self.prices)
        period = self.config.bb_period
        if len(arr) < period:
            return None, None, None

        sample = arr[-period:]
        center = sum(sample) / period
        std = pstdev(sample) if len(sample) > 1 else 0.0
        up = center + (self.config.bb_num_std * std)
        down = center - (self.config.bb_num_std * std)
        return up, center, down

    def _slope(self, series: deque[float], lookback: int) -> float | None:
        if len(series) < lookback:
            return None
        return float(series[-1] - series[-lookback])

    def evaluate(self, has_position: bool, selected_mode: str = "auto") -> dict:
        if len(self.ema_fast) < max(self.config.ema_slow_period, self.config.slope_lookback + 1):
            return {"signal": "none", "reason": "dados_insuficientes"}

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
        bb_upper, bb_mid, bb_lower = self._bollinger()

        if selected_mode == "auto":
            regime = detect_market_regime(atr=atr, ema21_slope=slope_ema21, price=price)
        elif selected_mode in {"tendencia", "lateral"}:
            regime = selected_mode
        else:
            regime = "auto"

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
            "bb_upper": bb_upper,
            "bb_mid": bb_mid,
            "bb_lower": bb_lower,
            "selected_mode": selected_mode,
            "active_mode": regime,
        }

        if regime == "tendencia":
            return self._evaluate_trend(has_position=has_position, base=base)
        if regime == "lateral":
            return self._evaluate_sideways(has_position=has_position, base=base)

        return {"signal": "none", "reason": "regime_indefinido", **base}

    def _evaluate_trend(self, has_position: bool, base: dict) -> dict:
        ema9 = float(base["ema9"])
        ema21 = float(base["ema21"])
        prev_ema9 = float(base["ema9_prev"])
        prev_ema21 = float(base["ema21_prev"])
        slope_ema9 = base["slope_ema9"]
        atr_gate = base["atr_gate"]
        dist = float(base["distancia_absoluta"])

        cross_up = prev_ema9 <= prev_ema21 and ema9 > ema21
        cross_down = prev_ema9 >= prev_ema21 and ema9 < ema21

        if not has_position:
            if not cross_up:
                return {"signal": "none", "reason": "sem_cruzamento_compra", **base}
            if slope_ema9 is None or slope_ema9 <= 0:
                return {"signal": "none", "reason": "slope_ema9_nao_positivo", **base}
            if atr_gate is None:
                return {"signal": "none", "reason": "atr_indisponivel", **base}
            if dist <= atr_gate:
                return {"signal": "none", "reason": "atr_insuficiente", **base}
            return {"signal": "buy", "reason": "compra_tendencia_ema9_ema21", **base}

        if cross_down:
            return {"signal": "sell", "reason": "cruzamento_baixa_ema9_ema21", **base}

        return {"signal": "none", "reason": "manter_posicao_tendencia", **base}

    def _evaluate_sideways(self, has_position: bool, base: dict) -> dict:
        price = float(base["price"])
        bb_upper = base["bb_upper"]
        bb_lower = base["bb_lower"]

        if bb_upper is None or bb_lower is None:
            return {"signal": "none", "reason": "bb_indisponivel", **base}

        if not has_position and price <= float(bb_lower):
            return {"signal": "buy", "reason": "toque_banda_inferior", **base}

        if has_position and price >= float(bb_upper):
            return {"signal": "sell", "reason": "toque_banda_superior", **base}

        return {"signal": "none", "reason": "manter_posicao_lateral", **base}
