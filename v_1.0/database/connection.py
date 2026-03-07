from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from database.init_db import DB_PATH, init_db


class DatabaseManager:
    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or DB_PATH
        init_db(self.db_path)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def start_session(self, saldo_inicio: float) -> int:
        now = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO bot_sessions (start_time, saldo_inicio, saldo_final, trades_executados) VALUES (?, ?, ?, ?)",
                (now, float(saldo_inicio), float(saldo_inicio), 0),
            )
            return int(cur.lastrowid)

    def end_session(self, session_id: int, saldo_final: float, trades_executados: int) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute(
                "UPDATE bot_sessions SET end_time = ?, saldo_final = ?, trades_executados = ? WHERE id = ?",
                (now, float(saldo_final), int(trades_executados), int(session_id)),
            )

    def insert_trade(
        self,
        simbolo: str,
        lado: str,
        entry_price: float,
        exit_price: float,
        quantidade: float,
        hora_entrada: str,
        hora_saida: str,
        taxa: float,
        lucro: float,
        profit_percent: float,
    ) -> int:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO trades (
                    simbolo, lado, entry_price, exit_price, quantidade,
                    hora_entrada, hora_saida, taxa, lucro, profit_percent
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    simbolo,
                    lado,
                    float(entry_price),
                    float(exit_price),
                    float(quantidade),
                    hora_entrada,
                    hora_saida,
                    float(taxa),
                    float(lucro),
                    float(profit_percent),
                ),
            )
            return int(cur.lastrowid)

    def add_fee(self, when_iso: str, valor: float) -> None:
        with self._connect() as conn:
            conn.execute("INSERT INTO fees (data, valor) VALUES (?, ?)", (when_iso, float(valor)))

    def upsert_daily_performance(self, day: str, lucro_delta: float, saldo_final: float, trade_delta: int = 1) -> None:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT lucro_dia, total_trades FROM daily_performance WHERE data = ?", (day,))
            row = cur.fetchone()
            if row:
                lucro, total = float(row[0] or 0.0), int(row[1] or 0)
                cur.execute(
                    "UPDATE daily_performance SET lucro_dia = ?, saldo_final = ?, total_trades = ? WHERE data = ?",
                    (lucro + float(lucro_delta), float(saldo_final), total + int(trade_delta), day),
                )
            else:
                cur.execute(
                    "INSERT INTO daily_performance (data, lucro_dia, saldo_final, total_trades) VALUES (?, ?, ?, ?)",
                    (day, float(lucro_delta), float(saldo_final), int(trade_delta)),
                )

    def get_total_fees(self) -> float:
        with self._connect() as conn:
            row = conn.execute("SELECT COALESCE(SUM(valor), 0) FROM fees").fetchone()
            return float((row or [0])[0] or 0.0)

    def fetch_one(self, query: str, params: tuple[Any, ...] = ()) -> Any:
        with self._connect() as conn:
            row = conn.execute(query, params).fetchone()
            if not row:
                return 0
            return row[0]

    def monthly_profit(self, year_month: str) -> float:
        return float(
            self.fetch_one(
                "SELECT COALESCE(SUM(lucro_dia), 0) FROM daily_performance WHERE strftime('%Y-%m', data) = ?",
                (year_month,),
            )
        )

    def trades_count(self) -> int:
        return int(self.fetch_one("SELECT COUNT(*) FROM trades"))

    def sessions_count(self) -> int:
        return int(self.fetch_one("SELECT COUNT(*) FROM bot_sessions"))

    def best_day(self) -> float:
        return float(self.fetch_one("SELECT COALESCE(MAX(lucro_dia), 0) FROM daily_performance"))

    def worst_day(self) -> float:
        return float(self.fetch_one("SELECT COALESCE(MIN(lucro_dia), 0) FROM daily_performance"))
