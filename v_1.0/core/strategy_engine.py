"""
strategy_engine.py — Arquitetura em 4 camadas com EMA38 como filtro macro.

CAMADA 1 — detectar_tendencia()
  slope EMA38 + dist EMA9/EMA21 → TENDENCIA_FORTE / TENDENCIA_FRACA / LATERAL

CAMADA 2 — Lógica por regime
  TENDÊNCIA: cascata EMA9 > EMA21 > EMA38
  LATERAL:   Bollinger (scalping) ou bloqueado

CAMADA 3 — deve_entrar()
  dist mínima + slope + ATR + volume + cascata

CAMADA 4 — signal_strength 0.0–1.0
  Position sizing inteligente

THROTTLE
  Avalia a cada N segundos. Com posição aberta: avalia sempre.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


class AtrCalculator:
    def __init__(self, period: int = 14):
        self.period = max(2, int(period))
        self._trs: deque[float] = deque(maxlen=self.period)
        self._prev_close: Optional[float] = None
        self._atr: Optional[float] = None

    def update(self, high: float, low: float, close: float) -> None:
        h, l, c = float(high), float(low), float(close)
        tr = (max(h - l, abs(h - self._prev_close), abs(l - self._prev_close))
              if self._prev_close is not None else h - l)
        self._trs.append(tr)
        self._prev_close = c
        if len(self._trs) >= self.period:
            self._atr = ((self._atr * (self.period - 1) + tr) / self.period
                         if self._atr is not None else sum(self._trs) / len(self._trs))

    def value(self) -> Optional[float]:
        return self._atr


@dataclass
class StrategyConfig:
    ema_fast_period: int   = 9
    ema_mid_period:  int   = 21
    ema_slow_period: int   = 38
    atr_period:      int   = 14
    bb_period:       int   = 20
    bb_num_std:      float = 2.0
    slope_lookback:  int   = 8
    min_dist_pct:    float = 0.0005   # 0.05% — filtra cruzamento de ruído
    atr_min_factor:  float = 0.3
    regime_slope_threshold: float = 0.000008  # slope EMA38 mínimo para tendência
    lateral_dist_threshold: float = 0.0003    # dist abaixo → colado → LATERAL
    eval_throttle_sec:      float = 5.0       # avalia a cada 5s no máximo
    aggressive_no_crossover: bool = False
    lateral_bb_entry:        bool = False
    lateral_bb_exit:         bool = False
    block_when_lateral:      bool = True


class StrategyEngine:
    def __init__(self, config: Optional[StrategyConfig] = None):
        self.config = config or StrategyConfig()
        self.prices:  deque[float] = deque(maxlen=5000)
        self.highs:   deque[float] = deque(maxlen=5000)
        self.lows:    deque[float] = deque(maxlen=5000)
        self.volumes: deque[float] = deque(maxlen=5000)
        self.ema_fast: deque[float] = deque(maxlen=5000)
        self.ema_mid:  deque[float] = deque(maxlen=5000)
        self.ema_slow: deque[float] = deque(maxlen=5000)
        self.atr_calc = AtrCalculator(period=self.config.atr_period)
        self._bb_upper: Optional[float] = None
        self._bb_lower: Optional[float] = None
        self._bb_mid:   Optional[float] = None
        self._last_eval_time:   Optional[datetime] = None
        self._last_eval_result: Optional[dict]     = None

    def _required_periods(self) -> int:
        return max(self.config.ema_slow_period, self.config.slope_lookback + 1, self.config.bb_period)

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
        self._update_emas(p)
        self.atr_calc.update(h, l, p)
        self._update_bollinger()

    def _update_emas(self, price: float) -> None:
        def _ema(series: deque, period: int) -> float:
            alpha = 2.0 / (period + 1.0)
            prev  = series[-1] if series else price
            return price * alpha + prev * (1.0 - alpha)
        self.ema_fast.append(_ema(self.ema_fast, self.config.ema_fast_period))
        self.ema_mid.append( _ema(self.ema_mid,  self.config.ema_mid_period))
        self.ema_slow.append(_ema(self.ema_slow, self.config.ema_slow_period))

    def _update_bollinger(self) -> None:
        n = self.config.bb_period
        if len(self.prices) < n:
            self._bb_upper = self._bb_lower = self._bb_mid = None
            return
        w   = list(self.prices)[-n:]
        mid = sum(w) / n
        std = (sum((x - mid) ** 2 for x in w) / n) ** 0.5
        self._bb_mid   = mid
        self._bb_upper = mid + self.config.bb_num_std * std
        self._bb_lower = mid - self.config.bb_num_std * std

    def _slope(self, series: deque, lookback: int) -> float:
        if len(series) < lookback:
            return 0.0
        return float(series[-1] - series[-lookback])

    # ── CAMADA 1 ──────────────────────────────────────────────────────────────
    def detectar_tendencia(self, price: float, e9: float, e21: float, e38: float) -> str:
        if price <= 0:
            return "lateral"
        s38       = self._slope(self.ema_slow, self.config.slope_lookback)
        slope_pct = abs(s38) / price
        dist_pct  = abs(e9 - e21) / e21 if e21 > 0 else 0.0
        if dist_pct < self.config.lateral_dist_threshold:
            return "lateral"
        if slope_pct < self.config.regime_slope_threshold:
            return "lateral"
        if (e9 > e21 > e38) or (e9 < e21 < e38):
            return "tendencia_forte"
        return "tendencia_fraca"

    # ── CAMADA 3 ──────────────────────────────────────────────────────────────
    def deve_entrar(self, e9: float, e21: float, e38: float,
                    slope9: float, dist_pct: float,
                    atr: Optional[float], atr_gate: Optional[float],
                    avg_vol: float, cur_vol: float,
                    modo_agressivo: bool = False,
                    bullish_cross: bool = False) -> tuple[bool, str]:
        dist    = abs(e9 - e21)
        dist_ok = dist_pct >= self.config.min_dist_pct
        slope_ok = slope9 > 0
        atr_ok   = (atr_gate is None) or (atr is None) or (dist >= atr_gate)
        vol_ok   = (avg_vol <= 0) or (cur_vol >= avg_vol * 0.8)
        cascade  = e9 > e21 > e38

        if not dist_ok:
            return False, f"dist_insuficiente ({dist_pct*100:.5f}% < {self.config.min_dist_pct*100:.3f}%)"
        if not slope_ok:
            return False, f"slope_negativo ({slope9:.4f})"
        if not atr_ok:
            return False, "atr_gate_nao_atingido"
        if not vol_ok:
            return False, "volume_insuficiente"
        if not cascade:
            return False, f"cascata_nao_alinhada (E9={e9:.0f} E21={e21:.0f} E38={e38:.0f})"
        if modo_agressivo:
            return True, "tendencia_cascata_agressiva"
        if bullish_cross:
            return True, "crossover_alta_cascata_confirmado"
        return False, "cascata_ok_aguardando_crossover"

    # ── CAMADA 4 ──────────────────────────────────────────────────────────────
    def _calc_signal_strength(self, result: dict, base: dict) -> float:
        if result.get("signal") == "none":
            return 0.0
        e9, e21, e38 = base["ema9"], base["ema21"], base["ema38"]
        s9, s38 = base["slope_ema9"], base["slope_ema38"]
        dist = base["distancia_percentual"]
        atr  = base["atr"] or 0.0
        price = base["price"] or 1.0
        checks = [e9 > e21 > e38, s9 > 0, s38 > 0,
                  dist >= self.config.min_dist_pct * 2, (atr / price) > 0.0001]
        return min(1.0, sum(checks) / len(checks) + min(0.2, dist * 100))

    # ── Evaluate principal ────────────────────────────────────────────────────
    def evaluate(self, has_position: bool, selected_mode: str = "auto") -> dict:
        required = self._required_periods()
        buf_len  = len(self.prices)

        if buf_len < required:
            price = float(self.prices[-1]) if self.prices else 0.0
            e9 = float(self.ema_fast[-1]) if self.ema_fast else price
            e21 = float(self.ema_mid[-1]) if self.ema_mid else price
            e38 = float(self.ema_slow[-1]) if self.ema_slow else price
            return {
                "signal": "none", "reason": "dados_insuficientes",
                "price": price, "ema9": e9, "ema21": e21, "ema38": e38,
                "ema9_prev": e9, "ema21_prev": e21,
                "distancia_percentual": 0.0, "distancia_absoluta": 0.0,
                "slope_ema9": 0.0, "slope_ema21": 0.0, "slope_ema38": 0.0,
                "atr": None, "atr_gate": None,
                "bb_upper": None, "bb_lower": None, "bb_mid": None,
                "volume": 0.0, "avg_volume": 0.0, "signal_strength": 0.0,
                "buffer_len": buf_len, "required_periods": required,
                "warming_up": True, "active_mode": "aquecendo",
                "selected_mode": selected_mode,
                "cascade_bull": False, "cascade_bear": False, "regime_slope_pct": 0.0,
            }

        now = datetime.utcnow()
        if (not has_position and self.config.eval_throttle_sec > 0
                and self._last_eval_time is not None and self._last_eval_result is not None
                and (now - self._last_eval_time).total_seconds() < self.config.eval_throttle_sec):
            return self._last_eval_result

        price  = float(self.prices[-1])
        e9     = float(self.ema_fast[-1])
        e21    = float(self.ema_mid[-1])
        e38    = float(self.ema_slow[-1])
        pe9    = float(self.ema_fast[-2]) if len(self.ema_fast) > 1 else e9
        pe21   = float(self.ema_mid[-2])  if len(self.ema_mid)  > 1 else e21
        s9     = self._slope(self.ema_fast, self.config.slope_lookback)
        s21    = self._slope(self.ema_mid,  self.config.slope_lookback)
        s38    = self._slope(self.ema_slow, self.config.slope_lookback)
        atr    = self.atr_calc.value()
        dist   = abs(e9 - e21)
        dist_pct = dist / e21 if e21 > 0 else 0.0
        atr_gate = (atr * self.config.atr_min_factor) if atr is not None else None
        avg_vol  = sum(list(self.volumes)[-20:]) / 20 if len(self.volumes) >= 20 else 0.0
        cur_vol  = float(self.volumes[-1]) if self.volumes else 0.0
        slope38_pct = abs(s38) / price if price > 0 else 0.0
        cascade_bull = e9 > e21 > e38
        cascade_bear = e9 < e21 < e38

        if selected_mode == "tendencia":
            regime = "tendencia_forte"
        elif selected_mode == "lateral":
            regime = "lateral"
        else:
            regime = self.detectar_tendencia(price, e9, e21, e38)

        base = {
            "price": price, "ema9": e9, "ema21": e21, "ema38": e38,
            "ema9_prev": pe9, "ema21_prev": pe21,
            "slope_ema9": s9, "slope_ema21": s21, "slope_ema38": s38,
            "atr": atr, "atr_gate": atr_gate,
            "distancia_absoluta": dist, "distancia_percentual": dist_pct,
            "bb_upper": self._bb_upper, "bb_lower": self._bb_lower, "bb_mid": self._bb_mid,
            "volume": cur_vol, "avg_volume": avg_vol,
            "selected_mode": selected_mode, "active_mode": regime,
            "buffer_len": buf_len, "required_periods": required,
            "warming_up": False, "signal_strength": 0.0,
            "cascade_bull": cascade_bull, "cascade_bear": cascade_bear,
            "regime_slope_pct": slope38_pct,
        }

        if regime in ("tendencia_forte", "tendencia_fraca"):
            result = self._evaluate_trend(has_position, base)
        elif self.config.block_when_lateral and not has_position:
            result = {"signal": "none", "reason": "mercado_lateral_bloqueado", **base}
        elif self.config.lateral_bb_entry:
            result = self._evaluate_lateral_scalping(has_position, base)
        elif has_position:
            result = self._evaluate_exit_only(has_position, base)
        else:
            result = {"signal": "none", "reason": "mercado_lateral_sem_operacao", **base}

        result["signal_strength"] = self._calc_signal_strength(result, base)
        self._last_eval_time   = now
        self._last_eval_result = result
        return result

    def _evaluate_trend(self, has_position: bool, base: dict) -> dict:
        e9, e21, e38 = base["ema9"], base["ema21"], base["ema38"]
        pe9, pe21    = base["ema9_prev"], base["ema21_prev"]
        s9           = base["slope_ema9"]
        bullish_cross = (pe9 <= pe21) and (e9 > e21)
        bearish_cross = (pe9 >= pe21) and (e9 < e21)

        if has_position:
            if bearish_cross:
                return {"signal": "sell", "reason": "crossover_baixa_ema9_ema21", **base}
            if base["cascade_bear"]:
                return {"signal": "sell", "reason": "cascata_baixa_ema9_ema21_ema38", **base}
            if s9 < 0 and e9 < e21 < e38:
                return {"signal": "sell", "reason": "slope_negativo_cascata_baixa", **base}
            return {"signal": "none", "reason": "posicao_mantida", **base}

        pode, motivo = self.deve_entrar(
            e9=e9, e21=e21, e38=e38,
            slope9=s9, dist_pct=base["distancia_percentual"],
            atr=base["atr"], atr_gate=base["atr_gate"],
            avg_vol=base["avg_volume"], cur_vol=base["volume"],
            modo_agressivo=self.config.aggressive_no_crossover,
            bullish_cross=bullish_cross,
        )
        return {"signal": "buy" if pode else "none", "reason": motivo, **base}

    def _evaluate_lateral_scalping(self, has_position: bool, base: dict) -> dict:
        price, bbu, bbl, bbm = base["price"], base["bb_upper"], base["bb_lower"], base["bb_mid"]
        if bbu is None or bbl is None or bbm is None:
            return {"signal": "none", "reason": "bollinger_sem_dados", **base}
        bw = bbu - bbl
        if bw <= 0:
            return {"signal": "none", "reason": "bollinger_banda_zero", **base}
        pos_rel = (price - bbl) / bw
        if has_position:
            if price >= bbu:
                return {"signal": "sell", "reason": f"lateral_banda_superior (pos={pos_rel:.2f})", **base}
            if price >= bbm:
                return {"signal": "sell", "reason": f"lateral_retorno_media (pos={pos_rel:.2f})", **base}
            return {"signal": "none", "reason": f"lateral_aguardando_saida (pos={pos_rel:.2f})", **base}
        if price <= bbl:
            return {"signal": "buy", "reason": f"lateral_banda_inferior (pos={pos_rel:.2f})", **base}
        return {"signal": "none", "reason": f"lateral_fora_entrada (pos={pos_rel:.2f})", **base}

    def _evaluate_exit_only(self, has_position: bool, base: dict) -> dict:
        if has_position:
            e9, e21, pe9, pe21 = base["ema9"], base["ema21"], base["ema9_prev"], base["ema21_prev"]
            if (pe9 >= pe21) and (e9 < e21):
                return {"signal": "sell", "reason": "crossover_baixa_exit_only", **base}
            if e9 < e21 and base["slope_ema9"] < 0:
                return {"signal": "sell", "reason": "slope_negativo_exit_only", **base}
        return {"signal": "none", "reason": "lateral_sem_sinal_saida", **base}

    # ── Setters públicos ──────────────────────────────────────────────────────
    def set_aggressive_mode(self, enabled: bool) -> None:
        self.config.aggressive_no_crossover = bool(enabled)

    def set_lateral_scalping(self, enabled: bool) -> None:
        self.config.lateral_bb_entry = bool(enabled)
        self.config.lateral_bb_exit  = bool(enabled)

    def set_block_lateral(self, enabled: bool) -> None:
        self.config.block_when_lateral = bool(enabled)

    def set_regime_threshold(self, threshold: float) -> None:
        self.config.regime_slope_threshold = max(0.0, float(threshold))

    def set_eval_throttle(self, seconds: float) -> None:
        self.config.eval_throttle_sec = max(0.0, float(seconds))

    def set_min_dist_pct(self, pct: float) -> None:
        self.config.min_dist_pct = max(0.0, float(pct))

    def get_debug_info(self) -> dict:
        price = float(self.prices[-1]) if self.prices else 0.0
        e9  = float(self.ema_fast[-1]) if self.ema_fast else 0.0
        e21 = float(self.ema_mid[-1])  if self.ema_mid  else 0.0
        e38 = float(self.ema_slow[-1]) if self.ema_slow else 0.0
        s38 = self._slope(self.ema_slow, self.config.slope_lookback)
        return {
            "buffer_len": len(self.prices),
            "ema9": e9, "ema21": e21, "ema38": e38,
            "slope9":  self._slope(self.ema_fast, self.config.slope_lookback),
            "slope21": self._slope(self.ema_mid,  self.config.slope_lookback),
            "slope38": s38,
            "dist_pct": abs(e9 - e21) / e21 if e21 > 0 else 0.0,
            "atr":      self.atr_calc.value(),
            "bb_upper": self._bb_upper, "bb_lower": self._bb_lower, "bb_mid": self._bb_mid,
            "regime":              self.detectar_tendencia(price, e9, e21, e38) if price > 0 else "N/A",
            "regime_slope_pct":    abs(s38) / price if price > 0 else 0.0,
            "cascade_bull":        e9 > e21 > e38 if e38 > 0 else False,
            "cascade_bear":        e9 < e21 < e38 if e38 > 0 else False,
            "regime_threshold":        self.config.regime_slope_threshold,
            "min_dist_pct":            self.config.min_dist_pct,
            "eval_throttle_sec":       self.config.eval_throttle_sec,
            "aggressive_no_crossover": self.config.aggressive_no_crossover,
            "lateral_scalping":        self.config.lateral_bb_entry,
            "block_when_lateral":      self.config.block_when_lateral,
        }