"""
信号验证系统 — 自动回测信号准确率

功能：
1. 检查已过期的active信号，验证价格是否按预期方向移动
2. 计算每个来源/类型的准确率
3. 为信号置信度提供历史校准数据

验证逻辑：
- 信号创建时记录价格(price_at_creation)
- 信号过期后(72h)，检查期间最大涨跌幅
- 价格移动>=2%且方向一致 → verified
- 价格移动>=2%但方向相反 → invalidated
- 价格变动<2% → expired（无法验证）
"""
import sys
import os
import json
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import get_conn, init_db


def verify_signals():
    """
    验证信号准确率
    返回: dict，包含验证结果统计
    """
    init_db()
    conn = get_conn()

    # 获取需要验证的信号（active且已过期，或已confirmed且已过期）
    rows = conn.execute("""
        SELECT * FROM signals_v2
        WHERE status IN ('active', 'confirmed')
        AND julianday('now') - julianday(timestamp) > 3
    """).fetchall()

    results = {"verified": 0, "invalidated": 0, "expired": 0, "errors": []}

    for row in rows:
        sig = dict(row)
        signal_id = sig["id"]
        target_stocks = json.loads(sig.get("target_stocks", "[]"))
        direction = sig.get("direction", "neutral")
        created_ts = sig.get("timestamp", "")

        if not target_stocks or direction == "neutral":
            # 无法验证的信号（无标的或中性方向）
            conn.execute("UPDATE signals_v2 SET status='expired' WHERE id=?",
                         (signal_id,))
            results["expired"] += 1
            continue

        # 获取创建时的价格
        price_at_creation = sig.get("price_at_creation")
        if not price_at_creation:
            # 补录创建时的价格
            price_at_creation = _get_price_at_date(target_stocks[0], created_ts[:10])
            if price_at_creation:
                conn.execute(
                    "UPDATE signals_v2 SET price_at_creation=? WHERE id=?",
                    (price_at_creation, signal_id))

        if not price_at_creation:
            results["errors"].append(f"Signal {signal_id}: 无法获取创建时价格")
            continue

        # 获取验证期间的最大涨跌幅
        # 验证窗口: 信号创建后的lead_time_days内
        lead_days = sig.get("lead_time_days", 3)
        verify_end = datetime.fromisoformat(created_ts) + timedelta(days=lead_days + 2)

        if datetime.now() < verify_end:
            # 还在验证窗口内，跳过
            continue

        max_change = _get_max_change_in_window(
            target_stocks[0], created_ts[:10], verify_end.strftime("%Y-%m-%d")
        )

        if max_change is None:
            results["errors"].append(f"Signal {signal_id}: 无法获取验证期间价格")
            continue

        # 判断验证结果
        if abs(max_change) >= 2:
            if direction == "bullish" and max_change > 0:
                status = "verified"
                results["verified"] += 1
            elif direction == "bearish" and max_change < 0:
                status = "verified"
                results["verified"] += 1
            else:
                status = "invalidated"
                results["invalidated"] += 1
        else:
            status = "expired"
            results["expired"] += 1

        conn.execute(
            """UPDATE signals_v2
               SET status=?, price_verified_at=?, price_change_pct=?
               WHERE id=?""",
            (status, datetime.now().isoformat(), round(max_change, 2), signal_id)
        )

    conn.commit()
    conn.close()

    # 计算准确率
    total = results["verified"] + results["invalidated"]
    results["accuracy"] = round(results["verified"] / total * 100, 1) if total > 0 else None

    return results


def get_accuracy_by_source():
    """按数据来源统计准确率"""
    init_db()
    conn = get_conn()
    rows = conn.execute("""
        SELECT source,
               COUNT(CASE WHEN status='verified' THEN 1 END) as verified,
               COUNT(CASE WHEN status='invalidated' THEN 1 END) as invalidated,
               COUNT(*) as total
        FROM signals_v2
        WHERE status IN ('verified', 'invalidated')
        GROUP BY source
    """).fetchall()
    conn.close()

    result = []
    for r in rows:
        d = dict(r)
        total = d["verified"] + d["invalidated"]
        d["accuracy"] = round(d["verified"] / total * 100, 1) if total > 0 else 0
        result.append(d)
    return result


def get_accuracy_by_type():
    """按信号类型统计准确率"""
    init_db()
    conn = get_conn()
    rows = conn.execute("""
        SELECT type, source,
               COUNT(CASE WHEN status='verified' THEN 1 END) as verified,
               COUNT(CASE WHEN status='invalidated' THEN 1 END) as invalidated
        FROM signals_v2
        WHERE status IN ('verified', 'invalidated')
        GROUP BY type, source
    """).fetchall()
    conn.close()

    result = []
    for r in rows:
        d = dict(r)
        total = d["verified"] + d["invalidated"]
        d["accuracy"] = round(d["verified"] / total * 100, 1) if total > 0 else 0
        result.append(d)
    return result


def get_accuracy_by_severity():
    """按信号等级统计准确率"""
    init_db()
    conn = get_conn()
    rows = conn.execute("""
        SELECT severity,
               COUNT(CASE WHEN status='verified' THEN 1 END) as verified,
               COUNT(CASE WHEN status='invalidated' THEN 1 END) as invalidated
        FROM signals_v2
        WHERE status IN ('verified', 'invalidated')
        GROUP BY severity
    """).fetchall()
    conn.close()

    result = []
    for r in rows:
        d = dict(r)
        total = d["verified"] + d["invalidated"]
        d["accuracy"] = round(d["verified"] / total * 100, 1) if total > 0 else 0
        result.append(d)
    return result


def get_recent_verifications(limit=20):
    """最近的验证结果"""
    init_db()
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM signals_v2
        WHERE status IN ('verified', 'invalidated')
        AND price_verified_at IS NOT NULL
        ORDER BY price_verified_at DESC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _get_price_at_date(code, date):
    """获取某股票某天的收盘价"""
    conn = get_conn()
    row = conn.execute(
        "SELECT close FROM stock_daily WHERE code=? AND date<=? ORDER BY date DESC LIMIT 1",
        (code, date)
    ).fetchone()
    conn.close()
    return row["close"] if row else None


def _get_max_change_in_window(code, start_date, end_date):
    """
    获取某股票在时间窗口内的最大涨跌幅
    相对于start_date的收盘价
    """
    conn = get_conn()
    # 获取起始价格
    start_row = conn.execute(
        "SELECT close FROM stock_daily WHERE code=? AND date<=? ORDER BY date DESC LIMIT 1",
        (code, start_date)
    ).fetchone()

    if not start_row:
        conn.close()
        return None

    start_price = start_row["close"]

    # 获取窗口内的所有价格
    rows = conn.execute(
        """SELECT close FROM stock_daily
           WHERE code=? AND date>? AND date<=?
           ORDER BY date""",
        (code, start_date, end_date)
    ).fetchall()
    conn.close()

    if not rows or start_price <= 0:
        return None

    # 计算最大涨跌幅
    max_change = 0
    for r in rows:
        change = (r["close"] - start_price) / start_price * 100
        if abs(change) > abs(max_change):
            max_change = change

    return max_change


def run_verification():
    """运行验证并返回完整报告"""
    print("=" * 50)
    print("信号验证系统")
    print("=" * 50)

    # 1. 验证待验证信号
    results = verify_signals()
    print(f"\n验证结果:")
    print(f"  已验证(正确): {results['verified']}")
    print(f"  已否定(错误): {results['invalidated']}")
    print(f"  已过期(无法验证): {results['expired']}")
    if results.get("accuracy") is not None:
        print(f"  准确率: {results['accuracy']}%")
    if results.get("errors"):
        print(f"  错误: {len(results['errors'])} 条")

    # 2. 按来源统计
    by_source = get_accuracy_by_source()
    if by_source:
        print(f"\n按来源统计:")
        for s in by_source:
            print(f"  {s['source']:15s} | 验证:{s['verified']} 否定:{s['invalidated']} "
                  f"准确率:{s['accuracy']}%")

    # 3. 按等级统计
    by_severity = get_accuracy_by_severity()
    if by_severity:
        print(f"\n按等级统计:")
        for s in by_severity:
            print(f"  {s['severity']:5s} | 验证:{s['verified']} 否定:{s['invalidated']} "
                  f"准确率:{s['accuracy']}%")

    # 4. 最近验证结果
    recent = get_recent_verifications(5)
    if recent:
        print(f"\n最近验证:")
        for r in recent:
            status_icon = "✓" if r["status"] == "verified" else "✗"
            desc = r.get("description", "")[:50]
            change = r.get("price_change_pct", 0)
            print(f"  {status_icon} [{r['severity']}] {desc}... "
                  f"({change:+.1f}%)")

    return results


if __name__ == "__main__":
    run_verification()
