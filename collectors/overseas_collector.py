"""
海外标的监控采集器
监控美股AI龙头(NVDA/TSM/AVGO/MU/SMCI/ASML)的盘后价格
海外标的异动通常领先A股对应板块1-2天
"""
import requests
import json
import time
from datetime import datetime
import sys
sys.path.insert(0, "/opt/ai-monitor")
from db import insert_overseas_daily, get_overseas_history
import config

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}

# Yahoo Finance API (免费，无需认证)
def _yahoo_code(symbol):
    """直接使用Yahoo Finance代码"""
    return symbol

def fetch_yahoo_quote(symbol):
    """从Yahoo Finance获取实时/盘后行情"""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{_yahoo_code(symbol)}"
    params = {
        "interval": "1d",
        "range": "5d",
        "includePrePost": "true",
    }
    try:
        r = requests.get(url, params=params, headers={
            "User-Agent": "Mozilla/5.0",
        }, timeout=15)
        if r.status_code != 200:
            return {}

        data = r.json()
        result = data.get("chart", {}).get("result", [])
        if not result:
            return {}

        meta = result[0].get("meta", {})
        indicators = result[0].get("indicators", {})
        quotes = indicators.get("quote", [{}])
        if not quotes:
            return {}

        quote = quotes[0]
        timestamps = result[0].get("timestamp", [])
        if not timestamps:
            return {}

        # 取最新一根K线
        closes = quote.get("close", [])
        opens = quote.get("open", [])
        highs = quote.get("high", [])
        lows = quote.get("low", [])
        volumes = quote.get("volume", [])

        if not closes or not closes[-1]:
            return {}

        latest_close = closes[-1]
        prev_close = closes[-2] if len(closes) >= 2 and closes[-2] else latest_close
        change_pct = round((latest_close - prev_close) / prev_close * 100, 2) if prev_close > 0 else 0

        # 盘后价格
        post_price = meta.get("postMarketPrice")
        post_change = None
        if post_price and latest_close > 0:
            post_change = round((post_price - latest_close) / latest_close * 100, 2)

        date_str = datetime.fromtimestamp(timestamps[-1]).strftime("%Y-%m-%d")

        return {
            "symbol": symbol,
            "name": meta.get("shortName", symbol),
            "date": date_str,
            "open": opens[-1] if opens else latest_close,
            "high": max(h for h in highs if h) if highs else latest_close,
            "low": min(l for l in lows if l) if lows else latest_close,
            "close": latest_close,
            "volume": volumes[-1] if volumes else 0,
            "change_pct": change_pct,
            "post_market_price": post_price,
            "post_market_change_pct": post_change,
            "currency": meta.get("currency", "USD"),
        }
    except Exception as e:
        print(f"[ERROR] fetch_yahoo_quote {symbol}: {e}")
        return {}

def fetch_yahoo_history(symbol, days=30):
    """获取海外标的历史K线"""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{_yahoo_code(symbol)}"
    params = {
        "interval": "1d",
        "range": f"{days}d",
    }
    try:
        r = requests.get(url, params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        if r.status_code != 200:
            return []
        data = r.json()
        result = data.get("chart", {}).get("result", [])
        if not result:
            return []

        timestamps = result[0].get("timestamp", [])
        quote = result[0].get("indicators", {}).get("quote", [{}])[0]
        closes = quote.get("close", [])
        opens = quote.get("open", [])
        highs = quote.get("high", [])
        lows = quote.get("low", [])
        volumes = quote.get("volume", [])

        results = []
        for i in range(len(timestamps)):
            if closes[i] is None:
                continue
            date_str = datetime.fromtimestamp(timestamps[i]).strftime("%Y-%m-%d")
            prev = closes[i-1] if i > 0 and closes[i-1] else closes[i]
            chg = round((closes[i] - prev) / prev * 100, 2) if prev > 0 else 0
            results.append({
                "date": date_str,
                "open": opens[i] if opens[i] else closes[i],
                "high": highs[i] if highs[i] else closes[i],
                "low": lows[i] if lows[i] else closes[i],
                "close": closes[i],
                "volume": volumes[i] if volumes[i] else 0,
                "change_pct": chg,
            })
        return results
    except Exception as e:
        print(f"[ERROR] fetch_yahoo_history {symbol}: {e}")
        return []

# 备用: 新浪美股行情
def fetch_sina_us_quote(symbol):
    """新浪美股行情(备用)"""
    sina_map = {
        "NVDA": "nvda", "TSM": "tsm", "AVGO": "avgo",
        "MU": "mu", "SMCI": "smci", "ASML": "asml",
    }
    sina_code = sina_map.get(symbol, symbol.lower())
    url = f"https://hq.sinajs.cn/list=gb_{sina_code}"
    try:
        r = requests.get(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://finance.sina.com.cn/",
        }, timeout=10)
        r.encoding = "gbk"
        text = r.text
        if "=" not in text or '""' in text:
            return {}
        parts = text.split('"')[1].split(",")
        if len(parts) < 20:
            return {}
        return {
            "symbol": symbol,
            "name": parts[0],
            "close": float(parts[1]) if parts[1] else 0,
            "change_pct": float(parts[2]) if parts[2] else 0,
            "volume": float(parts[10]) if parts[10] else 0,
            "date": parts[12] if len(parts) > 12 else datetime.now().strftime("%Y-%m-%d"),
        }
    except Exception as e:
        print(f"[ERROR] fetch_sina_us {symbol}: {e}")
        return {}

# ============================================================
# 综合采集
# ============================================================
def collect_overseas_stocks():
    """采集所有海外标的行情"""
    print("  === 采集海外标的行情 ===")
    results = {}

    for symbol in config.OVERSEAS_STOCKS:
        info = config.OVERSEAS_STOCKS[symbol]
        quote = fetch_yahoo_quote(symbol)
        if not quote:
            quote = fetch_sina_us_quote(symbol)

        if quote and quote.get("close", 0) > 0:
            # 存入数据库
            insert_overseas_daily(
                symbol, quote.get("date", datetime.now().strftime("%Y-%m-%d")),
                quote.get("open", 0), quote.get("high", 0),
                quote.get("low", 0), quote["close"],
                quote.get("volume", 0), quote.get("change_pct", 0),
                quote.get("post_market_price"),
                quote.get("post_market_change_pct"),
            )
            results[symbol] = quote

            # 输出
            chg = quote.get("change_pct", 0)
            icon = "🟢" if chg > 0 else ("🔴" if chg < 0 else "⚪")
            pm_str = ""
            if quote.get("post_market_price"):
                pm_chg = quote.get("post_market_change_pct", 0)
                pm_icon = "↑" if pm_chg > 0 else "↓"
                pm_str = f" 盘后{pm_icon}{abs(pm_chg):.1f}%"

            print(f"    {icon} {info['name']}({symbol}): ${quote['close']:.2f}"
                  f" {chg:+.1f}%{pm_str}")
        else:
            print(f"    ⚠ {info['name']}({symbol}): 数据不可用")

        time.sleep(0.5)

    print(f"  海外标的采集完成: {len(results)}只")
    return results

def get_overnight_changes():
    """获取隔夜海外异动，返回影响A股板块的预警"""
    alerts = []
    for symbol in config.OVERSEAS_STOCKS:
        history = get_overseas_history(symbol, days=2)
        if not history:
            continue
        latest = history[0]
        chg = latest.get("change_pct", 0) or 0
        if abs(chg) >= 3:  # 涨跌幅超过3%
            info = config.OVERSEAS_STOCKS[symbol]
            alerts.append({
                "symbol": symbol,
                "name": info["name"],
                "change_pct": chg,
                "affects": info["affects"],
                "note": info["note"],
                "severity": "high" if abs(chg) >= 5 else "medium",
            })
    return alerts

if __name__ == "__main__":
    from db import init_db
    init_db()
    results = collect_overseas_stocks()

    print("\n=== 隔夜异动检测 ===")
    alerts = get_overnight_changes()
    if alerts:
        for a in alerts:
            icon = "🟢" if a["change_pct"] > 0 else "🔴"
            print(f"  {icon} {a['name']}: {a['change_pct']:+.1f}% → 影响: {', '.join(a['affects'])}")
    else:
        print("  无显著异动")
