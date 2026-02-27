from __future__ import annotations

from dataclasses import dataclass
from statistics import pstdev


@dataclass
class RegimeResult:
    regime: str
    alerta: str
    valido: bool
    distancia_media_percentual: float
    desvio_padrao_atual: float
    em_exaustao: bool


class RegimeDetector:
    def __init__(self, distancia_min_percent: float = 1.0):
        self.distancia_min_percent = distancia_min_percent

    def detectar(
        self,
        preco: float,
        sma_rapida: float | None,
        sma_intermediaria: float | None,
        sma_lenta: float | None,
        closes: list[float],
    ) -> RegimeResult:
        if not sma_rapida or not sma_intermediaria or not sma_lenta:
            return RegimeResult(
                regime="LATERAL",
                alerta="",
                valido=False,
                distancia_media_percentual=0.0,
                desvio_padrao_atual=0.0,
                em_exaustao=False,
            )

        distancia = abs((sma_rapida - sma_intermediaria) / sma_intermediaria) * 100 if sma_intermediaria else 0.0
        janela = closes[-30:] if len(closes) >= 30 else closes
        desvio = pstdev(janela) if len(janela) > 1 else 0.0
        media = (sum(janela) / len(janela)) if janela else 0.0
        zscore = abs((preco - media) / desvio) if desvio > 0 else 0.0
        em_exaustao = zscore > 2.5

        alta = sma_rapida > sma_intermediaria and distancia > self.distancia_min_percent and preco > sma_lenta
        baixa = sma_rapida < sma_intermediaria and distancia > self.distancia_min_percent and preco < sma_lenta

        if alta and not em_exaustao:
            return RegimeResult(
                regime="ALTA",
                alerta="⚠ TENDENCIA DE BTC ALTA",
                valido=True,
                distancia_media_percentual=distancia,
                desvio_padrao_atual=desvio,
                em_exaustao=False,
            )

        if baixa and not em_exaustao:
            return RegimeResult(
                regime="BAIXA",
                alerta="⚠ TENDENCIA DE BTC BAIXA",
                valido=True,
                distancia_media_percentual=distancia,
                desvio_padrao_atual=desvio,
                em_exaustao=False,
            )

        return RegimeResult(
            regime="LATERAL",
            alerta="",
            valido=False,
            distancia_media_percentual=distancia,
            desvio_padrao_atual=desvio,
            em_exaustao=em_exaustao,
        )
