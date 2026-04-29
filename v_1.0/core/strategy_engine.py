"""
strategy_engine.py — Arquitetura em 4 camadas com EMA38 como filtro macro.

CAMADA 1 — Detector de regime
  Usa slope da EMA38 + distância EMA9/EMA21 para classificar:
    TENDENCIA_FORTE → opera normalmente
    TENDENCIA_FRACA → opera com filtros mais rígidos
    LATERAL         → bloqueia entrada, ou usa scalping Bollinger

CAMADA 2 — Lógica diferente por modo
  TENDÊNCIA: confirmação em cascata EMA9 > EMA21 > EMA38
  LATERAL:   Bollinger Bands (compra fundo, vende topo)

CAMADA 3 — Filtros de qualidade
  distância mínima EMA9/EMA21, slope consistente, ATR gate

CAMADA 4 — Sinal de força (para position sizing no engine)
  Retorna signal_strength 0.0–1.0 baseado em quantas camadas confirmam

AVALIAÇÃO A CADA N SEGUNDOS (throttle)
  Evita overtrading em ticks de 1-2s. Padrão: avalia a cada 5s no máximo.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


# ─── ATR Calculator ──────────────────────────────────────────────────────────
class AtrCalculator:
    def __init__(self, period: int = 14):
        self.period = max(2, int(period))
        self._trs: deque[float] = deque(maxlen=self.period)
        self._prev_close: Optional[float] = None
        self._atr: Optional[float] = None

    def update(self, high: float, low: float, close: float) -> None:
        h, l, c = float(high), float(low), float(close)
        tr = max(h - l, abs(h - self._prev_close), abs(l - self._prev_close)) \
             if self._prev_close is not None else (h - l)
        self._trs.append(tr)
        self._prev_close = c
        if len(self._trs) >= self.period:
            self._atr = ((self._atr * (self.period - 1) + tr) / self.period) \
                        if self._atr is not None else sum(self._trs) / len(self._trs)

    def value(self) -> Optional[float]:
        return self._atr


# ─── Configuração ─────────────────────────────────────────────────────────────
@dataclass
class StrategyConfig:
    # ── Períodos das EMAs ──────────────────────────────────────────────────
    ema_fast_period:  int = 9    # EMA rápida — sinal de entrada
    ema_mid_period:   int = 21   # EMA intermediária — confirmação
    ema_slow_period:  int = 38   # EMA lenta (NOVA) — filtro macro de tendência
    atr_period:       int = 14
    bb_period:        int = 20
    bb_num_std:       float = 2.0

    # ── Lookback para cálculo de slope ────────────────────────────────────
    slope_lookback: int = 8  # aumentado de 5 → 8 para slope mais estável

    # ── Distância mínima EMA9/EMA21 (CAMADA 3) ───────────────────────────
    # 0.0005 = 0.05% de R$379.000 ≈ R$190 — filtra cruzamentos de ruído
    min_dist_pct: float = 0.0005

    # ── ATR gate ──────────────────────────────────────────────────────────
    atr_min_factor: float = 0.3

    # ── Detector de regime (CAMADA 1) ────────────────────────────────────
    # Slope da EMA38 normalizado pelo preço
    # 0.000008 = R$3/tick em R$379.000 → tendência real
    regime_slope_threshold: float = 0.000008

    # Distância EMA9/EMA21 abaixo deste valor → mercado "colado" → LATERAL
    lateral_dist_threshold: float = 0.0003   # 0.03%

    # ── Throttle: mínimo de segundos entre avaliações ─────────────────────
    # Evita overtrading em ticks de 1-2s. 0 = sem throttle.
    eval_throttle_sec: float = 5.0

    # ── Modos ─────────────────────────────────────────────────────────────
    # Modo agressivo: entra sem exigir crossover, só EMA9 > EMA21 > EMA38
    aggressive_no_crossover: bool = False

    # Modo lateral: scalping por Bollinger Bands
    lateral_bb_entry: bool = True
    lateral_bb_exit:  bool = True

    # Bloquear operação quando lateral (sem scalping)
    block_when_lateral: bool = False


# ─── Engine ───────────────────────────────────────────────────────────────────
class StrategyEngine:
    def __init__(self, config: Optional[StrategyConfig] = None):
        self.config = config or StrategyConfig()

        self.prices:  deque[float] = deque(maxlen=5000)
        self.highs:   deque[float] = deque(maxlen=5000)
        self.lows:    deque[float] = deque(maxlen=5000)
        self.volumes: deque[float] = deque(maxlen=5000)

        self.ema_fast: deque[float] = deque(maxlen=5000)  # EMA9
        self.ema_mid:  deque[float] = deque(maxlen=5000)  # EMA21
        self.ema_slow: deque[float] = deque(maxlen=5000)  # EMA38 (NOVO)

        self.atr_calc = AtrCalculator(period=self.config.atr_period)

        # Bollinger
        self._bb_upper: Optional[float] = None
        self._bb_lower: Optional[float] = None
        self._bb_mid:   Optional[float] = None

        # Throttle de avaliação
        self._last_eval_time: Optional[datetime] = None
        self._last_eval_result: Optional[dict] = None

    # ─── Required periods ────────────────────────────────────────────────────
    def _required_periods(self) -> int:
        return max(
            self.config.ema_slow_period,
            self.config.slope_lookback + 1,
            self.config.bb_period,
        )

    # ─── Update tick ─────────────────────────────────────────────────────────
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

    # ─── CAMADA 1: Detector de regime ────────────────────────────────────────
    def _detect_regime(
        self, price: float, ema9: float, ema21: float, ema38: float
    ) -> str:
        """
        TENDENCIA_FORTE  → EMA9 > EMA21 > EMA38, slope38 alto, dist9_21 > threshold
        TENDENCIA_FRACA  → alinhamento parcial
        LATERAL          → EMAs coladas, slope baixo
        """
        if price <= 0:
            return "lateral"

        slope38  = self._slope(self.ema_slow, self.config.slope_lookback)
        slope_pct = abs(slope38) / price
        dist9_21 = abs(ema9 - ema21) / ema21 if ema21 > 0 else 0.0

        # EMA colada → lateral imediato
        if dist9_21 < self.config.lateral_dist_threshold:
            return "lateral"

        # Slope da EMA38 forte → tendência
        if slope_pct >= self.config.regime_slope_threshold:
            # Verificar alinhamento cascata
            if (ema9 > ema21 > ema38) or (ema9 < ema21 < ema38):
                return "tendencia_forte"
            return "tendencia_fraca"

        return "lateral"

    # ─── Evaluate principal ───────────────────────────────────────────────────
    def evaluate(self, has_position: bool, selected_mode: str = "auto") -> dict:
        required = self._required_periods()
        buf_len  = len(self.prices)

        # Aquecimento
        if buf_len < required:
            price = float(self.prices[-1]) if self.prices else 0.0
            e9    = float(self.ema_fast[-1]) if self.ema_fast else price
            e21   = float(self.ema_mid[-1])  if self.ema_mid  else price
            e38   = float(self.ema_slow[-1]) if self.ema_slow else price
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
            }

        # ── Throttle ─────────────────────────────────────────────────────────
        # Só reavalia se passou tempo suficiente OU se tem posição aberta
        # (posição aberta: avalia sempre para não perder stop/saída)
        now = datetime.utcnow()
        throttle = self.config.eval_throttle_sec
        if (
            not has_position
            and throttle > 0
            and self._last_eval_time is not None
            and self._last_eval_result is not None
        ):
            elapsed = (now - self._last_eval_time).total_seconds()
            if elapsed < throttle:
                return self._last_eval_result

        # ── Indicadores ───────────────────────────────────────────────────────
        price  = float(self.prices[-1])
        e9     = float(self.ema_fast[-1])
        e21    = float(self.ema_mid[-1])
        e38    = float(self.ema_slow[-1])
        pe9    = float(self.ema_fast[-2]) if len(self.ema_fast) > 1 else e9
        pe21   = float(self.ema_mid[-2])  if len(self.ema_mid)  > 1 else e21

        s9  = self._slope(self.ema_fast, self.config.slope_lookback)
        s21 = self._slope(self.ema_mid,  self.config.slope_lookback)
        s38 = self._slope(self.ema_slow, self.config.slope_lookback)

        atr      = self.atr_calc.value()
        dist     = abs(e9 - e21)
        dist_pct = dist / e21 if e21 > 0 else 0.0
        atr_gate = (atr * self.config.atr_min_factor) if atr is not None else None

        avg_vol = (sum(list(self.volumes)[-20:]) / 20) if len(self.volumes) >= 20 else 0.0
        cur_vol = float(self.volumes[-1]) if self.volumes else 0.0

        # ── CAMADA 1: Regime ─────────────────────────────────────────────────
        if selected_mode == "tendencia":
            regime = "tendencia_forte"
        elif selected_mode == "lateral":
            regime = "lateral"
        else:
            regime = self._detect_regime(price, e9, e21, e38)

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
        }

        # ── CAMADA 2: Roteamento ──────────────────────────────────────────────
        if regime in ("tendencia_forte", "tendencia_fraca"):
            result = self._evaluate_trend(has_position, base, regime)
        elif self.config.block_when_lateral and not has_position:
            result = {"signal": "none", "reason": "mercado_lateral_bloqueado", **base}
        elif self.config.lateral_bb_entry:
            result = self._evaluate_lateral_scalping(has_position, base)
        elif has_position:
            result = self._evaluate_exit_only(has_position, base)
        else:
            result = {"signal": "none", "reason": "mercado_lateral_sem_operacao", **base}

        # ── CAMADA 4: Força do sinal ──────────────────────────────────────────
        result["signal_strength"] = self._calc_signal_strength(result, base)

        self._last_eval_time   = now
        self._last_eval_result = result
        return result

    # ─── CAMADA 2A: Tendência — confirmação em cascata ────────────────────────
    def _evaluate_trend(self, has_position: bool, base: dict, regime: str) -> dict:
        """
        CAMADA 3 — Filtros de qualidade:
          1. Cascata: EMA9 > EMA21 > EMA38  (ou inverso para baixa)
          2. Distância EMA9/EMA21 > min_dist_pct
          3. Slope EMA9 positivo e consistente
          4. ATR gate
          5. Volume mínimo

        ENTRADA (sem posição):
          Padrão:    exige crossover EMA9/EMA21
          Agressivo: aceita EMA9 > EMA21 sem crossover recente
        """
        e9   = base["ema9"]
        e21  = base["ema21"]
        e38  = base["ema38"]
        pe9  = base["ema9_prev"]
        pe21 = base["ema21_prev"]
        s9   = base["slope_ema9"]
        dist_pct = base["distancia_percentual"]
        dist     = base["distancia_absoluta"]
        atr      = base["atr"]
        atr_gate = base["atr_gate"]
        avg_vol  = base["avg_volume"]
        cur_vol  = base["volume"]

        bullish_cross = (pe9 <= pe21) and (e9 > e21)
        bearish_cross = (pe9 >= pe21) and (e9 < e21)

        # ── Filtros de qualidade (CAMADA 3) ───────────────────────────────
        dist_ok  = dist_pct >= self.config.min_dist_pct
        slope_ok = s9 > 0
        atr_ok   = (atr_gate is None) or (atr is None) or (dist >= atr_gate)
        vol_ok   = (avg_vol <= 0) or (cur_vol >= avg_vol * 0.8)

        # Cascata: EMA9 > EMA21 > EMA38 (alta) ou EMA9 < EMA21 < EMA38 (baixa)
        cascade_bull = (e9 > e21) and (e21 > e38)
        cascade_bear = (e9 < e21) and (e21 < e38)

        # ── SAÍDA (posição aberta) ─────────────────────────────────────────
        if has_position:
            if bearish_cross:
                return {"signal": "sell", "reason": "crossover_baixa_ema9_ema21", **base}
            if cascade_bear:
                return {"signal": "sell", "reason": "cascata_baixa_ema9_ema21_ema38", **base}
            if s9 < 0 and e9 < e21 and e21 < e38:
                return {"signal": "sell", "reason": "slope_negativo_cascata_baixa", **base}
            return {"signal": "none", "reason": "posicao_mantida", **base}

        # ── ENTRADA (sem posição) ─────────────────────────────────────────
        # Filtros básicos primeiro
        if not dist_ok:
            return {
                "signal": "none",
                "reason": f"dist_insuficiente ({dist_pct*100:.5f}% < {self.config.min_dist_pct*100:.3f}%)",
                **base,
            }
        if not slope_ok:
            return {"signal": "none", "reason": f"slope_negativo ({s9:.4f})", **base}
        if not atr_ok:
            return {"signal": "none", "reason": "atr_gate_nao_atingido", **base}
        if not vol_ok:
            return {"signal": "none", "reason": "volume_insuficiente", **base}

        # Verificar cascata (ESSENCIAL — filtra ruído macro)
        if not cascade_bull:
            return {
                "signal": "none",
                "reason": f"cascata_nao_alinhada (E9={e9:.0f} E21={e21:.0f} E38={e38:.0f})",
                **base,
            }

        # Modo agressivo: aceita EMA9 > EMA21 sem crossover
        if self.config.aggressive_no_crossover:
            return {"signal": "buy", "reason": "tendencia_cascata_agressiva", **base}

        # Modo padrão: exige crossover
        if bullish_cross:
            return {"signal": "buy", "reason": "crossover_alta_cascata_confirmado", **base}

        return {"signal": "none", "reason": "cascata_ok_aguardando_crossover", **base}

    # ─── CAMADA 2B: Lateral — scalping Bollinger ──────────────────────────────
    def _evaluate_lateral_scalping(self, has_position: bool, base: dict) -> dict:
        """
        Compra na banda inferior, vende na banda superior ou na média.
        NÃO usa EMA cruzamento — usa reversão à média.
        """
        price    = base["price"]
        bb_upper = base["bb_upper"]
        bb_lower = base["bb_lower"]
        bb_mid   = base["bb_mid"]

        if bb_upper is None or bb_lower is None or bb_mid is None:
            return {"signal": "none", "reason": "bollinger_sem_dados", **base}

        bw = bb_upper - bb_lower
        if bw <= 0:
            return {"signal": "none", "reason": "bollinger_banda_zero", **base}

        pos_rel = (price - bb_lower) / bw  # 0 = fundo, 1 = topo

        if has_position:
            if price >= bb_upper:
                return {"signal": "sell", "reason": f"lateral_banda_superior (pos={pos_rel:.2f})", **base}
            if price >= bb_mid:
                return {"signal": "sell", "reason": f"lateral_retorno_media (pos={pos_rel:.2f})", **base}
            return {"signal": "none", "reason": f"lateral_aguardando_saida (pos={pos_rel:.2f})", **base}

        if price <= bb_lower:
            return {"signal": "buy", "reason": f"lateral_banda_inferior (pos={pos_rel:.2f})", **base}

        return {"signal": "none", "reason": f"lateral_fora_entrada (pos={pos_rel:.2f})", **base}

    # ─── Somente saída ────────────────────────────────────────────────────────
    def _evaluate_exit_only(self, has_position: bool, base: dict) -> dict:
        if has_position:
            e9, e21 = base["ema9"], base["ema21"]
            pe9, pe21 = base["ema9_prev"], base["ema21_prev"]
            if (pe9 >= pe21) and (e9 < e21):
                return {"signal": "sell", "reason": "crossover_baixa_exit_only", **base}
            if e9 < e21 and base["slope_ema9"] < 0:
                return {"signal": "sell", "reason": "slope_negativo_exit_only", **base}
        return {"signal": "none", "reason": "lateral_sem_sinal_saida", **base}

    # ─── CAMADA 4: Força do sinal ─────────────────────────────────────────────
    def _calc_signal_strength(self, result: dict, base: dict) -> float:
        """
        Retorna 0.0–1.0 baseado em quantas camadas confirmam.
        Usado pelo TradingEngine para position sizing inteligente.

        Forte (0.7–1.0): cascata alinhada + dist alta + slope forte + ATR ok
        Médio (0.4–0.7): a maioria confirmada
        Fraco (0.0–0.4): apenas 1-2 confirmações
        """
        if result.get("signal") == "none":
            return 0.0

        e9   = base["ema9"]
        e21  = base["ema21"]
        e38  = base["ema38"]
        s9   = base["slope_ema9"]
        s38  = base["slope_ema38"]
        dist = base["distancia_percentual"]
        atr  = base["atr"] or 0.0
        price= base["price"] or 1.0

        checks = [
            e9 > e21 > e38,                              # cascata alta
            s9 > 0,                                       # slope9 positivo
            s38 > 0,                                      # slope38 positivo (macro)
            dist >= self.config.min_dist_pct * 2,         # dist dobrada = mais forte
            (atr / price) > 0.0001,                       # volatilidade real
        ]
        score = sum(checks) / len(checks)

        # Bonus por distância percentual
        dist_bonus = min(0.2, dist * 100)
        return min(1.0, score + dist_bonus)

    # ─── Helpers públicos ─────────────────────────────────────────────────────
    def set_aggressive_mode(self, enabled: bool) -> None:
        """Liga modo agressivo (entra sem crossover se cascata alinhada)."""
        self.config.aggressive_no_crossover = bool(enabled)

    def set_lateral_scalping(self, enabled: bool) -> None:
        """Liga scalping por Bollinger em mercado lateral."""
        self.config.lateral_bb_entry = bool(enabled)
        self.config.lateral_bb_exit  = bool(enabled)

    def set_block_lateral(self, enabled: bool) -> None:
        """Se True, não opera em lateral (ignora scalping)."""
        self.config.block_when_lateral = bool(enabled)

    def set_regime_threshold(self, threshold: float) -> None:
        """Sensibilidade do detector. Menor = detecta tendência mais fácil."""
        self.config.regime_slope_threshold = max(0.0, float(threshold))

    def set_eval_throttle(self, seconds: float) -> None:
        """Intervalo mínimo entre avaliações (evita overtrading em ticks)."""
        self.config.eval_throttle_sec = max(0.0, float(seconds))

    def set_min_dist_pct(self, pct: float) -> None:
        """Distância mínima EMA9/EMA21 para aceitar sinal."""
        self.config.min_dist_pct = max(0.0, float(pct))

    def get_debug_info(self) -> dict:
        """Snapshot completo para debug e relatórios."""
        price = float(self.prices[-1]) if self.prices else 0.0
        e9    = float(self.ema_fast[-1]) if self.ema_fast else 0.0
        e21   = float(self.ema_mid[-1])  if self.ema_mid  else 0.0
        e38   = float(self.ema_slow[-1]) if self.ema_slow else 0.0
        return {
            "buffer_len":   len(self.prices),
            "ema9":         e9,
            "ema21":        e21,
            "ema38":        e38,
            "slope9":       self._slope(self.ema_fast, self.config.slope_lookback),
            "slope21":      self._slope(self.ema_mid,  self.config.slope_lookback),
            "slope38":      self._slope(self.ema_slow, self.config.slope_lookback),
            "dist_pct":     abs(e9 - e21) / e21 if e21 > 0 else 0.0,
            "atr":          self.atr_calc.value(),
            "bb_upper":     self._bb_upper,
            "bb_lower":     self._bb_lower,
            "bb_mid":       self._bb_mid,
            "regime":       self._detect_regime(price, e9, e21, e38) if price > 0 else "N/A",
            "regime_threshold":        self.config.regime_slope_threshold,
            "min_dist_pct":            self.config.min_dist_pct,
            "eval_throttle_sec":       self.config.eval_throttle_sec,
            "aggressive_no_crossover": self.config.aggressive_no_crossover,
            "lateral_scalping":        self.config.lateral_bb_entry,
            "block_when_lateral":      self.config.block_when_lateral,
            "cascade_bull":            (e9 > e21 > e38) if e38 > 0 else False,
            "cascade_bear":            (e9 < e21 < e38) if e38 > 0 else False,
        }