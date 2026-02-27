from __future__ import annotations


class EquityManager:
    def __init__(self):
        self.saldo_inicial_sessao = 0.0
        self.peak_equity = 0.0
        self.peak_lucro = 0.0

    def reset(self, saldo_inicial: float) -> None:
        self.saldo_inicial_sessao = float(saldo_inicial)
        self.peak_equity = float(saldo_inicial)
        self.peak_lucro = 0.0

    def update(self, equity: float) -> dict[str, float]:
        equity = float(equity)
        if equity > self.peak_equity:
            self.peak_equity = equity

        lucro_atual = equity - self.saldo_inicial_sessao
        if lucro_atual > self.peak_lucro:
            self.peak_lucro = lucro_atual

        drawdown_pct = ((self.peak_equity - equity) / self.peak_equity) * 100 if self.peak_equity > 0 else 0.0
        lucro_dia_pct = (lucro_atual / self.saldo_inicial_sessao) * 100 if self.saldo_inicial_sessao > 0 else 0.0

        if self.peak_lucro > 0:
            lucro_drop_pct = ((self.peak_lucro - lucro_atual) / self.peak_lucro) * 100
        else:
            lucro_drop_pct = 0.0

        return {
            "drawdown_pct": drawdown_pct,
            "lucro_dia_pct": lucro_dia_pct,
            "lucro_drop_pct": max(0.0, lucro_drop_pct),
            "lucro_atual": lucro_atual,
        }
