"""
数据库模块 - SQLite存储历史数据
"""
import sqlite3
import os
from datetime import datetime

DB_PATH = "/opt/ai-monitor/data/monitor.db"

def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()

    # 股价历史
    c.execute("""
        CREATE TABLE IF NOT EXISTS stock_daily (
            code TEXT,
            date TEXT,
            open REAL, high REAL, low REAL, close REAL,
            volume REAL, amount REAL,
            PRIMARY KEY (code, date)
        )
    """)

    # 库存数据
    c.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            commodity TEXT,
            date TEXT,
            stockpile REAL,
            change REAL,
            source TEXT,
            PRIMARY KEY (commodity, date)
        )
    """)

    # 信号记录
    c.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            type TEXT,
            source TEXT,
            title TEXT,
            detail TEXT,
            severity TEXT,
            sent INTEGER DEFAULT 0
        )
    """)

    # 新闻/公告
    c.execute("""
        CREATE TABLE IF NOT EXISTS news (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            source TEXT,
            title TEXT,
            url TEXT,
            keywords TEXT,
            relevance TEXT,
            processed INTEGER DEFAULT 0
        )
    """)

    conn.commit()
    conn.close()

def insert_stock(code, date, open_, high, low, close, volume, amount):
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO stock_daily VALUES (?,?,?,?,?,?,?,?)",
        (code, date, open_, high, low, close, volume, amount)
    )
    conn.commit()
    conn.close()

def insert_inventory(commodity, date, stockpile, change, source):
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO inventory VALUES (?,?,?,?,?)",
        (commodity, date, stockpile, change, source)
    )
    conn.commit()
    conn.close()

def insert_signal(type_, source, title, detail, severity):
    conn = get_conn()
    conn.execute(
        "INSERT INTO signals (timestamp, type, source, title, detail, severity) VALUES (?,?,?,?,?,?)",
        (datetime.now().isoformat(), type_, source, title, detail, severity)
    )
    conn.commit()
    conn.close()

def get_unsent_signals():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM signals WHERE sent=0 ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def mark_signal_sent(signal_id):
    conn = get_conn()
    conn.execute("UPDATE signals SET sent=1 WHERE id=?", (signal_id,))
    conn.commit()
    conn.close()

def get_stock_history(code, days=60):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM stock_daily WHERE code=? ORDER BY date DESC LIMIT ?",
        (code, days)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_inventory_history(commodity, weeks=10):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM inventory WHERE commodity=? ORDER BY date DESC LIMIT ?",
        (commodity, weeks)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

if __name__ == "__main__":
    init_db()
    print("Database initialized at", DB_PATH)
