from __future__ import annotations

from collections import deque


class AtrCalculator:
    """ATR incremental usando período fixo."""

    def __init__(self, period: int = 14):
        self.period = max(2, int(period))
        self._tr_values: deque[float] = deque(maxlen=self.period)
        self._last_close: float | None = None
        self.current_atr: float | None = None

    def update(self, high: float, low: float, close: float) -> float | None:
        h = float(high)
        l = float(low)
        c = float(close)
        if h <= 0 or l <= 0 or c <= 0:
            return self.current_atr

        if self._last_close is None:
            tr = max(0.0, h - l)
        else:
            tr = max(h - l, abs(h - self._last_close), abs(l - self._last_close))

        self._tr_values.append(tr)
        self._last_close = c

        if len(self._tr_values) < self.period:
            return None

        self.current_atr = sum(self._tr_values) / len(self._tr_values)
        return self.current_atr

    def value(self) -> float | None:
        return self.current_atr
