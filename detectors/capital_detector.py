"""
M2 · 资金异动信号检测器
检测北向资金/龙虎榜/融资融券/大宗交易/机构调研的异常行为

核心逻辑：
- 机构和外资有信息优势，其买卖行为领先于公开信息
- 连续买入/集中买入 = 消息面出来前的建仓
- 融资余额激增 = 杠杆资金先行入场
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models import Signal, Severity, Direction, SignalSource
from db import get_conn, init_db
import config


def detect_capital_signals():
    """
    检测资金异动信号，返回Signal列表
    """
    init_db()
    signals = []

    # 1. 北向资金连续买入
    signals.extend(_detect_northbound_consecutive())

    # 2. 北向资金单日大额净买入
    signals.extend(_detect_northbound_surge())

    # 3. 龙虎榜机构席位
    signals.extend(_detect_institutional_dragon())

    # 4. 融资余额激增
    signals.extend(_detect_margin_surge())

    # 5. 机构调研密集
    signals.extend(_detect_research_cluster())

    return signals


def _detect_northbound_consecutive():
    """检测北向资金连续买入同一标的"""
    signals = []
    conn = get_conn()

    # 获取最近10天的北向资金个股数据
    rows = conn.execute("""
        SELECT code, date, net_buy
        FROM northbound_history
        WHERE date >= date('now', '-15 days')
        ORDER BY code, date DESC
    """).fetchall()
    conn.close()

    if not rows:
        return signals

    # 按股票分组，检查连续买入
    by_code = {}
    for r in rows:
        code = r["code"]
        if code not in by_code:
            by_code[code] = []
        by_code[code].append(dict(r))

    for code, trades in by_code.items():
        # 按日期降序排列
        trades.sort(key=lambda x: x["date"], reverse=True)

        # 检查连续净买入天数
        consecutive = 0
        total_net = 0
        for t in trades:
            if t["net_buy"] and t["net_buy"] > 0:
                consecutive += 1
                total_net += t["net_buy"]
            else:
                break

        if consecutive >= 3:
            name, sector = config.WATCHLIST.get(code, (code, ""))
            severity = Severity.S2_HIGH if consecutive >= 5 else Severity.S3_MEDIUM
            signals.append(Signal(
                source=SignalSource.CAPITAL,
                type_="northbound_consecutive",
                target_stocks=[code],
                target_sectors=[sector] if sector else [],
                direction=Direction.BULLISH,
                severity=severity,
                description=(f"北向资金连续{consecutive}天净买入{name}({code})，"
                           f"累计{total_net / 1e8:.2f}亿"),
                raw_data={
                    "code": code,
                    "consecutive_days": consecutive,
                    "total_net_buy": total_net,
                    "daily_trades": trades[:consecutive],
                },
                lead_time_days=5,
                confidence=min(0.5 + consecutive * 0.08, 0.85),
                strength=min(consecutive * 15, 85),
            ))

    return signals


def _detect_northbound_surge():
    """检测北向资金单日大额净买入"""
    signals = []
    conn = get_conn()

    rows = conn.execute("""
        SELECT code, date, net_buy
        FROM northbound_history
        WHERE date >= date('now', '-3 days')
        AND net_buy > 100000000
        ORDER BY net_buy DESC
    """).fetchall()
    conn.close()

    for r in rows:
        code, net_buy = r["code"], r["net_buy"]
        name, sector = config.WATCHLIST.get(code, (code, ""))
        signals.append(Signal(
            source=SignalSource.CAPITAL,
            type_="northbound_surge",
            target_stocks=[code],
            target_sectors=[sector] if sector else [],
            direction=Direction.BULLISH,
            severity=Severity.S2_HIGH,
            description=f"北向资金单日净买入{name}({code}) {net_buy / 1e8:.2f}亿",
            raw_data={"code": code, "date": r["date"], "net_buy": net_buy},
            lead_time_days=3,
            confidence=0.65,
            strength=70,
        ))

    return signals


def _detect_institutional_dragon():
    """检测龙虎榜机构席位大额买入（需从东方财富API实时获取）"""
    # 这个检测器依赖 institutional_collector 的实时数据
    # 在 detect 阶段调用 collector 获取最新龙虎榜，再检测
    signals = []
    try:
        from collectors.institutional_collector import fetch_dragon_tiger
        data = fetch_dragon_tiger(days=3)

        for item in data or []:
            if not item.get("institutional_net_buy"):
                continue
            net = item["institutional_net_buy"]
            if net > 50000000:  # 机构净买入>5000万
                code = item.get("code", "")
                name, sector = config.WATCHLIST.get(code, (code, ""))
                signals.append(Signal(
                    source=SignalSource.CAPITAL,
                    type_="institutional_buy",
                    target_stocks=[code],
                    target_sectors=[sector] if sector else [],
                    direction=Direction.BULLISH,
                    severity=Severity.S2_HIGH,
                    description=f"龙虎榜机构专用席位净买入{name}({code}) {net / 1e8:.2f}亿",
                    raw_data=item,
                    lead_time_days=3,
                    confidence=0.7,
                    strength=75,
                ))
    except Exception:
        pass  # 采集器不可用时静默跳过

    return signals


def _detect_margin_surge():
    """检测融资余额激增"""
    signals = []
    try:
        from collectors.institutional_collector import fetch_margin_trading

        for code, (name, sector) in config.WATCHLIST.items():
            data = fetch_margin_trading(code, days=10)
            if not data or len(data) < 5:
                continue

            # 计算最近5天融资余额变化率
            recent = data[0].get("rzye", 0)  # 融资余额
            older = data[4].get("rzye", 0)
            if older and older > 0:
                change_pct = (recent - older) / older * 100
                if change_pct > 10:  # 周增幅>10%
                    signals.append(Signal(
                        source=SignalSource.CAPITAL,
                        type_="margin_surge",
                        target_stocks=[code],
                        target_sectors=[sector],
                        direction=Direction.BULLISH,
                        severity=Severity.S3_MEDIUM,
                        description=(f"{name}({code})融资余额5日增幅{change_pct:.1f}%，"
                                   f"杠杆资金加速入场"),
                        raw_data={"code": code, "change_pct": round(change_pct, 2),
                                  "recent": recent, "older": older},
                        lead_time_days=3,
                        confidence=0.55,
                        strength=55,
                    ))
    except Exception:
        pass

    return signals


def _detect_research_cluster():
    """检测机构调研密集（7天内>5家机构调研同一标的）"""
    signals = []
    try:
        from collectors.institutional_collector import fetch_research_visits
        data = fetch_research_visits(days=7)

        # 按标的分组统计
        by_code = {}
        for item in data or []:
            code = item.get("code", "")
            if code not in by_code:
                by_code[code] = []
            by_code[code].append(item)

        for code, visits in by_code.items():
            if len(visits) >= 5:
                name, sector = config.WATCHLIST.get(code, (code, ""))
                signals.append(Signal(
                    source=SignalSource.CAPITAL,
                    type_="research_cluster",
                    target_stocks=[code],
                    target_sectors=[sector] if sector else [],
                    direction=Direction.BULLISH,
                    severity=Severity.S3_MEDIUM,
                    description=(f"{name}({code})7天内获{len(visits)}家机构密集调研，"
                               f"关注度异常升高"),
                    raw_data={"code": code, "visit_count": len(visits),
                              "visits": visits[:10]},
                    lead_time_days=7,
                    confidence=0.5,
                    strength=50,
                ))
    except Exception:
        pass

    return signals


if __name__ == "__main__":
    signals = detect_capital_signals()
    print(f"资金异动检测器产生 {len(signals)} 个信号:")
    for s in signals:
        print(f"  {s.severity} | {s.type} | {s.description} | conf={s.confidence}")
