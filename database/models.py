from dataclasses import dataclass
from datetime import datetime

@dataclass
class Trade:
    simbolo: str
    tamanho: float
    entry_price: float
    exit_price: float | None
    quantidade: float
    hora_entrada: datetime
    hora_saida: datetime | None
    taxa: float
    caixa: float
    profit_percent: float
