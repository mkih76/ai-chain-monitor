"""
M2 · 资金异动信号检测器
检测龙虎榜/融资融券/大宗交易/北向资金的异常行为

数据源:
- 龙虎榜: datacenter-web.eastmoney.com ✅ 可用
- 融资融券: datacenter-web.eastmoney.com ✅ 可用
- 大宗交易: datacenter-web.eastmoney.com ✅ 可用
- 北向个股: push2.eastmoney.com ⚠️ 部分IP被拦截
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models import Signal, Severity, Direction, SignalSource
from db import get_conn, init_db, insert_northbound_history
from datetime import datetime
import config
import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://data.eastmoney.com/",
}

# 监控标的集合（快速查找）
_WATCHLIST_CODES = set(config.WATCHLIST.keys())


def detect_capital_signals():
    """检测资金异动信号"""
    init_db()
    signals = []

    # 1. 龙虎榜机构席位
    signals.extend(_detect_dragon_tiger())

    # 2. 融资余额激增
    signals.extend(_detect_margin_surge())

    # 3. 大宗交易机构溢价买入
    signals.extend(_detect_block_trade_premium())

    return signals


def _detect_dragon_tiger():
    """
    龙虎榜信号检测
    条件: reason含"机构" + 净买入>5000万
    额外加分: 在监控标的中
    """
    signals = []
    try:
        from collectors.institutional_collector import fetch_dragon_tiger
        data = fetch_dragon_tiger(days=3)
        if not data:
            return signals

        # 按股票聚合（同一只可能多天上榜）
        by_code = {}
        for item in data:
            code = item.get("code", "")
            reason = item.get("reason", "")
            net_buy = item.get("net_buy", 0)

            # 只关注机构买入（reason含"机构"且不含"卖出"）
            if not reason or "机构" not in reason:
                continue
            if "卖出" in reason:
                continue
            if net_buy <= 50000000:  # 5000万阈值
                continue

            if code not in by_code:
                by_code[code] = []
            by_code[code].append(item)

        for code, items in by_code.items():
            total_net = sum(i["net_buy"] for i in items)
            total_net_yi = total_net / 1e8
            name = items[0]["name"]
            reason = items[0]["reason"]

            # 判断是否在监控标的中
            in_watchlist = code in _WATCHLIST_CODES
            _, sector = config.WATCHLIST.get(code, (name, ""))

            # 在监控标的中 → 更高severity
            severity = Severity.S2_HIGH if in_watchlist else Severity.S3_MEDIUM
            confidence = 0.7 if in_watchlist else 0.55

            signals.append(Signal(
                source=SignalSource.CAPITAL,
                type_="institutional_buy",
                target_stocks=[code],
                target_sectors=[sector] if sector else [],
                direction=Direction.BULLISH,
                severity=severity,
                description=(f"龙虎榜机构净买入{name}({code}) {total_net_yi:.2f}亿"
                           f"{' ★监控标的' if in_watchlist else ''} [{reason[:20]}]"),
                raw_data={
                    "code": code, "name": name,
                    "total_net_buy": total_net,
                    "reason": reason,
                    "in_watchlist": in_watchlist,
                    "entries": len(items),
                },
                lead_time_days=3,
                confidence=confidence,
                strength=confidence * 100,
            ))

    except Exception as e:
        print(f"  [ERROR] 龙虎榜检测: {e}")

    return signals


def _detect_margin_surge():
    """
    融资余额激增检测
    条件: 监控标的5日融资余额增幅>10%
    """
    signals = []
    try:
        from collectors.institutional_collector import fetch_margin_trading

        for code, (name, sector) in config.WATCHLIST.items():
            try:
                data = fetch_margin_trading(code, days=6)
            except Exception:
                continue

            if not data or len(data) < 5:
                continue

            recent = data[0].get("rz_balance", 0)
            older = data[4].get("rz_balance", 0)

            if not older or older <= 0:
                continue

            change_pct = (recent - older) / older * 100

            if change_pct > 10:
                signals.append(Signal(
                    source=SignalSource.CAPITAL,
                    type_="margin_surge",
                    target_stocks=[code],
                    target_sectors=[sector],
                    direction=Direction.BULLISH,
                    severity=Severity.S3_MEDIUM,
                    description=(f"{name}({code})融资余额5日增{change_pct:.1f}%，"
                               f"杠杆资金加速入场"),
                    raw_data={
                        "code": code,
                        "change_pct": round(change_pct, 2),
                        "recent_balance": recent,
                        "older_balance": older,
                    },
                    lead_time_days=3,
                    confidence=0.55,
                    strength=55,
                ))
    except Exception as e:
        print(f"  [ERROR] 融资检测: {e}")

    return signals


def _detect_block_trade_premium():
    """
    大宗交易溢价检测
    条件: 机构专用买入 + 溢价>5% 或 金额>5000万
    """
    signals = []
    try:
        from collectors.institutional_collector import fetch_block_trades
        data = fetch_block_trades(days=3)
        if not data:
            return signals

        # 按股票聚合
        by_code = {}
        for item in data:
            code = item.get("code", "")
            buyer = item.get("buyer", "")
            premium = item.get("premium", 0)
            amount = item.get("amount", 0)

            # 机构专用买入 + (溢价>5% 或 金额>5000万)
            is_institutional = "机构" in buyer
            is_premium = premium > 0.05
            is_large = amount > 50000000

            if not is_institutional:
                continue
            if not (is_premium or is_large):
                continue

            if code not in by_code:
                by_code[code] = []
            by_code[code].append(item)

        for code, items in by_code.items():
            total_amount = sum(i["amount"] for i in items)
            avg_premium = sum(i["premium"] for i in items) / len(items)
            name = items[0]["name"]
            in_watchlist = code in _WATCHLIST_CODES
            _, sector = config.WATCHLIST.get(code, (name, ""))

            signals.append(Signal(
                source=SignalSource.CAPITAL,
                type_="block_trade_institutional",
                target_stocks=[code],
                target_sectors=[sector] if sector else [],
                direction=Direction.BULLISH,
                severity=Severity.S3_MEDIUM,
                description=(f"大宗交易机构买入{name}({code}) "
                           f"{total_amount/1e8:.2f}亿"
                           f"{' 溢价' + str(round(avg_premium*100,1)) + '%' if avg_premium > 0 else ''}"
                           f"{' ★监控标的' if in_watchlist else ''}"),
                raw_data={
                    "code": code, "name": name,
                    "total_amount": total_amount,
                    "avg_premium": round(avg_premium, 4),
                    "entries": len(items),
                    "in_watchlist": in_watchlist,
                },
                lead_time_days=3,
                confidence=0.5 if in_watchlist else 0.4,
                strength=50,
            ))

    except Exception as e:
        print(f"  [ERROR] 大宗交易检测: {e}")

    return signals


if __name__ == "__main__":
    signals = detect_capital_signals()
    print(f"资金异动检测器产生 {len(signals)} 个信号:")
    for s in signals:
        print(f"  {s.severity} | {s.type} | {s.description}")
