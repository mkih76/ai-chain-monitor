"""
M7 · 海外映射信号检测器
检测美股AI龙头的异动，预警A股次日走势

核心逻辑：
- NVDA/TSM/AVGO等隔夜异动 → A股次日开盘前发出预警
- 美股收盘到A股开盘有12小时窗口，是天然的预警时间
- 跌幅>5% = S2级利空信号，创新高 = S3级利多信号
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models import Signal, Severity, Direction, SignalSource
from db import get_conn, init_db
import config


def detect_overseas_signals():
    """检测海外标的异动信号"""
    init_db()
    signals = []

    for symbol, info in config.OVERSEAS_STOCKS.items():
        history = _get_overseas_history(symbol, days=5)
        if not history:
            continue

        latest = history[0]
        change_pct = latest.get("change_pct", 0) or 0
        close = latest.get("close", 0) or 0

        if close <= 0:
            continue

        affected_sectors = info.get("affects", [])
        name = info["name"]

        # --- 信号1: 单日大跌>5% ---
        if change_pct < -5:
            # 拉动A股对应板块的标的
            affected_stocks = _sectors_to_stocks(affected_sectors)
            signals.append(Signal(
                source=SignalSource.OVERSEAS,
                type_="overseas_drag",
                target_stocks=affected_stocks,
                target_sectors=affected_sectors,
                direction=Direction.BEARISH,
                severity=Severity.S2_HIGH if change_pct < -7 else Severity.S3_MEDIUM,
                description=(f"{name}({symbol})隔夜{change_pct:.1f}%，"
                           f"→ A股次日{', '.join(affected_sectors[:3])}承压"),
                raw_data={
                    "symbol": symbol,
                    "close": close,
                    "change_pct": round(change_pct, 2),
                    "note": info.get("note", ""),
                },
                lead_time_days=1,  # 次日生效
                confidence=min(0.5 + abs(change_pct) * 0.04, 0.85),
                strength=min(40 + abs(change_pct) * 5, 90),
            ))

        # --- 信号2: 单日大涨>5% ---
        elif change_pct > 5:
            affected_stocks = _sectors_to_stocks(affected_sectors)
            signals.append(Signal(
                source=SignalSource.OVERSEAS,
                type_="overseas_boost",
                target_stocks=affected_stocks,
                target_sectors=affected_sectors,
                direction=Direction.BULLISH,
                severity=Severity.S2_HIGH if change_pct > 8 else Severity.S3_MEDIUM,
                description=(f"{name}({symbol})隔夜+{change_pct:.1f}%，"
                           f"→ A股次日{', '.join(affected_sectors[:3])}受益"),
                raw_data={
                    "symbol": symbol,
                    "close": close,
                    "change_pct": round(change_pct, 2),
                },
                lead_time_days=1,
                confidence=min(0.45 + change_pct * 0.04, 0.8),
                strength=min(35 + change_pct * 5, 85),
            ))

        # --- 信号3: 创60日新高 ---
        if len(history) >= 5:
            prices = [h["close"] for h in history if h.get("close")]
            if prices and close >= max(prices) * 0.98:  # 接近近期高点
                # 更严格的：检查是否创新高
                longer = _get_overseas_history(symbol, days=60)
                if longer:
                    all_prices = [h["close"] for h in longer if h.get("close")]
                    if all_prices and close >= max(all_prices):
                        affected_stocks = _sectors_to_stocks(affected_sectors)
                        signals.append(Signal(
                            source=SignalSource.OVERSEAS,
                            type_="overseas_new_high",
                            target_stocks=affected_stocks,
                            target_sectors=affected_sectors,
                            direction=Direction.BULLISH,
                            severity=Severity.S3_MEDIUM,
                            description=(f"{name}({symbol})创60日新高 ${close:.2f}，"
                                       f"动量向上→ {', '.join(affected_sectors[:3])}"),
                            raw_data={"symbol": symbol, "close": close},
                            lead_time_days=2,
                            confidence=0.5,
                            strength=50,
                        ))

    return signals


def _get_overseas_history(symbol, days=5):
    """获取海外标的历史"""
    conn = get_conn()
    rows = conn.execute(
        """SELECT * FROM overseas_daily
           WHERE symbol=?
           ORDER BY date DESC LIMIT ?""",
        (symbol, days)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _sectors_to_stocks(sectors):
    """板块名称列表→受影响的A股代码列表"""
    stocks = []
    for code, (name, sector) in config.WATCHLIST.items():
        if sector in sectors:
            stocks.append(code)
    return stocks


if __name__ == "__main__":
    signals = detect_overseas_signals()
    print(f"海外映射检测器产生 {len(signals)} 个信号:")
    for s in signals:
        print(f"  {s.severity} | {s.type} | {s.description}")
