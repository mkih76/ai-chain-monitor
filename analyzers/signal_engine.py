"""
投行级信号分析引擎
新增维度：估值异动、融资融券变化、龙虎榜上榜、机构调研密度、大宗交易溢价/折价
"""
import sys
import time
sys.path.insert(0, "/opt/ai-monitor")
from db import get_stock_history, get_inventory_history, insert_signal
from collectors.inventory_collector import get_inventory_trend
from collectors.institutional_collector import (
    fetch_valuation, fetch_margin_trading, fetch_dragon_tiger,
    fetch_institutional_visits, fetch_block_trades, fetch_northbound_realtime
)
from datetime import datetime, timedelta
import config

# ============================================================
# 原有信号（价格/库存/日历）
# ============================================================
def analyze_stock_signals(code, name, sector):
    """分析单只股票的价格信号"""
    signals = []
    history = get_stock_history(code, days=60)
    if len(history) < 5:
        return signals
    latest = history[0]
    close = latest["close"]
    volume = latest["volume"]

    # 涨跌幅
    if len(history) >= 2:
        prev_close = history[1]["close"]
        if prev_close > 0:
            change_pct = (close - prev_close) / prev_close * 100
            if change_pct >= config.SIGNALS["price_surge_pct"]:
                signals.append({
                    "type": "price_surge", "source": f"{name}({code})",
                    "title": f"🚀 {name} 单日涨 {change_pct:.1f}%",
                    "detail": f"收盘价 {close}，板块: {sector}，日期: {latest['date']}",
                    "severity": "high" if change_pct >= 7 else "medium",
                })
            elif change_pct <= config.SIGNALS["price_drop_pct"]:
                signals.append({
                    "type": "price_drop", "source": f"{name}({code})",
                    "title": f"📉 {name} 单日跌 {change_pct:.1f}%",
                    "detail": f"收盘价 {close}，板块: {sector}，日期: {latest['date']}",
                    "severity": "high" if change_pct <= -7 else "medium",
                })

    # 创新高/新低
    lookback = config.SIGNALS["price_new_high_days"]
    if len(history) >= lookback:
        recent_closes = [h["close"] for h in history[:lookback]]
        if close >= max(recent_closes):
            signals.append({
                "type": "new_high", "source": f"{name}({code})",
                "title": f"📈 {name} 创{lookback}日新高",
                "detail": f"收盘价 {close}，突破{lookback}日最高点",
                "severity": "medium",
            })
        elif close <= min(recent_closes):
            signals.append({
                "type": "new_low", "source": f"{name}({code})",
                "title": f"⚠️ {name} 创{lookback}日新低",
                "detail": f"收盘价 {close}，跌破{lookback}日最低点",
                "severity": "medium",
            })

    # 放量
    if len(history) >= 20:
        avg_vol = sum(h["volume"] for h in history[1:21]) / 20
        if avg_vol > 0 and volume >= avg_vol * config.SIGNALS["volume_surge_ratio"]:
            ratio = volume / avg_vol
            signals.append({
                "type": "volume_surge", "source": f"{name}({code})",
                "title": f"🔊 {name} 放量 {ratio:.1f}倍",
                "detail": f"成交量 {volume/10000:.0f}万手，20日均量 {avg_vol/10000:.0f}万手",
                "severity": "medium",
            })

    return signals

def analyze_inventory_signals():
    """分析库存信号"""
    signals = []
    tin_trend = get_inventory_trend("tin", weeks=5)
    if tin_trend["trend"] == "declining" and tin_trend["weeks"] >= config.SIGNALS["shfe_tin_decline_weeks"]:
        signals.append({
            "type": "inventory_decline", "source": "SHFE锡库存",
            "title": f"🔻 锡库存连续{tin_trend['weeks']}周下降",
            "detail": f"当前库存 {tin_trend['latest']:.0f}吨，累计下降 {abs(tin_trend['change_total']):.0f}吨",
            "severity": "high" if tin_trend["latest"] < config.SIGNALS["shfe_tin_low_threshold"] else "medium",
        })
    if 0 < tin_trend.get("latest", 99999) < config.SIGNALS["shfe_tin_low_threshold"]:
        signals.append({
            "type": "inventory_critical", "source": "SHFE锡库存",
            "title": f"🚨 锡库存降至 {tin_trend['latest']:.0f}吨（警戒线）",
            "detail": f"低于{config.SIGNALS['shfe_tin_low_threshold']}吨警戒线",
            "severity": "critical",
        })
    copper_trend = get_inventory_trend("copper", weeks=5)
    if 0 < copper_trend.get("latest", 99999) < config.SIGNALS["shfe_copper_low_threshold"]:
        signals.append({
            "type": "inventory_critical", "source": "SHFE铜库存",
            "title": f"⚠️ 铜库存降至 {copper_trend['latest']:.0f}吨",
            "detail": "AI数据中心铜需求推升", "severity": "medium",
        })
    return signals

def analyze_calendar_signals():
    """分析日历事件信号"""
    signals = []
    today = datetime.now().date()
    remind_days = config.SIGNALS["earnings_remind_days"]
    for event in config.CALENDAR_EVENTS:
        event_date = datetime.strptime(event["date"], "%Y-%m-%d").date()
        days_until = (event_date - today).days
        if 0 < days_until <= remind_days:
            signals.append({
                "type": "calendar_reminder", "source": "日历提醒",
                "title": f"📅 {days_until}天后: {event['event']}",
                "detail": f"影响板块: {', '.join(event['impact'])}", "severity": "medium",
            })
        elif days_until == 0:
            signals.append({
                "type": "calendar_today", "source": "日历提醒",
                "title": f"🔔 今日: {event['event']}",
                "detail": f"影响板块: {', '.join(event['impact'])}", "severity": "high",
            })
    return signals

# ============================================================
# 新增：投行级信号
# ============================================================
def analyze_valuation_signals(code, name, sector):
    """估值异动信号"""
    signals = []
    val = fetch_valuation(code)
    if not val:
        return signals

    pe = val.get("pe_ttm")
    pb = val.get("pb")
    mv = val.get("total_mv")
    change_60d = val.get("60day_change")

    # PE 异常高/低
    if pe and pe > 0:
        if pe > 100:
            signals.append({
                "type": "val_high_pe", "source": f"{name}({code})",
                "title": f"⚠️ {name} PE(TTM)={pe:.0f} 估值偏高",
                "detail": f"当前PE {pe:.0f}，需关注业绩兑现能力",
                "severity": "medium",
            })
        elif pe < 15 and sector in ("锡", "铜"):
            signals.append({
                "type": "val_low_pe", "source": f"{name}({code})",
                "title": f"💎 {name} PE(TTM)={pe:.0f} 估值偏低",
                "detail": f"当前PE {pe:.0f}，板块: {sector}，可能存在低估",
                "severity": "medium",
            })

    # 60日涨跌幅异常
    if change_60d:
        if change_60d > 50:
            signals.append({
                "type": "val_60d_surge", "source": f"{name}({code})",
                "title": f"🔥 {name} 60日涨 {change_60d:.1f}%",
                "detail": f"短期涨幅较大，注意回调风险",
                "severity": "medium",
            })
        elif change_60d < -30:
            signals.append({
                "type": "val_60d_drop", "source": f"{name}({code})",
                "title": f"💧 {name} 60日跌 {change_60d:.1f}%",
                "detail": f"深度回调，关注是否到位",
                "severity": "medium",
            })

    # 市值突破关键位
    if mv:
        if mv > 1000:
            signals.append({
                "type": "val_mega_cap", "source": f"{name}({code})",
                "title": f"🏰 {name} 市值突破 {mv:.0f}亿",
                "detail": f"总市值 {mv:.0f}亿，板块: {sector}",
                "severity": "low",
            })

    return signals

def analyze_margin_signals(code, name):
    """融资融券异动信号"""
    signals = []
    margin = fetch_margin_trading(code, days=5)
    if len(margin) < 2:
        return signals

    latest = margin[0]
    prev = margin[1]
    rz_latest = latest["rz_balance"]
    rz_prev = prev["rz_balance"]

    if rz_prev > 0:
        rz_change_pct = (rz_latest - rz_prev) / rz_prev * 100
        if rz_change_pct > 5:
            signals.append({
                "type": "margin_rz_surge", "source": f"{name}({code})",
                "title": f"📈 {name} 融资余额增 {rz_change_pct:.1f}%",
                "detail": f"融资余额 {latest['rz_balance_yi']}亿，杠杆资金流入",
                "severity": "medium",
            })
        elif rz_change_pct < -5:
            signals.append({
                "type": "margin_rz_drop", "source": f"{name}({code})",
                "title": f"📉 {name} 融资余额减 {abs(rz_change_pct):.1f}%",
                "detail": f"融资余额 {latest['rz_balance_yi']}亿，杠杆资金撤出",
                "severity": "medium",
            })

    return signals

def analyze_dragon_tiger_signals(watchlist_codes):
    """龙虎榜信号（全局，筛选监控标的中的上榜股）"""
    signals = []
    dt = fetch_dragon_tiger(days=3)
    if not dt:
        return signals

    for item in dt:
        if item["code"] in watchlist_codes:
            name = config.WATCHLIST.get(item["code"], (item["name"], ""))[0]
            net = item["net_buy"]
            if abs(net) > 5e7:  # 净买入/卖出超过5000万
                if net > 0:
                    signals.append({
                        "type": "dragon_buy", "source": f"{name}({item['code']})",
                        "title": f"🐉 {name} 龙虎榜净买入 {item['net_buy_yi']}亿",
                        "detail": f"涨跌: {item['change_pct']:.1f}%，{item['reason']}",
                        "severity": "high",
                    })
                else:
                    signals.append({
                        "type": "dragon_sell", "source": f"{name}({item['code']})",
                        "title": f"🐲 {name} 龙虎榜净卖出 {abs(item['net_buy_yi']):.2f}亿",
                        "detail": f"涨跌: {item['change_pct']:.1f}%，{item['reason']}",
                        "severity": "high",
                    })
    return signals

def analyze_block_trade_signals(watchlist_codes):
    """大宗交易信号"""
    signals = []
    trades = fetch_block_trades(days=3)
    if not trades:
        return signals

    for item in trades:
        if item["code"] in watchlist_codes:
            name = config.WATCHLIST.get(item["code"], (item["name"], ""))[0]
            premium = item.get("premium", 0) or 0
            if item["amount"] > 1e7:  # 超过1000万
                if premium > 3:
                    signals.append({
                        "type": "block_premium", "source": f"{name}({item['code']})",
                        "title": f"📦 {name} 大宗交易溢价 {premium:.1f}%",
                        "detail": f"金额 {item['amount_yi']}亿，买方: {item['buyer']}",
                        "severity": "medium",
                    })
                elif premium < -5:
                    signals.append({
                        "type": "block_discount", "source": f"{name}({item['code']})",
                        "title": f"📦 {name} 大宗交易折价 {abs(premium):.1f}%",
                        "detail": f"金额 {item['amount_yi']}亿，卖方: {item['seller']}",
                        "severity": "medium",
                    })
    return signals

def analyze_northbound_signal():
    """北向资金信号"""
    signals = []
    nb = fetch_northbound_realtime()
    if not nb or nb.get("total_net", 0) == 0:
        return signals

    total = nb["total_net"]
    if total > 1000000:  # 净流入超过100万（万元=100亿）
        signals.append({
            "type": "northbound_inflow", "source": "北向资金",
            "title": f"💰 北向资金大幅净流入 {nb['total_net_yi']}亿",
            "detail": f"沪股通: {nb['hgt_net']/10000:.1f}亿 深股通: {nb['sgt_net']/10000:.1f}亿",
            "severity": "high",
        })
    elif total < -1000000:
        signals.append({
            "type": "northbound_outflow", "source": "北向资金",
            "title": f"💸 北向资金大幅净流出 {abs(nb['total_net_yi'])}亿",
            "detail": f"沪股通: {nb['hgt_net']/10000:.1f}亿 深股通: {nb['sgt_net']/10000:.1f}亿",
            "severity": "high",
        })
    return signals

# ============================================================
# 综合分析
# ============================================================
def run_all_analysis():
    """运行全部分析"""
    all_signals = []

    # 价格信号
    print("  分析价格信号...")
    for code, (name, sector) in config.WATCHLIST.items():
        sigs = analyze_stock_signals(code, name, sector)
        all_signals.extend(sigs)

    # 库存信号
    print("  分析库存信号...")
    all_signals.extend(analyze_inventory_signals())

    # 日历信号
    print("  分析日历信号...")
    all_signals.extend(analyze_calendar_signals())

    # 存入数据库
    for sig in all_signals:
        insert_signal(sig["type"], sig["source"], sig["title"],
                      sig["detail"], sig["severity"])

    print(f"  基础信号: {len(all_signals)}个")
    return all_signals

def run_institutional_analysis():
    """运行投行级分析（较慢，需逐只请求API）"""
    all_signals = []

    # 估值信号
    print("  分析估值信号...")
    for code, (name, sector) in config.WATCHLIST.items():
        sigs = analyze_valuation_signals(code, name, sector)
        all_signals.extend(sigs)
        time.sleep(0.5)

    # 融资融券信号
    print("  分析融资融券信号...")
    for code, (name, sector) in config.WATCHLIST.items():
        sigs = analyze_margin_signals(code, name)
        all_signals.extend(sigs)
        time.sleep(0.3)

    # 龙虎榜信号
    print("  分析龙虎榜信号...")
    watchlist_codes = set(config.WATCHLIST.keys())
    all_signals.extend(analyze_dragon_tiger_signals(watchlist_codes))
    time.sleep(0.3)

    # 大宗交易信号
    print("  分析大宗交易信号...")
    all_signals.extend(analyze_block_trade_signals(watchlist_codes))
    time.sleep(0.3)

    # 北向资金信号
    print("  分析北向资金信号...")
    all_signals.extend(analyze_northbound_signal())

    # 存入数据库
    for sig in all_signals:
        insert_signal(sig["type"], sig["source"], sig["title"],
                      sig["detail"], sig["severity"])

    print(f"  投行信号: {len(all_signals)}个")
    return all_signals

def run_full_analysis():
    """完整分析 = 基础 + 投行"""
    basic = run_all_analysis()
    institutional = run_institutional_analysis()
    return basic + institutional

if __name__ == "__main__":
    import time
    signals = run_full_analysis()
    for s in signals:
        icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "⚪"}.get(s["severity"], "⚪")
        print(f"{icon} {s['title']}")
        print(f"   {s['detail']}")
