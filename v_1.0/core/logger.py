from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class SessionEvent:
    timestamp: datetime
    event_type: str
    payload: dict[str, Any]


class ProfessionalLogger:
    def __init__(self, logs_dir: str | Path):
        self.logs_dir = Path(logs_dir)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.session_start = datetime.now()
        self.events: list[SessionEvent] = []

    def reset_session(self) -> None:
        self.session_start = datetime.now()
        self.events.clear()

    def add_event(self, event_type: str, payload: dict[str, Any]) -> None:
        self.events.append(SessionEvent(timestamp=datetime.now(), event_type=event_type, payload=dict(payload)))

    def export_report(self, mode_label: str, strategy_label: str, stats: dict[str, Any]) -> Path:
        now = datetime.now()
        path = self.logs_dir / f"relatorio_simulacao_{now.strftime('%Y%m%d_%H%M')}.txt"

        lines: list[str] = []
        lines.append("SIMULACAO AUTOMACAO BTC")
        lines.append("")
        lines.append(f"Inicio: {self.session_start.strftime('%H:%M')}")
        lines.append(f"Modo: {mode_label}")
        lines.append(f"Estrategia: {strategy_label}")
        lines.append("")

        for event in self.events:
            ts = event.timestamp.strftime("%H:%M")
            payload = event.payload
            lines.append(ts)
            if event.event_type == "tick":
                lines.append(f"Preco BTC: {float(payload.get('price', 0.0)):.2f}")
                lines.append(f"EMA9: {float(payload.get('ema9', 0.0)):.2f}")
                lines.append(f"EMA21: {float(payload.get('ema21', 0.0)):.2f}")
                lines.append(f"Sinal: {str(payload.get('signal', 'NONE')).upper()}")
            elif event.event_type == "trade":
                lines.append(f"Preco BTC: {float(payload.get('price', 0.0)):.2f}")
                lines.append(f"Sinal: {str(payload.get('side', 'NONE')).upper()}")
                if "pnl_pct" in payload:
                    lines.append(f"Lucro: {float(payload['pnl_pct']):+.2f}%")
            lines.append("")

        lines.append("RESUMO")
        lines.append(f"Total trades: {int(stats.get('total_trades', 0))}")
        lines.append(f"Win rate: {float(stats.get('win_rate', 0.0)) * 100:.2f}%")
        lines.append(f"Lucro total: {float(stats.get('lucro_total_brl', 0.0)):+.2f} BRL")
        lines.append(f"Drawdown maximo: {float(stats.get('drawdown_max_pct', 0.0)):.2f}%")

        path.write_text("\n".join(lines), encoding="utf-8")
        return path
