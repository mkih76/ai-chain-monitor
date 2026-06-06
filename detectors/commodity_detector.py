"""
M3 · 商品期货联动信号检测器
检测铜/锡/镍/铝期货价格异动，推算A股传导标的

核心逻辑：
- 商品价格变化传导到A股有1-3天时滞
- 期现背离可识别投机驱动vs真实供需
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models import Signal, Severity, Direction, SignalSource
from db import get_conn, init_db
import config


# 商品→A股传导链
COMMODITY_CHAIN = {
    "tin": {
        "name": "沪锡",
        "sectors": ["锡", "封装"],
        "stocks_benefit": ["000960"],  # 锡业股份
        "stocks_pressure": ["600584", "002156"],  # 长电/通富（成本端）
    },
    "copper": {
        "name": "沪铜",
        "sectors": ["铜", "铜缆", "PCB"],
        "stocks_benefit": ["601899"],  # 紫金矿业
        "stocks_pressure": ["002916", "002436", "002130"],  # PCB/铜缆
    },
    "nickel": {
        "name": "沪镍",
        "sectors": ["镍"],
        "stocks_benefit": [],
        "stocks_pressure": [],
    },
    "aluminum": {
        "name": "沪铝",
        "sectors": ["铝"],
        "stocks_benefit": [],
        "stocks_pressure": [],
    },
}


def detect_commodity_signals():
    """检测商品期货信号"""
    init_db()
    signals = []

    for material, chain in COMMODITY_CHAIN.items():
        history = _get_material_history(material, days=25)
        if len(history) < 5:
            continue

        latest = history[0]
        price = latest.get("price", 0)
        change_pct = latest.get("change_pct", 0) or 0

        if price <= 0:
            continue

        # --- 信号1: 单日异动(>1.5%) ---
        if abs(change_pct) > 1.5:
            direction = Direction.BULLISH if change_pct > 0 else Direction.BEARISH
            target = (chain["stocks_benefit"] if change_pct > 0
                      else chain["stocks_pressure"])
            signals.append(Signal(
                source=SignalSource.COMMODITY,
                type_="commodity_surge",
                target_stocks=target,
                target_sectors=chain["sectors"],
                direction=direction,
                severity=Severity.S3_MEDIUM if abs(change_pct) < 5 else Severity.S2_HIGH,
                description=(f"{chain['name']}今日{'+' if change_pct > 0 else ''}"
                           f"{change_pct:.1f}%，"
                           f"传导→{', '.join(_code_to_name(c) for c in target[:3])}"),
                raw_data={
                    "material": material,
                    "price": price,
                    "change_pct": round(change_pct, 2),
                },
                lead_time_days=2,
                confidence=min(0.4 + abs(change_pct) * 0.05, 0.8),
                strength=min(30 + abs(change_pct) * 8, 85),
            ))

        # --- 信号2: 突破20日均线 ---
        if len(history) >= 20:
            ma20 = sum(h["price"] for h in history[:20]) / 20
            # 检查是否连续3天站上20日均线
            above_count = sum(1 for h in history[:3] if h["price"] > ma20)
            if above_count >= 3 and history[3]["price"] <= ma20 if len(history) > 3 else True:
                signals.append(Signal(
                    source=SignalSource.COMMODITY,
                    type_="commodity_breakout",
                    target_stocks=chain["stocks_benefit"],
                    target_sectors=chain["sectors"],
                    direction=Direction.BULLISH,
                    severity=Severity.S3_MEDIUM,
                    description=(f"{chain['name']}连续3日站上20日均线({ma20:.0f})，"
                               f"趋势向上"),
                    raw_data={
                        "material": material,
                        "price": price,
                        "ma20": round(ma20, 2),
                    },
                    lead_time_days=3,
                    confidence=0.55,
                    strength=55,
                ))

        # --- 信号3: 期现背离警告 ---
        inventory_history = _get_inventory_for_material(material, weeks=4)
        if inventory_history and len(inventory_history) >= 2:
            inv_rising = inventory_history[0]["stockpile"] > inventory_history[-1]["stockpile"]
            price_rising = change_pct > 1
            if inv_rising and price_rising:
                signals.append(Signal(
                    source=SignalSource.COMMODITY,
                    type_="divergence_warning",
                    target_stocks=[],
                    target_sectors=chain["sectors"],
                    direction=Direction.NEUTRAL,
                    severity=Severity.S4_WATCH,
                    description=(f"{chain['name']}期货涨但库存也在涨，"
                               f"可能是投机驱动，持续性存疑"),
                    raw_data={
                        "material": material,
                        "price_change": round(change_pct, 2),
                        "inventory_trend": "rising",
                    },
                    lead_time_days=0,
                    confidence=0.4,
                    strength=30,
                ))

    return signals


def _get_material_history(material, days=25):
    """获取材料价格历史"""
    conn = get_conn()
    rows = conn.execute(
        """SELECT * FROM material_prices
           WHERE material=?
           ORDER BY timestamp DESC LIMIT ?""",
        (material, days)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _get_inventory_for_material(material, weeks=4):
    """获取对应库存数据"""
    conn = get_conn()
    rows = conn.execute(
        """SELECT date, stockpile FROM inventory
           WHERE commodity=?
           ORDER BY date DESC LIMIT ?""",
        (material, weeks)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _code_to_name(code):
    """股票代码转名称"""
    return config.WATCHLIST.get(code, (code, ""))[0]


if __name__ == "__main__":
    signals = detect_commodity_signals()
    print(f"商品期货检测器产生 {len(signals)} 个信号:")
    for s in signals:
        print(f"  {s.severity} | {s.type} | {s.description}")
