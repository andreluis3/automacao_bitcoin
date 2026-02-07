import sqlite3 

conn = sqlite3.connect('bitcoin_data.db')
cursor = conn.cursor()
cursor.execute('''
    CREATE DATABASE bitcoin_data; ''')

cursor.execute('''
CREATE TABLE trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    simbolo TEXT NOT NULL,
    tamanho REAL NOT NULL,
    entry_price REAL NOT NULL,
    exit_price REAL,
    quantidade REAL NOT NULL,
    hora_entrada TEXT NOT NULL,
    hora_saida TEXT,
    taxa REAL,
    caixa REAL,
    profit_percent REAL
);
''')
