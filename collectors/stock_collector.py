"""
股价数据采集器 - 新浪/腾讯API（VPS友好）
东方财富API被限速，改用新浪实时行情 + 腾讯K线
"""
import requests
import json
import time
import re
from datetime import datetime, timedelta
import sys
sys.path.insert(0, "/opt/ai-monitor")
from db import insert_stock, get_stock_history
import config

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://finance.sina.com.cn/",
}

def _sina_code(code):
    """转换为新浪代码格式"""
    if code.startswith(("6", "9")):
        return f"sh{code}"
    return f"sz{code}"

def _tencent_code(code):
    """转换为腾讯代码格式"""
    if code.startswith(("6", "9")):
        return f"sh{code}"
    return f"sz{code}"

def fetch_realtime(code):
    """新浪实时行情"""
    sina = _sina_code(code)
    url = f"https://hq.sinajs.cn/list={sina}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.encoding = "gbk"
        text = r.text
        # 解析: var hq_str_sz000960="名称,今开,昨收,最新,最高,最低,...";
        match = re.search(r'"([^"]+)"', text)
        if not match:
            return {}
        parts = match.group(1).split(",")
        if len(parts) < 32:
            return {}
        return {
            "code": code,
            "name": parts[0],
            "open": float(parts[1]),
            "prev_close": float(parts[2]),
            "price": float(parts[3]),
            "high": float(parts[4]),
            "low": float(parts[5]),
            "volume": float(parts[8]),      # 成交量(股)
            "amount": float(parts[9]),      # 成交额
            "date": parts[30],
            "time": parts[31],
            "change_pct": round((float(parts[3]) - float(parts[2])) / float(parts[2]) * 100, 2) if float(parts[2]) > 0 else 0,
        }
    except Exception as e:
        print(f"[ERROR] fetch_realtime {code}: {e}")
        return {}

def fetch_kline(code, days=60):
    """腾讯K线历史数据"""
    tc = _tencent_code(code)
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=days*2)).strftime("%Y-%m-%d")
    url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    params = {
        "param": f"{tc},day,{start_date},{end_date},{days},qfq",
    }
    try:
        r = requests.get(url, params=params, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://web.sqt.gtimg.cn/",
        }, timeout=15)
        data = r.json()
        stock_data = data.get("data", {}).get(tc, {})
        klines = stock_data.get("qfqday", []) or stock_data.get("day", [])
        if not klines:
            return _fetch_kline_sina(code, days)

        results = []
        name = config.WATCHLIST.get(code, (code, ""))[0]
        for k in klines:
            # 格式: [日期, 开盘, 收盘, 最高, 最低, 成交量]
            date, open_, close, high, low = k[0], float(k[1]), float(k[2]), float(k[3]), float(k[4])
            vol = float(k[5]) if len(k) > 5 else 0
            insert_stock(code, date, open_, high, low, close, vol, 0)
            results.append({
                "date": date, "open": open_, "close": close,
                "high": high, "low": low, "volume": vol, "name": name
            })
        return results
    except Exception as e:
        print(f"[ERROR] fetch_kline(tencent) {code}: {e}")
        return _fetch_kline_sina(code, days)

def _fetch_kline_sina(code, days=60):
    """新浪K线备用接口"""
    sina = _sina_code(code)
    url = f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
    params = {
        "symbol": sina,
        "scale": "240",  # 日K
        "ma": "no",
        "datalen": str(days),
    }
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=15)
        data = json.loads(r.text)
        if not data:
            return []
        results = []
        name = config.WATCHLIST.get(code, (code, ""))[0]
        for item in data:
            date = item["day"]
            open_, high, low, close = (
                float(item["open"]), float(item["high"]),
                float(item["low"]), float(item["close"])
            )
            vol = float(item.get("volume", 0))
            insert_stock(code, date, open_, high, low, close, vol, 0)
            results.append({
                "date": date, "open": open_, "close": close,
                "high": high, "low": low, "volume": vol, "name": name
            })
        return results
    except Exception as e:
        print(f"[ERROR] fetch_kline(sina) {code}: {e}")
        return []

def collect_all():
    """采集所有监控股票"""
    results = {}
    for i, (code, (name, sector)) in enumerate(config.WATCHLIST.items()):
        if i > 0:
            time.sleep(1)
        klines = fetch_kline(code, days=60)
        if klines:
            latest = klines[-1]
            results[code] = {
                "name": name, "sector": sector,
                "latest": latest, "count": len(klines),
            }
            print(f"  ✓ {name}({code}): {len(klines)}条, 最新收盘 {latest['close']}")
        else:
            print(f"  ✗ {name}({code}): 无数据")
    return results

if __name__ == "__main__":
    print("=== 测试实时行情 ===")
    rt = fetch_realtime("000960")
    print(json.dumps(rt, ensure_ascii=False, indent=2))

    print("\n=== 测试K线 ===")
    klines = fetch_kline("000960", days=5)
    for k in klines:
        print(f"  {k['date']}: 收盘 {k['close']}")
