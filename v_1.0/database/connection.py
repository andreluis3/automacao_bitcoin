import sqlite3
import os

DB_PATH = "data/trades.db"

os.makedirs("data", exist_ok=True)

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# HISTÓRICO DE TRADES
cursor.execute("""
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    simbolo TEXT,
    lado TEXT,
    tamanho REAL,
    entry_price REAL,
    exit_price REAL,
    quantidade REAL,
    hora_entrada TEXT,
    hora_saida TEXT,
    taxa REAL,
    lucro REAL,
    profit_percent REAL
)
""")

# PERFORMANCE DIÁRIA
cursor.execute("""
CREATE TABLE IF NOT EXISTS daily_performance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    data TEXT UNIQUE,
    lucro_dia REAL,
    saldo_final REAL,
    total_trades INTEGER
)
""")

# SESSÕES DO BOT
cursor.execute("""
CREATE TABLE IF NOT EXISTS bot_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_time TEXT,
    end_time TEXT,
    saldo_inicio REAL,
    saldo_final REAL,
    trades_executados INTEGER
)
""")

# TAXAS PAGAS
cursor.execute("""
CREATE TABLE IF NOT EXISTS fees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    data TEXT,
    valor REAL
)
""")

conn.commit()
conn.close()

print("Banco de dados inicializado.")