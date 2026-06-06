"""
M1 · 库存信号检测器
检测SHFE/LME库存变化，产生先行信号

核心逻辑：
- 库存连续下降 → 供需趋紧 → 价格滞后上涨
- 库存低于历史分位 → 结构性紧缺
- 库存下降加速 → 边际恶化
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models import Signal, Severity, Direction, SignalSource
from db import get_conn, init_db
import config

# 库存→板块传导映射
INVENTORY_CHAIN = {
    "tin": {
        "name": "锡",
        "sectors": ["锡", "封装"],  # 锡业股份直接受益，长电/通富成本承压
        "stocks_up": ["000960"],    # 锡价涨→锡业股份受益
        "stocks_down": ["600584", "002156"],  # 锡价涨→封测成本承压
    },
    "copper": {
        "name": "铜",
        "sectors": ["铜", "铜缆", "PCB"],
        "stocks_up": ["601899"],    # 紫金矿业受益
        "stocks_down": ["002916", "002436", "002130"],  # PCB/铜缆成本承压
    },
    "nickel": {
        "name": "镍",
        "sectors": ["镍"],
        "stocks_up": [],
        "stocks_down": [],
    },
    "aluminum": {
        "name": "铝",
        "sectors": ["铝"],
        "stocks_up": [],
        "stocks_down": [],
    },
}


def detect_inventory_signals():
    """
    检测库存信号，返回Signal列表
    """
    init_db()
    signals = []

    for commodity, chain in INVENTORY_CHAIN.items():
        history = _get_inventory_weekly(commodity, weeks=10)
        if len(history) < 3:
            continue

        latest = history[0]  # 最新一周
        prev_weeks = history[1:]

        # --- 信号1: 连续周下降 ---
        decline_weeks = 0
        for i in range(len(history) - 1):
            if history[i]["stockpile"] < history[i + 1]["stockpile"]:
                decline_weeks += 1
            else:
                break

        if decline_weeks >= 3:
            severity = Severity.S2_CRITICAL if decline_weeks >= 5 else Severity.S3_MEDIUM
            total_decline_pct = _calc_decline_pct(history[decline_weeks], latest)
            signals.append(Signal(
                source=SignalSource.INVENTORY,
                type_="inventory_decline",
                target_stocks=chain["stocks_up"],
                target_sectors=chain["sectors"],
                direction=Direction.BULLISH,  # 库存降→价格涨压力
                severity=severity,
                description=(f"{chain['name']}库存连续{decline_weeks}周下降，"
                           f"累计降幅{total_decline_pct:.1f}%，"
                           f"当前{latest['stockpile']:.0f}吨"),
                raw_data={
                    "commodity": commodity,
                    "decline_weeks": decline_weeks,
                    "latest_stockpile": latest["stockpile"],
                    "total_decline_pct": round(total_decline_pct, 2),
                    "weekly_data": [{"date": h["date"], "stockpile": h["stockpile"]} for h in history[:decline_weeks + 1]],
                },
                lead_time_days=5,  # 历史平均领先价格5天
                confidence=min(0.5 + decline_weeks * 0.1, 0.9),
                strength=min(decline_weeks * 15, 90),
            ))

        # --- 信号2: 库存低于历史20%分位 ---
        stockpiles = [h["stockpile"] for h in history]
        p20 = sorted(stockpiles)[int(len(stockpiles) * 0.2)] if len(stockpiles) >= 5 else min(stockpiles)

        if latest["stockpile"] <= p20 and latest["stockpile"] > 0:
            signals.append(Signal(
                source=SignalSource.INVENTORY,
                type_="inventory_critical",
                target_stocks=chain["stocks_up"],
                target_sectors=chain["sectors"],
                direction=Direction.BULLISH,
                severity=Severity.S2_HIGH,
                description=(f"{chain['name']}库存降至历史低位，"
                           f"当前{latest['stockpile']:.0f}吨，低于近期80%观测值"),
                raw_data={
                    "commodity": commodity,
                    "current": latest["stockpile"],
                    "p20_threshold": p20,
                    "historical": stockpiles,
                },
                lead_time_days=7,
                confidence=0.7,
                strength=75,
            ))

        # --- 信号3: 库存下降加速 ---
        if len(history) >= 5:
            recent_decline = _calc_decline_pct(history[1], history[0])  # 最近一周
            avg_decline = sum(
                _calc_decline_pct(history[i + 1], history[i])
                for i in range(1, min(5, len(history) - 1))
            ) / min(4, len(history) - 2) if len(history) > 2 else 0

            if recent_decline > 0 and avg_decline > 0 and recent_decline > avg_decline * 2:
                signals.append(Signal(
                    source=SignalSource.INVENTORY,
                    type_="inventory_acceleration",
                    target_stocks=chain["stocks_up"],
                    target_sectors=chain["sectors"],
                    direction=Direction.BULLISH,
                    severity=Severity.S3_MEDIUM,
                    description=(f"{chain['name']}库存下降加速，本周-{recent_decline:.1f}%，"
                               f"前4周均值-{avg_decline:.1f}%，加速{recent_decline / avg_decline:.1f}倍"),
                    raw_data={
                        "commodity": commodity,
                        "recent_week_decline": round(recent_decline, 2),
                        "avg_4week_decline": round(avg_decline, 2),
                        "acceleration_ratio": round(recent_decline / avg_decline, 2),
                    },
                    lead_time_days=5,
                    confidence=0.6,
                    strength=60,
                ))

    return signals


def _get_inventory_weekly(commodity, weeks=10):
    """获取库存周数据（按周聚合）"""
    conn = get_conn()
    rows = conn.execute(
        """SELECT date, stockpile, change, source
           FROM inventory
           WHERE commodity=?
           ORDER BY date DESC
           LIMIT ?""",
        (commodity, weeks * 7)  # 最多取weeks*7条日数据
    ).fetchall()
    conn.close()

    if not rows:
        return []

    # 按周聚合（取每周最新一条）
    weekly = []
    seen_weeks = set()
    for r in rows:
        week_key = r["date"][:7] if len(r["date"]) >= 7 else r["date"]  # YYYY-MM
        if week_key not in seen_weeks:
            seen_weeks.add(week_key)
            weekly.append(dict(r))
    return weekly[:weeks]


def _calc_decline_pct(older, newer):
    """计算下降百分比"""
    if not older or not newer or not older.get("stockpile") or older["stockpile"] == 0:
        return 0
    return (older["stockpile"] - newer["stockpile"]) / older["stockpile"] * 100


if __name__ == "__main__":
    signals = detect_inventory_signals()
    print(f"库存检测器产生 {len(signals)} 个信号:")
    for s in signals:
        print(f"  {s.severity} | {s.type} | {s.description} | conf={s.confidence}")
