"""
数据库模块 - SQLite存储历史数据
包含: 股价、库存、信号、新闻、上游数据、海外标的、AI分析、北向资金
"""
import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "monitor.db")

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
            category TEXT DEFAULT 'general',
            title TEXT,
            content TEXT,
            url TEXT,
            keywords TEXT,
            relevance TEXT,
            ai_direction TEXT,
            ai_confidence TEXT,
            ai_reason TEXT,
            affected_sectors TEXT,
            processed INTEGER DEFAULT 0
        )
    """)

    # 上游产业数据 (TSMC营收、LME库存、DRAM价格等)
    c.execute("""
        CREATE TABLE IF NOT EXISTS upstream_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT,
            date TEXT,
            metric TEXT,
            value REAL,
            unit TEXT,
            yoy_change REAL,
            mom_change REAL,
            raw_json TEXT,
            UNIQUE(source, date, metric)
        )
    """)

    # 海外标的日线 (NVDA/TSM/AVGO/MU/SMCI/ASML)
    c.execute("""
        CREATE TABLE IF NOT EXISTS overseas_daily (
            symbol TEXT,
            date TEXT,
            open REAL, high REAL, low REAL, close REAL,
            volume REAL,
            change_pct REAL,
            after_hours_price REAL,
            after_hours_change_pct REAL,
            PRIMARY KEY (symbol, date)
        )
    """)

    # AI分析结果
    c.execute("""
        CREATE TABLE IF NOT EXISTS ai_analysis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            target TEXT,
            analysis_type TEXT,
            direction TEXT,
            confidence TEXT,
            catalyst TEXT,
            risk TEXT,
            action TEXT,
            key_metrics TEXT,
            supporting_dimensions TEXT,
            raw_response TEXT
        )
    """)

    # 北向资金个股明细 (用于连续买入检测)
    c.execute("""
        CREATE TABLE IF NOT EXISTS northbound_history (
            date TEXT,
            code TEXT,
            net_buy REAL,
            holding_ratio REAL,
            source TEXT,
            PRIMARY KEY (date, code)
        )
    """)

    # 新闻AI分析结果
    c.execute("""
        CREATE TABLE IF NOT EXISTS news_analysis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            news_id INTEGER,
            timestamp TEXT,
            direction TEXT,
            affected_stocks TEXT,
            time_horizon TEXT,
            confidence TEXT,
            reasoning TEXT,
            FOREIGN KEY (news_id) REFERENCES news(id)
        )
    """)

    # 材料价格数据
    c.execute("""
        CREATE TABLE IF NOT EXISTS material_prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            material TEXT,
            price REAL,
            unit TEXT,
            change_pct REAL,
            stockpile REAL,
            stockpile_unit TEXT,
            stockpile_change_pct REAL,
            source TEXT,
            ai_impact TEXT,
            UNIQUE(timestamp, material)
        )
    """)

    # 先行信号 v2（核心信号表）
    c.execute("""
        CREATE TABLE IF NOT EXISTS signals_v2 (
            id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            source TEXT NOT NULL,
            type TEXT NOT NULL,
            target_stocks TEXT,
            target_sectors TEXT,
            direction TEXT,
            severity TEXT NOT NULL,
            lead_time_days INTEGER,
            confidence REAL,
            strength REAL,
            raw_data TEXT,
            description TEXT,
            corroboration TEXT,
            status TEXT DEFAULT 'active',
            ai_verdict TEXT,
            price_at_creation REAL,
            price_verified_at TEXT,
            price_change_pct REAL
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

# ============================================================
# 上游产业数据
# ============================================================
def insert_upstream(source, date, metric, value, unit="", yoy=None, mom=None, raw=None):
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO upstream_data (source,date,metric,value,unit,yoy_change,mom_change,raw_json) VALUES (?,?,?,?,?,?,?,?)",
        (source, date, metric, value, unit, yoy, mom, raw)
    )
    conn.commit()
    conn.close()

def get_upstream_latest(source, metric, limit=12):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM upstream_data WHERE source=? AND metric=? ORDER BY date DESC LIMIT ?",
        (source, metric, limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_upstream_recent(source, days=90):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM upstream_data WHERE source=? ORDER BY date DESC",
        (source,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ============================================================
# 海外标的
# ============================================================
def insert_overseas_daily(symbol, date, open_, high, low, close, volume, change_pct, ah_price=None, ah_change=None):
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO overseas_daily VALUES (?,?,?,?,?,?,?,?,?,?)",
        (symbol, date, open_, high, low, close, volume, change_pct, ah_price, ah_change)
    )
    conn.commit()
    conn.close()

def get_overseas_history(symbol, days=30):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM overseas_daily WHERE symbol=? ORDER BY date DESC LIMIT ?",
        (symbol, days)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ============================================================
# AI分析结果
# ============================================================
def insert_ai_analysis(target, analysis_type, direction, confidence, catalyst, risk, action, key_metrics, dimensions, raw):
    conn = get_conn()
    conn.execute(
        "INSERT INTO ai_analysis (timestamp,target,analysis_type,direction,confidence,catalyst,risk,action,key_metrics,supporting_dimensions,raw_response) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (datetime.now().isoformat(), target, analysis_type, direction, confidence, catalyst, risk, action, key_metrics, dimensions, raw)
    )
    conn.commit()
    conn.close()

def get_ai_analysis_recent(limit=20):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM ai_analysis ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ============================================================
# 北向资金个股明细
# ============================================================
def insert_northbound_history(date, code, net_buy, holding_ratio=None, source="eastmoney"):
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO northbound_history VALUES (?,?,?,?,?)",
        (date, code, net_buy, holding_ratio, source)
    )
    conn.commit()
    conn.close()

def get_northbound_by_code(code, days=10):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM northbound_history WHERE code=? ORDER BY date DESC LIMIT ?",
        (code, days)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_northbound_consecutive_buy(code, min_days=3):
    """检测连续N天净买入"""
    rows = get_northbound_by_code(code, days=min_days + 2)
    if len(rows) < min_days:
        return 0, 0
    consecutive = 0
    total = 0
    for r in rows:
        if r["net_buy"] and r["net_buy"] > 0:
            consecutive += 1
            total += r["net_buy"]
        else:
            break
    return consecutive, total

# ============================================================
# 新闻AI分析
# ============================================================
def insert_news_analysis(news_id, direction, affected_stocks, time_horizon, confidence, reasoning):
    conn = get_conn()
    conn.execute(
        "INSERT INTO news_analysis (news_id,timestamp,direction,affected_stocks,time_horizon,confidence,reasoning) VALUES (?,?,?,?,?,?,?)",
        (news_id, datetime.now().isoformat(), direction, affected_stocks, time_horizon, confidence, reasoning)
    )
    conn.commit()
    conn.close()

# ============================================================
# 材料价格
# ============================================================
def insert_material_price(material, price, unit, change_pct, stockpile=None, stockpile_unit=None, stockpile_change_pct=None, source="", ai_impact=""):
    conn = get_conn()
    conn.execute(
        """INSERT OR REPLACE INTO material_prices
           (timestamp, material, price, unit, change_pct, stockpile, stockpile_unit, stockpile_change_pct, source, ai_impact)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (datetime.now().isoformat(), material, price, unit, change_pct,
         stockpile, stockpile_unit, stockpile_change_pct, source, ai_impact)
    )
    conn.commit()
    conn.close()

def get_latest_materials():
    conn = get_conn()
    rows = conn.execute(
        """SELECT * FROM material_prices
           WHERE id IN (SELECT MAX(id) FROM material_prices GROUP BY material)
           ORDER BY material"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_material_history(material, days=30):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM material_prices WHERE material=? ORDER BY timestamp DESC LIMIT ?",
        (material, days)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ============================================================
# 信号 v2 CRUD
# ============================================================
import json as _json

def insert_signal_v2(signal):
    """保存Signal对象到signals_v2表"""
    conn = get_conn()
    d = signal.to_dict() if hasattr(signal, 'to_dict') else signal
    conn.execute(
        """INSERT OR REPLACE INTO signals_v2
           (id, timestamp, source, type, target_stocks, target_sectors,
            direction, severity, lead_time_days, confidence, strength,
            raw_data, description, corroboration, status, ai_verdict,
            price_at_creation, price_verified_at, price_change_pct)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (d["id"], d["timestamp"], d["source"], d["type"],
         _json.dumps(d["target_stocks"], ensure_ascii=False),
         _json.dumps(d["target_sectors"], ensure_ascii=False),
         d["direction"], d["severity"], d["lead_time_days"],
         d["confidence"], d["strength"],
         _json.dumps(d["raw_data"], ensure_ascii=False),
         d["description"],
         _json.dumps(d["corroboration"], ensure_ascii=False),
         d["status"],
         _json.dumps(d["ai_verdict"], ensure_ascii=False) if d.get("ai_verdict") else None,
         d.get("price_at_creation"),
         d.get("price_verified_at"),
         d.get("price_change_pct"))
    )
    conn.commit()
    conn.close()


def get_active_signals(limit=50):
    """获取活跃信号，按severity+confidence排序"""
    conn = get_conn()
    rows = conn.execute(
        """SELECT * FROM signals_v2
           WHERE status IN ('active', 'confirmed')
           ORDER BY
             CASE severity WHEN 'S1' THEN 1 WHEN 'S2' THEN 2
                           WHEN 'S3' THEN 3 ELSE 4 END,
             confidence DESC
           LIMIT ?""",
        (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_signals_by_sector(sector, limit=20):
    """按板块查询信号"""
    conn = get_conn()
    rows = conn.execute(
        """SELECT * FROM signals_v2
           WHERE target_sectors LIKE ? AND status IN ('active', 'confirmed')
           ORDER BY confidence DESC LIMIT ?""",
        (f'%{sector}%', limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_signal_by_id(signal_id):
    """按ID查询信号"""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM signals_v2 WHERE id=?", (signal_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def update_signal_status(signal_id, status):
    """更新信号状态"""
    conn = get_conn()
    conn.execute(
        "UPDATE signals_v2 SET status=? WHERE id=?",
        (status, signal_id)
    )
    conn.commit()
    conn.close()


def update_signal_corroboration(signal_id, corroborated_by):
    """添加佐证信号"""
    conn = get_conn()
    row = conn.execute(
        "SELECT corroboration FROM signals_v2 WHERE id=?", (signal_id,)
    ).fetchone()
    if row:
        existing = _json.loads(row["corroboration"]) if row["corroboration"] else []
        if corroborated_by not in existing:
            existing.append(corroborated_by)
        conn.execute(
            "UPDATE signals_v2 SET corroboration=?, status='confirmed' WHERE id=?",
            (_json.dumps(existing), signal_id)
        )
    conn.commit()
    conn.close()


def expire_old_signals():
    """过期老信号：无佐证72h，有佐证120h"""
    conn = get_conn()
    conn.execute("""
        UPDATE signals_v2 SET status='expired'
        WHERE status IN ('active', 'confirmed')
        AND (
            (corroboration = '[]' OR corroboration IS NULL
             AND julianday('now') - julianday(timestamp) > 3)
            OR
            (corroboration != '[]' AND corroboration IS NOT NULL
             AND julianday('now') - julianday(timestamp) > 5)
        )
    """)
    conn.commit()
    conn.close()


def get_signal_stats():
    """信号统计"""
    conn = get_conn()
    stats = {}
    for status in ["active", "confirmed", "expired", "verified", "invalidated"]:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM signals_v2 WHERE status=?",
            (status,)
        ).fetchone()
        stats[status] = row["cnt"]

    # 准确率 = verified / (verified + invalidated)
    v = stats.get("verified", 0)
    inv = stats.get("invalidated", 0)
    total = v + inv
    stats["accuracy"] = round(v / total * 100, 1) if total > 0 else None

    conn.close()
    return stats


def get_all_signals(limit=100, status=None, source=None):
    """查询信号（带过滤）"""
    conn = get_conn()
    sql = "SELECT * FROM signals_v2 WHERE 1=1"
    params = []
    if status:
        sql += " AND status=?"
        params.append(status)
    if source:
        sql += " AND source=?"
        params.append(source)
    sql += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]
