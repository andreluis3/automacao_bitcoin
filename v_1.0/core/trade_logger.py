from __future__ import annotations

from datetime import datetime

from database.connection import TradeDatabase


class StructuredTradeLogger:
    def __init__(self, database: TradeDatabase):
        self.database = database

    def registrar_trade(
        self,
        tipo: str,
        preco: float,
        quantidade: float,
        lucro: float,
        saldo_apos_trade: float,
        motivo_entrada: str,
        regime_mercado: str,
        distancia_media_percentual: float,
        desvio_padrao_atual: float,
    ) -> None:
        self.database.inserir_trade_log(
            data_hora=datetime.utcnow().isoformat(timespec="seconds"),
            tipo=tipo,
            preco=float(preco),
            quantidade=float(quantidade),
            lucro=float(lucro),
            saldo_apos_trade=float(saldo_apos_trade),
            motivo_entrada=motivo_entrada,
            regime_mercado=regime_mercado,
            distancia_media_percentual=float(distancia_media_percentual),
            desvio_padrao_atual=float(desvio_padrao_atual),
        )
