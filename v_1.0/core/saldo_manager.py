from __future__ import annotations

from datetime import datetime

from database.database import TradeDatabase


class SaldoManager:
    def __init__(self, database: TradeDatabase):
        self.database = database

    def carregar_saldo_acumulado(self) -> float | None:
        row = self.database.buscar_ultimo_saldo_diario()
        if not row:
            return None
        return float(row.get("saldo_final") or 0.0)

    def salvar_saldo_diario(
        self,
        saldo_inicial: float,
        saldo_final: float,
        drawdown_dia: float,
        total_trades: int,
        win_rate: float,
        data_ref: str | None = None,
    ) -> None:
        data = data_ref or datetime.utcnow().date().isoformat()
        lucro_dia = float(saldo_final) - float(saldo_inicial)
        percentual_dia = (lucro_dia / float(saldo_inicial)) * 100 if saldo_inicial > 0 else 0.0

        self.database.inserir_saldo_historico(
            data=data,
            saldo_inicial=float(saldo_inicial),
            saldo_final=float(saldo_final),
            lucro_dia=lucro_dia,
            percentual_dia=percentual_dia,
            drawdown_dia=float(drawdown_dia),
            total_trades=int(total_trades),
            win_rate=float(win_rate),
        )

    def listar_saldos(self) -> list[dict]:
        return self.database.listar_saldo_historico()
