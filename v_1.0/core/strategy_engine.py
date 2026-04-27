from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Optional


@dataclass
class StrategyConfig:
    ema_fast_period: int = 9
    ema_slow_period: int = 21
    atr_period: int = 14
    atr_min_factor: float = 0.2
    slope_lookback: int = 5
    bb_period: int = 20
    bb_num_std: float = 2.0
    # Thresholds de qualidade do sinal
    min_dist_pct: float = 0.0003      # distância mínima entre EMAs (0.03%)
    min_slope: float = 0.0            # slope mínimo da EMA rápida
    adx_period: int = 14              # período para cálculo do ADX


class AtrCalculator:
    """Calcula o Average True Range (ATR) incremental."""

    def __init__(self, period: int = 14):
        self.period = max(1, int(period))
        self._prev_close: Optional[float] = None
        self._trs: deque[float] = deque(maxlen=self.period)
        self._atr: Optional[float] = None

    def update(self, high: float, low: float, close: float) -> None:
        h, l, c = float(high), float(low), float(close)
        if self._prev_close is None:
            tr = h - l
        else:
            tr = max(h - l, abs(h - self._prev_close), abs(l - self._prev_close))
        self._trs.append(tr)
        self._prev_close = c

        if len(self._trs) == self.period:
            if self._atr is None:
                self._atr = sum(self._trs) / self.period
            else:
                self._atr = (self._atr * (self.period - 1) + tr) / self.period

    def value(self) -> Optional[float]:
        return self._atr


class StrategyEngine:
    def __init__(self, config: Optional[StrategyConfig] = None):
        self.config = config or StrategyConfig()
        self.prices: deque[float] = deque(maxlen=3000)
        self.highs: deque[float] = deque(maxlen=3000)
        self.lows: deque[float] = deque(maxlen=3000)
        self.volumes: deque[float] = deque(maxlen=3000)

        self.ema_fast: deque[float] = deque(maxlen=3000)
        self.ema_slow: deque[float] = deque(maxlen=3000)
        self.atr_calc = AtrCalculator(period=self.config.atr_period)

        # Para cálculo do ADX (detector de regime)
        self._adx_highs: deque[float] = deque(maxlen=self.config.adx_period * 3)
        self._adx_lows: deque[float] = deque(maxlen=self.config.adx_period * 3)
        self._adx_closes: deque[float] = deque(maxlen=self.config.adx_period * 3)

    def _required_periods(self) -> int:
        return max(self.config.ema_slow_period, self.config.slope_lookback + 1)

    def update_tick(
        self,
        price: float,
        high: Optional[float] = None,
        low: Optional[float] = None,
        volume: float = 0.0,
    ) -> None:
        p = float(price)
        if p <= 0:
            return

        h = float(high if high is not None else p)
        l = float(low if low is not None else p)

        self.prices.append(p)
        self.highs.append(h)
        self.lows.append(l)
        self.volumes.append(max(0.0, float(volume)))

        self._adx_highs.append(h)
        self._adx_lows.append(l)
        self._adx_closes.append(p)

        self._update_ema(p)
        self.atr_calc.update(h, l, p)

    def _update_ema(self, price: float) -> None:
        alpha_fast = 2.0 / (self.config.ema_fast_period + 1.0)
        alpha_slow = 2.0 / (self.config.ema_slow_period + 1.0)

        prev_fast = self.ema_fast[-1] if self.ema_fast else price
        prev_slow = self.ema_slow[-1] if self.ema_slow else price

        self.ema_fast.append((price * alpha_fast) + (prev_fast * (1.0 - alpha_fast)))
        self.ema_slow.append((price * alpha_slow) + (prev_slow * (1.0 - alpha_slow)))

    def _slope(self, series: deque, lookback: int) -> Optional[float]:
        if len(series) < lookback:
            return None
        return float(series[-1] - series[-lookback])

    def _calc_adx(self) -> Optional[float]:
        """Calcula ADX simplificado para detectar força da tendência."""
        period = self.config.adx_period
        highs = list(self._adx_highs)
        lows = list(self._adx_lows)
        closes = list(self._adx_closes)

        if len(closes) < period + 1:
            return None

        plus_dm_list = []
        minus_dm_list = []
        tr_list = []

        for i in range(1, len(closes)):
            h_diff = highs[i] - highs[i - 1]
            l_diff = lows[i - 1] - lows[i]

            plus_dm = h_diff if (h_diff > l_diff and h_diff > 0) else 0.0
            minus_dm = l_diff if (l_diff > h_diff and l_diff > 0) else 0.0

            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )

            plus_dm_list.append(plus_dm)
            minus_dm_list.append(minus_dm)
            tr_list.append(tr)

        if len(tr_list) < period:
            return None

        # Smoothed averages (últimos `period` valores)
        atr_s = sum(tr_list[-period:]) / period
        plus_di = (sum(plus_dm_list[-period:]) / period / atr_s * 100) if atr_s > 0 else 0.0
        minus_di = (sum(minus_dm_list[-period:]) / period / atr_s * 100) if atr_s > 0 else 0.0

        di_sum = plus_di + minus_di
        dx = (abs(plus_di - minus_di) / di_sum * 100) if di_sum > 0 else 0.0
        return dx

    def _detect_regime(self) -> str:
        """
        Detecta regime de mercado usando ADX.
        ADX > 25  → tendência forte
        ADX 20-25 → tendência fraca
        ADX < 20  → lateral (range)
        """
        adx = self._calc_adx()
        if adx is None:
            return "tendencia"  # sem dados suficientes → assume tendência (conservador)
        if adx >= 25:
            return "tendencia"
        if adx >= 20:
            return "tendencia_fraca"
        return "lateral"

    def evaluate(self, has_position: bool, selected_mode: str = "auto") -> dict:
        # 1️⃣ Verifica dados suficientes
        required_periods = self._required_periods()
        buffer_len = len(self.prices)

        if buffer_len < required_periods:
            price = float(self.prices[-1]) if self.prices else 0.0
            ema9 = float(self.ema_fast[-1]) if self.ema_fast else price
            ema21 = float(self.ema_slow[-1]) if self.ema_slow else price
            dist = abs(ema9 - ema21)
            dist_pct = (dist / ema21) if ema21 > 0 else 0.0

            return {
                "signal": "none",
                "reason": "dados_insuficientes",
                "price": price,
                "ema9": ema9,
                "ema21": ema21,
                "ema9_prev": ema9,
                "ema21_prev": ema21,
                "distancia_absoluta": dist,
                "distancia_percentual": dist_pct,
                "slope_ema9": 0.0,
                "slope_ema21": 0.0,
                "atr": None,
                "atr_gate": None,
                "buffer_len": buffer_len,
                "required_periods": required_periods,
                "warming_up": True,
                "active_mode": "aquecendo",
                "selected_mode": selected_mode,
            }

        # 2️⃣ Calcula indicadores
        price = float(self.prices[-1])
        ema9 = float(self.ema_fast[-1])
        ema21 = float(self.ema_slow[-1])

        prev_ema9 = float(self.ema_fast[-2]) if len(self.ema_fast) > 1 else ema9
        prev_ema21 = float(self.ema_slow[-2]) if len(self.ema_slow) > 1 else ema21

        slope_ema9 = self._slope(self.ema_fast, self.config.slope_lookback) or 0.0
        slope_ema21 = self._slope(self.ema_slow, self.config.slope_lookback) or 0.0

        atr = self.atr_calc.value()
        dist = abs(ema9 - ema21)
        dist_pct = (dist / ema21) if ema21 > 0 else 0.0
        atr_gate = (atr * self.config.atr_min_factor) if atr is not None else None

        # 3️⃣ Detecta regime
        if selected_mode == "auto":
            regime = self._detect_regime()
        elif selected_mode == "tendencia":
            regime = "tendencia"
        elif selected_mode == "lateral":
            regime = "lateral"
        else:
            regime = self._detect_regime()

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
            "buffer_len": buffer_len,
            "required_periods": required_periods,
            "warming_up": False,
        }

        # 4️⃣ Executa estratégia baseada no regime
        if regime == "lateral":
            # Em mercado lateral: se tem posição, avalia saída. Não abre novas.
            if has_position:
                return self._evaluate_exit_only(has_position=has_position, base=base)
            return {"signal": "none", "reason": "mercado_lateral_sem_operacao", **base}

        if regime in ("tendencia", "tendencia_fraca"):
            return self._evaluate_trend(has_position=has_position, base=base)

        return {"signal": "none", "reason": "regime_indefinido", **base}

    def _evaluate_trend(self, has_position: bool, base: dict) -> dict:
        """
        Estratégia de tendência com EMA crossover + confirmações.

        COMPRA quando:
          - EMA9 cruza acima da EMA21 (crossover de alta)
          - slope da EMA9 é positivo
          - distância entre EMAs é suficiente (filtra ruído)
          - ATR confirma volatilidade mínima

        VENDA quando:
          - EMA9 cruza abaixo da EMA21 (crossover de baixa)
          - ou slope negativo com posição aberta
        """
        ema9 = base["ema9"]
        ema21 = base["ema21"]
        prev_ema9 = base["ema9_prev"]
        prev_ema21 = base["ema21_prev"]
        slope_ema9 = base["slope_ema9"]
        dist_pct = base["distancia_percentual"]
        atr = base["atr"]
        atr_gate = base["atr_gate"]

        # --- Detecção de crossovers ---
        bullish_cross = (prev_ema9 <= prev_ema21) and (ema9 > ema21)
        bearish_cross = (prev_ema9 >= prev_ema21) and (ema9 < ema21)

        # --- Filtros de qualidade ---
        slope_ok = slope_ema9 > self.config.min_slope
        dist_ok = dist_pct >= self.config.min_dist_pct
        atr_ok = (atr_gate is None) or (dist_pct > 0 and (abs(ema9 - ema21) >= atr_gate))

        # --- Volume (se disponível) ---
        vol_ok = True
        if len(self.volumes) >= 20:
            avg_vol = sum(list(self.volumes)[-20:]) / 20
            current_vol = self.volumes[-1]
            vol_ok = current_vol >= avg_vol * 0.8  # volume não precisa explodir, mas não pode sumir

        # --- Lógica de saída (tem posição) ---
        if has_position:
            if bearish_cross:
                return {
                    "signal": "sell",
                    "reason": "crossover_baixa",
                    **base,
                }
            if slope_ema9 < -self.config.min_slope and ema9 < ema21:
                return {
                    "signal": "sell",
                    "reason": "slope_negativo_abaixo_ema21",
                    **base,
                }
            return {"signal": "none", "reason": "posicao_mantida", **base}

        # --- Lógica de entrada (sem posição) ---
        if not bullish_cross:
            motivo = "sem_crossover"
            if ema9 > ema21 and slope_ok and dist_ok:
                motivo = "tendencia_sem_cross_recente"
            return {"signal": "none", "reason": motivo, **base}

        # Verifica filtros um por um para log detalhado
        if not slope_ok:
            return {
                "signal": "none",
                "reason": f"slope_insuficiente ({slope_ema9:.4f})",
                **base,
            }
        if not dist_ok:
            return {
                "signal": "none",
                "reason": f"distancia_insuficiente ({dist_pct:.5f} < {self.config.min_dist_pct})",
                **base,
            }
        if not atr_ok:
            return {
                "signal": "none",
                "reason": "atr_gate_nao_atingido",
                **base,
            }
        if not vol_ok:
            return {
                "signal": "none",
                "reason": "volume_insuficiente",
                **base,
            }

        # ✅ Todos os filtros passaram → COMPRA
        return {
            "signal": "buy",
            "reason": "crossover_alta_confirmado",
            **base,
        }

    def _evaluate_exit_only(self, has_position: bool, base: dict) -> dict:
        """Em mercado lateral, apenas avalia saída se houver posição."""
        ema9 = base["ema9"]
        ema21 = base["ema21"]
        prev_ema9 = base["ema9_prev"]
        prev_ema21 = base["ema21_prev"]

        if has_position:
            bearish_cross = (prev_ema9 >= prev_ema21) and (ema9 < ema21)
            if bearish_cross:
                return {"signal": "sell", "reason": "crossover_baixa_lateral", **base}
            if ema9 < ema21 and base["slope_ema9"] < 0:
                return {"signal": "sell", "reason": "saida_mercado_lateral", **base}

        return {"signal": "none", "reason": "mercado_lateral_aguardando", **base}