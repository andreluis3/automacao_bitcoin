from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GlobalRiskConfig:
    stop_diario_pct: float = 3.0
    stop_drawdown_acumulado_pct: float = 15.0
    trailing_equity_drop_pct: float = 30.0


class GlobalRiskManager:
    def __init__(self, config: GlobalRiskConfig | None = None):
        self.config = config or GlobalRiskConfig()

    def ajustar_por_modo(self, modo: str) -> None:
        key = modo.strip().lower()
        if key == "conservador":
            self.config = GlobalRiskConfig(stop_diario_pct=2.0, stop_drawdown_acumulado_pct=10.0, trailing_equity_drop_pct=20.0)
        elif key == "agressivo":
            self.config = GlobalRiskConfig(stop_diario_pct=4.0, stop_drawdown_acumulado_pct=20.0, trailing_equity_drop_pct=35.0)
        else:
            self.config = GlobalRiskConfig(stop_diario_pct=3.0, stop_drawdown_acumulado_pct=15.0, trailing_equity_drop_pct=30.0)

    def deve_pausar(self, lucro_dia_pct: float, drawdown_acumulado_pct: float, lucro_protegido_pct: float) -> tuple[bool, str]:
        if lucro_dia_pct <= -self.config.stop_diario_pct:
            return True, "stop_diario"
        if drawdown_acumulado_pct >= self.config.stop_drawdown_acumulado_pct:
            return True, "stop_drawdown_acumulado"
        if lucro_protegido_pct >= self.config.trailing_equity_drop_pct:
            return True, "protecao_lucro"
        return False, ""
