from __future__ import annotations

from datetime import datetime

from database.connection import DatabaseManager


def get_performance_cards(db: DatabaseManager) -> dict[str, float | int]:
    year_month = datetime.now().strftime("%Y-%m")
    return {
        "lucro_mes": db.monthly_profit(year_month),
        "trades_executados": db.trades_count(),
        "sessoes": db.sessions_count(),
        "melhor_dia": db.best_day(),
        "pior_dia": db.worst_day(),
    }
