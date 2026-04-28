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
        self._ensure_trade_logs_table()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ─── Garante tabela trade_logs existe ────────────────────────────────────
    def _ensure_trade_logs_table(self) -> None:
        """
        Cria a tabela trade_logs se não existir.
        Permite usar StructuredTradeLogger sem alterar init_db.py.
        """
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trade_logs (
                    id                         INTEGER PRIMARY KEY AUTOINCREMENT,
                    data_hora                  TEXT    NOT NULL,
                    tipo                       TEXT    NOT NULL,
                    preco                      REAL    NOT NULL DEFAULT 0,
                    quantidade                 REAL    NOT NULL DEFAULT 0,
                    lucro                      REAL    NOT NULL DEFAULT 0,
                    saldo_apos_trade           REAL    NOT NULL DEFAULT 0,
                    motivo_entrada             TEXT    NOT NULL DEFAULT '',
                    regime_mercado             TEXT    NOT NULL DEFAULT '',
                    distancia_media_percentual REAL    NOT NULL DEFAULT 0,
                    desvio_padrao_atual        REAL    NOT NULL DEFAULT 0
                )
            """)

    # ─── Sessões ──────────────────────────────────────────────────────────────
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

    # ─── Trades ───────────────────────────────────────────────────────────────
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
                    simbolo, lado,
                    float(entry_price), float(exit_price), float(quantidade),
                    hora_entrada, hora_saida,
                    float(taxa), float(lucro), float(profit_percent),
                ),
            )
            return int(cur.lastrowid)

    # ─── Trade logs estruturados (StructuredTradeLogger) ─────────────────────
    def inserir_trade_log(
        self,
        data_hora: str,
        tipo: str,
        preco: float,
        quantidade: float,
        lucro: float,
        saldo_apos_trade: float,
        motivo_entrada: str,
        regime_mercado: str,
        distancia_media_percentual: float,
        desvio_padrao_atual: float,
    ) -> int:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO trade_logs (
                    data_hora, tipo, preco, quantidade, lucro,
                    saldo_apos_trade, motivo_entrada, regime_mercado,
                    distancia_media_percentual, desvio_padrao_atual
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data_hora, tipo,
                    float(preco), float(quantidade), float(lucro),
                    float(saldo_apos_trade), motivo_entrada, regime_mercado,
                    float(distancia_media_percentual), float(desvio_padrao_atual),
                ),
            )
            return int(cur.lastrowid)

    def listar_trade_logs(self, limit: int = 200) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM trade_logs ORDER BY id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
            return [dict(r) for r in rows]

    # ─── Taxas ────────────────────────────────────────────────────────────────
    def add_fee(self, when_iso: str, valor: float) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO fees (data, valor) VALUES (?, ?)",
                (when_iso, float(valor)),
            )

    # ─── Performance diária ───────────────────────────────────────────────────
    def upsert_daily_performance(
        self, day: str, lucro_delta: float, saldo_final: float, trade_delta: int = 1
    ) -> None:
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT lucro_dia, total_trades FROM daily_performance WHERE data = ?",
                (day,),
            )
            row = cur.fetchone()
            if row:
                lucro = float(row["lucro_dia"] or 0.0)
                total = int(row["total_trades"] or 0)
                cur.execute(
                    "UPDATE daily_performance SET lucro_dia = ?, saldo_final = ?, total_trades = ? WHERE data = ?",
                    (lucro + float(lucro_delta), float(saldo_final), total + int(trade_delta), day),
                )
            else:
                cur.execute(
                    "INSERT INTO daily_performance (data, lucro_dia, saldo_final, total_trades) VALUES (?, ?, ?, ?)",
                    (day, float(lucro_delta), float(saldo_final), int(trade_delta)),
                )

    # ─── Consultas de resumo ──────────────────────────────────────────────────
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


# ─── StructuredTradeLogger ────────────────────────────────────────────────────

class StructuredTradeLogger:
    """
    Logger estruturado de trades. Usa DatabaseManager como backend.

    Uso:
        db  = DatabaseManager()
        log = StructuredTradeLogger(db)
        log.registrar_trade(
            tipo="BUY",
            preco=383000.0,
            quantidade=0.00078,
            lucro=0.0,
            saldo_apos_trade=300.0,
            motivo_entrada="crossover_alta_confirmado",
            regime_mercado="tendencia",
            distancia_media_percentual=0.0003,
            desvio_padrao_atual=45.2,
        )
    """

    def __init__(self, database: DatabaseManager):
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

    def listar(self, limit: int = 200) -> list[dict]:
        """Retorna os últimos N registros de trade_logs."""
        return self.database.listar_trade_logs(limit=limit)