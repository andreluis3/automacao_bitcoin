"""
strategy_engine.py — Motor de estratégia corrigido.

Problemas resolvidos vs versão anterior:
1. ADX baseado em ticks de 1-2s sempre detectava lateral → detector novo
   baseado em slope da EMA21 normalizado pelo preço (calibrado para BTC/BRL).
2. Modo agressivo: entra se EMA9 > EMA21 sem exigir crossover.
3. Modo lateral: scalping por reversão à média (Bollinger Bands).
4. Thresholds calibrados para ticks de 1-2 segundos em BTC/BRL (~R$383.000).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Optional


class AtrCalculator:
    def __init__(self, period: int = 14):
        self.period = max(2, int(period))
        self._trs: deque[float] = deque(maxlen=self.period)
        self._prev_close: Optional[float] = None
        self._atr: Optional[float] = None

    def update(self, high: float, low: float, close: float) -> None:
        h, l, c = float(high), float(low), float(close)
        if self._prev_close is None:
            tr = h - l
        else:
            tr = max(h - l, abs(h - self._prev_close), abs(l - self._prev_close))
        self._trs.append(tr)
        self._prev_close = c
        if len(self._trs) >= self.period:
            if self._atr is None:
                self._atr = sum(self._trs) / len(self._trs)
            else:
                self._atr = (self._atr * (self.period - 1) + tr) / self.period

    def value(self) -> Optional[float]:
        return self._atr


@dataclass
class StrategyConfig:
    ema_fast_period: int   = 9
    ema_slow_period: int   = 21
    atr_period: int        = 14
    atr_min_factor: float  = 0.2
    slope_lookback: int    = 5
    bb_period: int         = 20
    bb_num_std: float      = 2.0

    # Distância mínima entre EMAs — 0.0001 = 0.01% = R$38 em R$383.000
    min_dist_pct: float = 0.0001

    # Slope mínimo da EMA9 (valor absoluto em R$); 0 = aceita qualquer positivo
    min_slope: float = 0.0

    # Detector de regime: slope normalizado da EMA21
    # 0.000005 = calibrado para ticks de 1-2s em BTC/BRL
    # Menor = detecta tendência mais fácil | Maior = fica lateral mais tempo
    regime_slope_threshold: float = 0.000005

    # Modo agressivo: entra se EMA9 > EMA21 sem exigir crossover
    aggressive_no_crossover: bool = False

    # Modo lateral: scalping por Bollinger Bands
    lateral_bb_entry: bool = True
    lateral_bb_exit:  bool = True


class StrategyEngine:
    def __init__(self, config: Optional[StrategyConfig] = None):
        self.config = config or StrategyConfig()

        self.prices:  deque[float] = deque(maxlen=3000)
        self.highs:   deque[float] = deque(maxlen=3000)
        self.lows:    deque[float] = deque(maxlen=3000)
        self.volumes: deque[float] = deque(maxlen=3000)

        self.ema_fast: deque[float] = deque(maxlen=3000)
        self.ema_slow: deque[float] = deque(maxlen=3000)
        self.atr_calc = AtrCalculator(period=self.config.atr_period)

        self._bb_upper: Optional[float] = None
        self._bb_lower: Optional[float] = None
        self._bb_mid:   Optional[float] = None

    def _required_periods(self) -> int:
        return max(self.config.ema_slow_period, self.config.slope_lookback + 1)

    def update_tick(self, price: float, high: Optional[float] = None,
                    low: Optional[float] = None, volume: float = 0.0) -> None:
        p = float(price)
        if p <= 0:
            return
        h = float(high if high is not None else p)
        l = float(low  if low  is not None else p)

        self.prices.append(p)
        self.highs.append(h)
        self.lows.append(l)
        self.volumes.append(max(0.0, float(volume)))

        self._update_ema(p)
        self.atr_calc.update(h, l, p)
        self._update_bollinger()

    def _update_ema(self, price: float) -> None:
        af  = 2.0 / (self.config.ema_fast_period + 1.0)
        as_ = 2.0 / (self.config.ema_slow_period + 1.0)
        pf  = self.ema_fast[-1] if self.ema_fast else price
        ps  = self.ema_slow[-1] if self.ema_slow else price
        self.ema_fast.append(price * af  + pf * (1.0 - af))
        self.ema_slow.append(price * as_ + ps * (1.0 - as_))

    def _update_bollinger(self) -> None:
        n = self.config.bb_period
        if len(self.prices) < n:
            self._bb_upper = self._bb_lower = self._bb_mid = None
            return
        window = list(self.prices)[-n:]
        mid = sum(window) / n
        std = (sum((x - mid) ** 2 for x in window) / n) ** 0.5
        self._bb_mid   = mid
        self._bb_upper = mid + self.config.bb_num_std * std
        self._bb_lower = mid - self.config.bb_num_std * std

    def _slope(self, series: deque, lookback: int) -> float:
        if len(series) < lookback:
            return 0.0
        return float(series[-1] - series[-lookback])

    def _detect_regime(self, price: float) -> str:
        """
        Detecta regime pelo slope normalizado da EMA21.

        Para BTC/BRL ≈ R$383.000 em ticks de 1-2s:
          slope de R$2/tick → pct ≈ 0.0000052 → TENDÊNCIA (limiar padrão 0.000005)
          slope de R$1/tick → pct ≈ 0.0000026 → LATERAL

        Ajuste via set_regime_threshold() ou config.regime_slope_threshold.
        """
        if price <= 0:
            return "lateral"
        slope21 = self._slope(self.ema_slow, self.config.slope_lookback)
        slope_pct = abs(slope21) / price
        if slope_pct >= self.config.regime_slope_threshold:
            return "tendencia"
        return "lateral"

    # ── Avaliação principal ──────────────────────────────────────────────────
    def evaluate(self, has_position: bool, selected_mode: str = "auto") -> dict:
        required = self._required_periods()
        buf_len  = len(self.prices)

        if buf_len < required:
            price = float(self.prices[-1]) if self.prices else 0.0
            ema9  = float(self.ema_fast[-1]) if self.ema_fast else price
            ema21 = float(self.ema_slow[-1]) if self.ema_slow else price
            dist  = abs(ema9 - ema21)
            return {
                "signal": "none", "reason": "dados_insuficientes",
                "price": price, "ema9": ema9, "ema21": ema21,
                "ema9_prev": ema9, "ema21_prev": ema21,
                "distancia_absoluta": dist,
                "distancia_percentual": dist / ema21 if ema21 > 0 else 0.0,
                "slope_ema9": 0.0, "slope_ema21": 0.0,
                "atr": None, "atr_gate": None,
                "bb_upper": None, "bb_lower": None, "bb_mid": None,
                "volume": 0.0, "avg_volume": 0.0,
                "buffer_len": buf_len, "required_periods": required,
                "warming_up": True, "active_mode": "aquecendo",
                "selected_mode": selected_mode,
            }

        price    = float(self.prices[-1])
        ema9     = float(self.ema_fast[-1])
        ema21    = float(self.ema_slow[-1])
        prev_e9  = float(self.ema_fast[-2]) if len(self.ema_fast) > 1 else ema9
        prev_e21 = float(self.ema_slow[-2]) if len(self.ema_slow) > 1 else ema21
        slope9   = self._slope(self.ema_fast, self.config.slope_lookback)
        slope21  = self._slope(self.ema_slow,  self.config.slope_lookback)
        atr      = self.atr_calc.value()
        dist     = abs(ema9 - ema21)
        dist_pct = dist / ema21 if ema21 > 0 else 0.0
        atr_gate = (atr * self.config.atr_min_factor) if atr is not None else None

        avg_vol = 0.0
        if len(self.volumes) >= 20:
            avg_vol = sum(list(self.volumes)[-20:]) / 20
        cur_vol = float(self.volumes[-1]) if self.volumes else 0.0

        if selected_mode == "tendencia":
            regime = "tendencia"
        elif selected_mode == "lateral":
            regime = "lateral"
        else:
            regime = self._detect_regime(price)

        base = {
            "price": price, "ema9": ema9, "ema21": ema21,
            "ema9_prev": prev_e9, "ema21_prev": prev_e21,
            "slope_ema9": slope9, "slope_ema21": slope21,
            "atr": atr, "atr_gate": atr_gate,
            "distancia_absoluta": dist, "distancia_percentual": dist_pct,
            "bb_upper": self._bb_upper, "bb_lower": self._bb_lower, "bb_mid": self._bb_mid,
            "volume": cur_vol, "avg_volume": avg_vol,
            "selected_mode": selected_mode, "active_mode": regime,
            "buffer_len": buf_len, "required_periods": required, "warming_up": False,
        }

        if regime == "tendencia":
            return self._evaluate_trend(has_position, base)
        else:
            if self.config.lateral_bb_entry:
                return self._evaluate_lateral_scalping(has_position, base)
            if has_position:
                return self._evaluate_exit_only(has_position, base)
            return {"signal": "none", "reason": "mercado_lateral_sem_operacao", **base}

    # ── Tendência ────────────────────────────────────────────────────────────
    def _evaluate_trend(self, has_position: bool, base: dict) -> dict:
        ema9     = base["ema9"]
        ema21    = base["ema21"]
        prev_e9  = base["ema9_prev"]
        prev_e21 = base["ema21_prev"]
        slope9   = base["slope_ema9"]
        dist_pct = base["distancia_percentual"]
        atr      = base["atr"]
        atr_gate = base["atr_gate"]
        dist     = base["distancia_absoluta"]
        avg_vol  = base["avg_volume"]
        cur_vol  = base["volume"]

        bullish_cross = (prev_e9 <= prev_e21) and (ema9 > ema21)
        bearish_cross = (prev_e9 >= prev_e21) and (ema9 < ema21)

        slope_ok = slope9 >= self.config.min_slope
        dist_ok  = dist_pct >= self.config.min_dist_pct
        atr_ok   = (atr_gate is None) or (atr is None) or (dist >= atr_gate)
        vol_ok   = (avg_vol <= 0) or (cur_vol >= avg_vol * 0.8)

        # Saída
        if has_position:
            if bearish_cross:
                return {"signal": "sell", "reason": "crossover_baixa", **base}
            if slope9 < -abs(self.config.min_slope) and ema9 < ema21:
                return {"signal": "sell", "reason": "slope_negativo_abaixo_ema21", **base}
            return {"signal": "none", "reason": "posicao_mantida", **base}

        # Modo agressivo: sem crossover
        if self.config.aggressive_no_crossover:
            if ema9 > ema21 and slope_ok and dist_ok:
                return {"signal": "buy", "reason": "tendencia_agressiva_sem_crossover", **base}
            reason = "ema9_abaixo_ema21" if ema9 <= ema21 else \
                     f"slope_negativo ({slope9:.4f})" if not slope_ok else \
                     f"dist_insuficiente ({dist_pct*100:.5f}%)"
            return {"signal": "none", "reason": reason, **base}

        # Entrada padrão: exige crossover
        if not bullish_cross:
            reason = "sem_crossover"
            if ema9 > ema21:
                reason = "tendencia_ativa_sem_cross_recente"
            return {"signal": "none", "reason": reason, **base}

        if not slope_ok:
            return {"signal": "none", "reason": f"slope_insuficiente ({slope9:.4f})", **base}
        if not dist_ok:
            return {"signal": "none", "reason": f"distancia_insuficiente ({dist_pct*100:.5f}%)", **base}
        if not atr_ok:
            return {"signal": "none", "reason": "atr_gate_nao_atingido", **base}
        if not vol_ok:
            return {"signal": "none", "reason": f"volume_insuficiente", **base}

        return {"signal": "buy", "reason": "crossover_alta_confirmado", **base}

    # ── Lateral: scalping Bollinger ──────────────────────────────────────────
    def _evaluate_lateral_scalping(self, has_position: bool, base: dict) -> dict:
        """
        Compra na banda inferior, vende na banda superior ou na média.
        Ideal para mercado oscilante sem direção clara.
        """
        price    = base["price"]
        bb_upper = base["bb_upper"]
        bb_lower = base["bb_lower"]
        bb_mid   = base["bb_mid"]

        if bb_upper is None or bb_lower is None or bb_mid is None:
            return {"signal": "none", "reason": "bollinger_sem_dados", **base}

        band_width = bb_upper - bb_lower
        if band_width <= 0:
            return {"signal": "none", "reason": "bollinger_banda_zero", **base}

        pos_rel = (price - bb_lower) / band_width  # 0 = lower, 1 = upper

        if has_position:
            if price >= bb_upper:
                return {"signal": "sell", "reason": f"lateral_banda_superior (pos={pos_rel:.2f})", **base}
            if price >= bb_mid:
                return {"signal": "sell", "reason": f"lateral_retorno_media (pos={pos_rel:.2f})", **base}
            return {"signal": "none", "reason": f"lateral_aguardando_saida (pos={pos_rel:.2f})", **base}

        if price <= bb_lower:
            return {"signal": "buy", "reason": f"lateral_banda_inferior (pos={pos_rel:.2f})", **base}

        return {"signal": "none", "reason": f"lateral_fora_entrada (pos={pos_rel:.2f})", **base}

    # ── Somente saída ────────────────────────────────────────────────────────
    def _evaluate_exit_only(self, has_position: bool, base: dict) -> dict:
        ema9    = base["ema9"]
        ema21   = base["ema21"]
        prev_e9 = base["ema9_prev"]
        prev_e21= base["ema21_prev"]
        if has_position:
            if (prev_e9 >= prev_e21) and (ema9 < ema21):
                return {"signal": "sell", "reason": "crossover_baixa_lateral", **base}
            if ema9 < ema21 and base["slope_ema9"] < 0:
                return {"signal": "sell", "reason": "saida_mercado_lateral", **base}
        return {"signal": "none", "reason": "mercado_lateral_aguardando", **base}

    # ── Helpers públicos ─────────────────────────────────────────────────────
    def set_aggressive_mode(self, enabled: bool) -> None:
        self.config.aggressive_no_crossover = bool(enabled)

    def set_lateral_scalping(self, enabled: bool) -> None:
        self.config.lateral_bb_entry = bool(enabled)
        self.config.lateral_bb_exit  = bool(enabled)

    def set_regime_threshold(self, threshold: float) -> None:
        """
        Ajusta sensibilidade do detector de regime.
        Valores úteis para ticks 1-2s BTC/BRL:
          0.000002 → muito sensível (quase sempre tendência)
          0.000005 → padrão
          0.00001  → conservador (fica lateral na maioria do tempo)
        """
        self.config.regime_slope_threshold = max(0.0, float(threshold))

    def get_debug_info(self) -> dict:
        price = float(self.prices[-1]) if self.prices else 0.0
        return {
            "buffer_len": len(self.prices),
            "ema9":  float(self.ema_fast[-1]) if self.ema_fast else 0.0,
            "ema21": float(self.ema_slow[-1]) if self.ema_slow else 0.0,
            "slope9":  self._slope(self.ema_fast, self.config.slope_lookback),
            "slope21": self._slope(self.ema_slow,  self.config.slope_lookback),
            "atr":     self.atr_calc.value(),
            "bb_upper": self._bb_upper,
            "bb_lower": self._bb_lower,
            "bb_mid":   self._bb_mid,
            "regime":   self._detect_regime(price) if price > 0 else "N/A",
            "regime_threshold": self.config.regime_slope_threshold,
            "aggressive_no_crossover": self.config.aggressive_no_crossover,
            "lateral_scalping": self.config.lateral_bb_entry,
        }