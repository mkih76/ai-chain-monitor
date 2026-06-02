"""
AI产业链监控 - 预测回测系统
核心进化能力:
  1. 记录每次AI预测（方向、置信度、标的）
  2. N天后自动回测实际涨跌
  3. 统计准确率，按维度/置信度分组
  4. 自动校准信号阈值和AI prompt权重
"""
import sys
import os
import json
import sqlite3
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import get_conn, init_db, get_stock_history
import config

# ============================================================
# 1. 预测记录表
# ============================================================
def _ensure_prediction_table():
    """确保预测表存在"""
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            target TEXT,
            direction TEXT,
            confidence TEXT,
            catalyst TEXT,
            risk TEXT,
            action TEXT,
            -- 回测字段
            check_date TEXT,
            actual_direction TEXT,
            actual_change_pct REAL,
            correct INTEGER,
            checked INTEGER DEFAULT 0,
            -- 校准字段
            prompt_version TEXT DEFAULT 'v1',
            signal_thresholds TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS calibration_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            param_name TEXT,
            old_value TEXT,
            new_value TEXT,
            reason TEXT,
            accuracy_before REAL,
            accuracy_after REAL
        )
    """)
    conn.commit()
    conn.close()

def save_prediction(target, direction, confidence, catalyst="", risk="", action=""):
    """保存一条预测记录"""
    _ensure_prediction_table()
    conn = get_conn()
    # 预测验证日期：3个交易日后
    check_date = (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d")
    conn.execute(
        """INSERT INTO predictions
           (timestamp, target, direction, confidence, catalyst, risk, action, check_date)
           VALUES (?,?,?,?,?,?,?,?)""",
        (datetime.now().isoformat(), target, direction, confidence,
         catalyst, risk, action, check_date)
    )
    conn.commit()
    conn.close()

# ============================================================
# 2. 回测系统
# ============================================================
def backtest_expired_predictions():
    """回测已到期的预测，对比实际涨跌"""
    _ensure_prediction_table()
    conn = get_conn()
    today = datetime.now().strftime("%Y-%m-%d")

    # 找出已到期但未回测的预测
    rows = conn.execute(
        """SELECT * FROM predictions
           WHERE checked=0 AND check_date <= ? AND target != 'GLOBAL'""",
        (today,)
    ).fetchall()
    conn.close()

    if not rows:
        return []

    results = []
    for row in rows:
        row = dict(row)
        target = row["target"]
        predicted_dir = row["direction"]

        # 获取预测时的价格和当前价格
        history = get_stock_history(target, days=10)
        if len(history) < 2:
            continue

        # 找到预测日期附近的价格
        pred_date = row["timestamp"][:10]
        pred_price = None
        current_price = history[0]["close"]

        for h in history:
            if h["date"] >= pred_date:
                pred_price = h["close"]
                break

        if not pred_price or pred_price == 0:
            continue

        actual_change = (current_price - pred_price) / pred_price * 100
        actual_dir = "bullish" if actual_change > 1 else ("bearish" if actual_change < -1 else "neutral")

        # 判断预测是否正确
        correct = False
        if predicted_dir == "bullish" and actual_change > 0:
            correct = True
        elif predicted_dir == "bearish" and actual_change < 0:
            correct = True
        elif predicted_dir == "neutral" and abs(actual_change) < 2:
            correct = True

        # 更新数据库
        conn = get_conn()
        conn.execute(
            """UPDATE predictions SET
               checked=1, actual_direction=?, actual_change_pct=?, correct=?
               WHERE id=?""",
            (actual_dir, round(actual_change, 2), 1 if correct else 0, row["id"])
        )
        conn.commit()
        conn.close()

        results.append({
            "id": row["id"],
            "target": target,
            "predicted": predicted_dir,
            "actual": actual_dir,
            "actual_change": round(actual_change, 2),
            "correct": correct,
            "confidence": row["confidence"],
        })

        icon = "✓" if correct else "✗"
        print(f"  {icon} {target}: 预测{predicted_dir} → 实际{actual_change:+.1f}% ({actual_dir})")

    return results

def weekly_backtest():
    """周度回测汇总统计"""
    _ensure_prediction_table()
    conn = get_conn()

    # 最近7天的已回测预测
    week_ago = (datetime.now() - timedelta(days=7)).isoformat()
    rows = conn.execute(
        """SELECT * FROM predictions
           WHERE checked=1 AND timestamp >= ?
           ORDER BY timestamp DESC""",
        (week_ago,)
    ).fetchall()
    conn.close()

    if not rows:
        print("  本周无回测数据")
        return None

    rows = [dict(r) for r in rows]
    total = len(rows)
    correct = sum(1 for r in rows if r["correct"])

    # 按置信度分组
    by_confidence = {}
    for r in rows:
        conf = r["confidence"]
        if conf not in by_confidence:
            by_confidence[conf] = {"total": 0, "correct": 0}
        by_confidence[conf]["total"] += 1
        if r["correct"]:
            by_confidence[conf]["correct"] += 1

    # 按方向分组
    by_direction = {}
    for r in rows:
        d = r["direction"]
        if d not in by_direction:
            by_direction[d] = {"total": 0, "correct": 0}
        by_direction[d]["total"] += 1
        if r["correct"]:
            by_direction[d]["correct"] += 1

    stats = {
        "total": total,
        "correct": correct,
        "accuracy": round(correct / total * 100, 1) if total > 0 else 0,
        "by_confidence": {},
        "by_direction": {},
    }

    print(f"\n  === 周度回测报告 ===")
    print(f"  总预测: {total} | 正确: {correct} | 准确率: {stats['accuracy']}%")

    print(f"\n  按置信度:")
    for conf, data in by_confidence.items():
        acc = round(data["correct"] / data["total"] * 100, 1) if data["total"] > 0 else 0
        stats["by_confidence"][conf] = acc
        print(f"    {conf}: {data['correct']}/{data['total']} ({acc}%)")

    print(f"\n  按方向:")
    for d, data in by_direction.items():
        acc = round(data["correct"] / data["total"] * 100, 1) if data["total"] > 0 else 0
        stats["by_direction"][d] = acc
        print(f"    {d}: {data['correct']}/{data['total']} ({acc}%)")

    return stats

# ============================================================
# 3. 自动校准
# ============================================================
def auto_calibrate(stats):
    """根据回测结果自动校准阈值"""
    if not stats or stats["total"] < 5:
        print("  样本不足，跳过自动校准")
        return []

    calibrations = []
    conn = get_conn()

    # 校准1: 如果高置信度准确率低于60%，降低AI分析权重
    high_conf_acc = stats["by_confidence"].get("high", 100)
    if high_conf_acc < 60:
        reason = f"高置信度准确率仅{high_conf_acc}%，需要更保守"
        old_val = config.AI_ENGINE.get("confidence_threshold", "medium")
        new_val = "high"  # 只推送高置信度
        _log_calibration(conn, "ai_confidence_threshold", str(old_val), str(new_val),
                        reason, high_conf_acc, None)
        calibrations.append({"param": "ai_confidence_threshold", "old": old_val, "new": new_val})

    # 校准2: 如果看多准确率低，提高价格信号阈值
    bullish_acc = stats["by_direction"].get("bullish", 100)
    if bullish_acc < 50 and stats["by_direction"].get("bullish", {}).get("total", 0) >= 3:
        reason = f"看多准确率仅{bullish_acc}%，提高价格信号门槛"
        old_pct = config.SIGNALS["price_surge_pct"]
        new_pct = min(old_pct + 1.0, 8.0)
        _log_calibration(conn, "price_surge_pct", str(old_pct), str(new_pct),
                        reason, bullish_acc, None)
        calibrations.append({"param": "price_surge_pct", "old": old_pct, "new": new_pct})

    # 校准3: 如果看空准确率低，降低价格信号阈值（更敏感）
    bearish_acc = stats["by_direction"].get("bearish", 100)
    if bearish_acc < 50 and stats["by_direction"].get("bearish", {}).get("total", 0) >= 3:
        reason = f"看空准确率仅{bearish_acc}%，降低下跌信号门槛"
        old_pct = config.SIGNALS["price_drop_pct"]
        new_pct = max(old_pct - 1.0, -8.0)
        _log_calibration(conn, "price_drop_pct", str(old_pct), str(new_pct),
                        reason, bearish_acc, None)
        calibrations.append({"param": "price_drop_pct", "old": old_pct, "new": new_pct})

    # 校准4: 如果整体准确率低于40%，缩小监控范围（只保留高权重标的）
    if stats["accuracy"] < 40:
        reason = f"整体准确率仅{stats['accuracy']}%，建议聚焦核心标的"
        _log_calibration(conn, "focus_recommendation", "all", "core_only",
                        reason, stats["accuracy"], None)
        calibrations.append({"param": "focus_recommendation", "old": "all", "new": "core_only"})

    conn.commit()
    conn.close()

    return calibrations

def _log_calibration(conn, param_name, old_value, new_value, reason, acc_before, acc_after):
    """记录校准日志"""
    conn.execute(
        """INSERT INTO calibration_log
           (timestamp, param_name, old_value, new_value, reason, accuracy_before, accuracy_after)
           VALUES (?,?,?,?,?,?,?)""",
        (datetime.now().isoformat(), param_name, old_value, new_value,
         reason, acc_before, acc_after)
    )

def get_calibration_history(limit=20):
    """获取校准历史"""
    _ensure_prediction_table()
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM calibration_log ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_prediction_stats():
    """获取预测统计概览"""
    _ensure_prediction_table()
    conn = get_conn()

    total = conn.execute("SELECT COUNT(*) FROM predictions WHERE checked=1").fetchone()[0]
    correct = conn.execute("SELECT COUNT(*) FROM predictions WHERE checked=1 AND correct=1").fetchone()[0]
    unchecked = conn.execute("SELECT COUNT(*) FROM predictions WHERE checked=0").fetchone()[0]

    # 最近10条预测
    recent = conn.execute(
        "SELECT * FROM predictions ORDER BY id DESC LIMIT 10"
    ).fetchall()

    conn.close()

    return {
        "total_checked": total,
        "correct": correct,
        "accuracy": round(correct / total * 100, 1) if total > 0 else 0,
        "unchecked": unchecked,
        "recent": [dict(r) for r in recent],
    }

if __name__ == "__main__":
    init_db()
    _ensure_prediction_table()
    print("=== 预测回测系统 ===")
    stats = get_prediction_stats()
    print(f"已回测: {stats['total_checked']} | 正确: {stats['correct']} | 准确率: {stats['accuracy']}%")
    print(f"待回测: {stats['unchecked']}")

    print("\n=== 执行回测 ===")
    results = backtest_expired_predictions()

    print("\n=== 周度统计 ===")
    weekly_stats = weekly_backtest()
