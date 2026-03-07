from __future__ import annotations

import sqlite3
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
DB_PATH = ROOT_DIR / "data" / "trades.db"


def init_db(db_path: Path | None = None) -> Path:
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path)
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            simbolo TEXT NOT NULL,
            lado TEXT NOT NULL,
            entry_price REAL,
            exit_price REAL,
            quantidade REAL NOT NULL,
            hora_entrada TEXT NOT NULL,
            hora_saida TEXT,
            taxa REAL DEFAULT 0,
            lucro REAL DEFAULT 0,
            profit_percent REAL DEFAULT 0
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS daily_performance (
            data TEXT PRIMARY KEY,
            lucro_dia REAL DEFAULT 0,
            saldo_final REAL DEFAULT 0,
            total_trades INTEGER DEFAULT 0
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS bot_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            start_time TEXT NOT NULL,
            end_time TEXT,
            saldo_inicio REAL DEFAULT 0,
            saldo_final REAL DEFAULT 0,
            trades_executados INTEGER DEFAULT 0
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS fees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data TEXT NOT NULL,
            valor REAL NOT NULL
        )
        """
    )

    conn.commit()
    conn.close()
    return path


if __name__ == "__main__":
    created = init_db()
    print(f"Banco inicializado em: {created}")
