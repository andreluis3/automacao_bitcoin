from __future__ import annotations

from datetime import datetime
from typing import Any


class SaldoManager:
    """
    Gerencia persistência de saldo diário e histórico de performance.
    Desacoplado do banco: aceita qualquer objeto com os métodos necessários.
    """

    def __init__(self, database: Any):
        self.database = database

    def carregar_saldo_acumulado(self) -> float | None:
        """Retorna o último saldo final registrado, ou None se não houver."""
        try:
            row = self.database.buscar_ultimo_saldo_diario()
        except Exception:
            return None
        if not row:
            return None
        valor = row.get("saldo_final")
        if valor is None:
            return None
        try:
            return float(valor)
        except (TypeError, ValueError):
            return None

    def salvar_saldo_diario(
        self,
        saldo_inicial: float,
        saldo_final: float,
        drawdown_dia: float,
        total_trades: int,
        win_rate: float,
        data_ref: str | None = None,
    ) -> None:
        """Persiste o resumo diário de performance."""
        data = data_ref or datetime.utcnow().date().isoformat()
        si = float(saldo_inicial)
        sf = float(saldo_final)
        lucro_dia = sf - si
        percentual_dia = (lucro_dia / si) * 100 if si > 0 else 0.0

        try:
            self.database.inserir_saldo_historico(
                data=data,
                saldo_inicial=si,
                saldo_final=sf,
                lucro_dia=lucro_dia,
                percentual_dia=percentual_dia,
                drawdown_dia=float(drawdown_dia),
                total_trades=int(total_trades),
                win_rate=float(win_rate),
            )
        except Exception as exc:
            print(f"[SaldoManager] Erro ao salvar saldo diário: {exc}")

    def listar_saldos(self) -> list[dict]:
        """Retorna histórico completo de saldos diários."""
        try:
            return self.database.listar_saldo_historico() or []
        except Exception:
            return []

    def calcular_resumo(self) -> dict:
        """Calcula métricas de resumo a partir do histórico."""
        saldos = self.listar_saldos()
        if not saldos:
            return {
                "total_dias": 0,
                "lucro_total": 0.0,
                "melhor_dia": 0.0,
                "pior_dia": 0.0,
                "win_rate_medio": 0.0,
            }

        lucros = [float(s.get("lucro_dia", 0.0)) for s in saldos]
        win_rates = [float(s.get("win_rate", 0.0)) for s in saldos]

        return {
            "total_dias": len(saldos),
            "lucro_total": sum(lucros),
            "melhor_dia": max(lucros) if lucros else 0.0,
            "pior_dia": min(lucros) if lucros else 0.0,
            "win_rate_medio": sum(win_rates) / len(win_rates) if win_rates else 0.0,
        }