"""
投行/机构级数据采集器 v2
已验证可用的数据源：
- ✅ 融资融券（东方财富datacenter API）
- ✅ 龙虎榜（东方财富datacenter API）
- ✅ 机构调研（东方财富datacenter API）
- ✅ 估值指标（腾讯财经API + 新浪行情API）
- ⚠️ 研报评级（东方财富datacenter API，可能为空）
- ⚠️ 北向资金（API字段变更，用实时接口）
- ✅ 大宗交易（东方财富datacenter API）
"""
import requests
import json
import time
import re
from datetime import datetime, timedelta
import sys
sys.path.insert(0, "/opt/ai-monitor")
import config

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://data.eastmoney.com/",
}

def _tencent_code(code):
    if code.startswith(("6", "9")):
        return f"sh{code}"
    return f"sz{code}"

# ============================================================
# 1. 估值指标（腾讯+新浪API，VPS直连可用）
# ============================================================
def fetch_valuation(code):
    """获取估值指标"""
    tc = _tencent_code(code)
    url = f"https://qt.gtimg.cn/q={tc}"
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        r.encoding = "gbk"
        parts = r.text.split("~")
        if len(parts) < 50:
            return {}
        def _f(idx, div=1):
            try:
                return round(float(parts[idx]) / div, 2)
            except (ValueError, IndexError):
                return None
        return {
            "code": code,
            "name": parts[1],
            "price": _f(3),
            "prev_close": _f(4),
            "open": _f(5),
            "volume": _f(6),              # 成交量(手)
            "amount": _f(37),              # 成交额(万)
            "high": _f(33),
            "low": _f(34),
            "change_pct": _f(32),
            "pe_ttm": _f(39),             # 市盈率TTM
            "pb": _f(46),                 # 市净率
            "total_mv": _f(45),            # 总市值(亿)
            "circ_mv": _f(44),             # 流通市值(亿)
            "turnover_rate": _f(38),       # 换手率
            "60day_change": _f(42),        # 60日涨跌幅
        }
    except Exception as e:
        print(f"[ERROR] fetch_valuation {code}: {e}")
        return {}

# ============================================================
# 2. 研报评级 & 目标价（东方财富datacenter）
# ============================================================
def fetch_analyst_ratings(code, limit=10):
    """获取个股研报评级"""
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    params = {
        "reportName": "RPT_CUSTOM_STOCK_RESEARCH",
        "columns": "ALL",
        "filter": f'(SECURITY_CODE="{code}")',
        "pageNumber": 1,
        "pageSize": limit,
        "sortColumns": "REPORT_DATE",
        "sortTypes": -1,
        "source": "WEB",
        "client": "WEB",
    }
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=15)
        data = r.json()
        if not data.get("result") or not data["result"].get("data"):
            return []
        results = []
        for item in data["result"]["data"]:
            results.append({
                "date": (item.get("REPORT_DATE") or "")[:10],
                "title": item.get("TITLE", ""),
                "org": item.get("ORG_NAME", ""),
                "author": item.get("RESEARCHER", ""),
                "rating": item.get("RATING_NAME", ""),
                "target_price": item.get("PREDICT_NEXT_TWO_EPS") or item.get("PREDICT_NEXT_EPS"),
                "industry": item.get("INDVNAME", ""),
            })
        return results
    except Exception as e:
        print(f"[ERROR] fetch_analyst_ratings {code}: {e}")
        return []

def fetch_consensus_estimate(code):
    """获取一致预期"""
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    params = {
        "reportName": "RPT_CUSTOM_STOCK_PREDICT",
        "columns": "ALL",
        "filter": f'(SECURITY_CODE="{code}")',
        "pageNumber": 1,
        "pageSize": 1,
        "sortColumns": "REPORT_DATE",
        "sortTypes": -1,
        "source": "WEB",
        "client": "WEB",
    }
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=15)
        data = r.json()
        if not data.get("result") or not data["result"].get("data"):
            return {}
        item = data["result"]["data"][0]
        return {
            "code": code,
            "eps_current": item.get("PREDICT_NEXT_EPS"),
            "eps_next": item.get("PREDICT_NEXT_TWO_EPS"),
            "pe_current": item.get("PREDICT_PE_CURRENT"),
            "pe_next": item.get("PREDICT_PE_NEXT"),
            "revenue": item.get("PREDICT_REVENUE_CURRENT"),
            "profit": item.get("PREDICT_NETPROFIT_CURRENT"),
            "rating_count": item.get("RATING_COUNT"),
        }
    except Exception as e:
        print(f"[ERROR] fetch_consensus_estimate {code}: {e}")
        return {}

# ============================================================
# 3. 融资融券（已验证可用）
# ============================================================
def fetch_margin_trading(code, days=10):
    """获取个股融资融券数据"""
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    params = {
        "reportName": "RPTA_WEB_RZRQ_GGMX",
        "columns": "ALL",
        "filter": f'(SCODE="{code}")',
        "pageNumber": 1,
        "pageSize": days,
        "sortColumns": "DATE",
        "sortTypes": -1,
        "source": "WEB",
        "client": "WEB",
    }
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=15)
        data = r.json()
        if not data.get("result") or not data["result"].get("data"):
            return []
        results = []
        for item in data["result"]["data"]:
            rz_balance = item.get("RZYE", 0)
            rq_balance = item.get("RQYE", 0)
            results.append({
                "date": (item.get("DATE") or "")[:10],
                "rz_balance": rz_balance,
                "rq_balance": rq_balance,
                "rz_balance_yi": round(rz_balance / 1e8, 2) if rz_balance else 0,
            })
        return results
    except Exception as e:
        print(f"[ERROR] fetch_margin_trading {code}: {e}")
        return []

# ============================================================
# 4. 龙虎榜（已验证可用）
# ============================================================
def fetch_dragon_tiger(days=5):
    """获取龙虎榜数据"""
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    params = {
        "reportName": "RPT_DAILYBILLBOARD_DETAILSNEW",
        "columns": "SECURITY_CODE,SECURITY_NAME_ABBR,TRADE_DATE,CLOSE_PRICE,CHANGE_RATE,BILLBOARD_NET_AMT,BILLBOARD_BUY_AMT,BILLBOARD_SELL_AMT,EXPLAIN",
        "filter": f'(TRADE_DATE>\'{cutoff}\')',
        "pageNumber": 1,
        "pageSize": 50,
        "sortColumns": "TRADE_DATE,SECURITY_CODE",
        "sortTypes": "-1,1",
        "source": "WEB",
        "client": "WEB",
    }
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=15)
        data = r.json()
        if not data.get("result") or not data["result"].get("data"):
            return []
        results = []
        for item in data["result"]["data"]:
            net = item.get("BILLBOARD_NET_AMT", 0) or 0
            results.append({
                "code": item.get("SECURITY_CODE", ""),
                "name": item.get("SECURITY_NAME_ABBR", ""),
                "date": (item.get("TRADE_DATE") or "")[:10],
                "close": item.get("CLOSE_PRICE", 0),
                "change_pct": item.get("CHANGE_RATE", 0),
                "net_buy": net,
                "net_buy_yi": round(net / 1e8, 2) if net else 0,
                "reason": item.get("EXPLAIN", ""),
            })
        return results
    except Exception as e:
        print(f"[ERROR] fetch_dragon_tiger: {e}")
        return []

# ============================================================
# 5. 机构调研（已验证可用）
# ============================================================
def fetch_institutional_visits(code, limit=10):
    """获取机构调研记录"""
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    params = {
        "reportName": "RPT_ORG_SURVEYNEW",
        "columns": "ALL",
        "filter": f'(SECURITY_CODE="{code}")',
        "pageNumber": 1,
        "pageSize": limit,
        "sortColumns": "NOTICE_DATE",
        "sortTypes": -1,
        "source": "WEB",
        "client": "WEB",
    }
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=15)
        data = r.json()
        if not data.get("result") or not data["result"].get("data"):
            return []
        results = []
        for item in data["result"]["data"]:
            results.append({
                "date": (item.get("NOTICE_DATE") or "")[:10],
                "org_count": item.get("ORG_NUM", 0),
                "orgs": (item.get("ORG_NAME") or "")[:100],
                "summary": (item.get("QUESTIONCONTENT") or "")[:200],
            })
        return results
    except Exception as e:
        print(f"[ERROR] fetch_institutional_visits {code}: {e}")
        return []

# ============================================================
# 6. 大宗交易（已验证可用）
# ============================================================
def fetch_block_trades(code=None, days=7):
    """获取大宗交易数据"""
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    filter_str = f'(TRADE_DATE>\'{cutoff}\')'
    if code:
        filter_str += f'(SECURITY_CODE="{code}")'
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    params = {
        "reportName": "RPT_DATA_BLOCKTRADE",
        "columns": "ALL",
        "filter": filter_str,
        "pageNumber": 1,
        "pageSize": 50,
        "sortColumns": "TRADE_DATE",
        "sortTypes": -1,
        "source": "WEB",
        "client": "WEB",
    }
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=15)
        data = r.json()
        if not data.get("result") or not data["result"].get("data"):
            return []
        results = []
        for item in data["result"]["data"]:
            amt = item.get("DEAL_AMT", 0) or 0
            results.append({
                "code": item.get("SECURITY_CODE", ""),
                "name": item.get("SECURITY_NAME_ABBR", ""),
                "date": (item.get("TRADE_DATE") or "")[:10],
                "price": item.get("DEAL_PRICE", 0),
                "amount": amt,
                "amount_yi": round(amt / 1e8, 2) if amt else 0,
                "premium": item.get("PREMIUM_RATIO", 0),
                "buyer": (item.get("BUYER_NAME") or "")[:30],
                "seller": (item.get("SELLER_NAME") or "")[:30],
            })
        return results
    except Exception as e:
        print(f"[ERROR] fetch_block_trades: {e}")
        return []

# ============================================================
# 7. 北向资金（实时接口）
# ============================================================
def fetch_northbound_realtime():
    """获取北向资金实时净流入"""
    url = "https://push2.eastmoney.com/api/qt/kamt.rtmin/get"
    params = {
        "fields1": "f1,f2,f3,f4",
        "fields2": "f51,f52,f53,f54,f55,f56",
        "ut": "b2884a393a59ad64002292a3e90d46a5",
    }
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=10)
        data = r.json().get("data", {})
        # s2n = 沪股通净流入, n2s = 南向净流入
        s2n = data.get("s2n", [])
        s2s = data.get("s2s", [])
        # 取最后一个有效数据点
        hgt_net = 0  # 沪股通
        sgt_net = 0  # 深股通
        for item in reversed(s2n):
            parts = item.split(",")
            if len(parts) >= 2 and parts[1] != "-" and float(parts[1]) != 0:
                hgt_net = float(parts[1])
                break
        for item in reversed(s2s):
            parts = item.split(",")
            if len(parts) >= 2 and parts[1] != "-" and float(parts[1]) != 0:
                sgt_net = float(parts[1])
                break
        return {
            "date": data.get("s2nDate", ""),
            "hgt_net": hgt_net,         # 沪股通净流入(万元)
            "sgt_net": sgt_net,         # 深股通净流入(万元)
            "total_net": hgt_net + sgt_net,
            "total_net_yi": round((hgt_net + sgt_net) / 10000, 2),
        }
    except Exception as e:
        print(f"[ERROR] fetch_northbound_realtime: {e}")
        return {}

# ============================================================
# 综合采集
# ============================================================
def collect_institutional(code, name=""):
    """采集单只股票的全部机构数据"""
    result = {
        "code": code,
        "name": name or config.WATCHLIST.get(code, (code, ""))[0],
        "val": {},
        "ratings": [],
        "consensus": {},
        "margin": [],
        "visits": [],
    }
    result["val"] = fetch_valuation(code)
    time.sleep(0.3)
    result["ratings"] = fetch_analyst_ratings(code, limit=5)
    time.sleep(0.3)
    result["consensus"] = fetch_consensus_estimate(code)
    time.sleep(0.3)
    result["margin"] = fetch_margin_trading(code, days=5)
    time.sleep(0.3)
    result["visits"] = fetch_institutional_visits(code, limit=3)
    return result

def collect_all_institutional():
    """采集所有监控标的的机构数据"""
    results = {}
    for i, (code, (name, sector)) in enumerate(config.WATCHLIST.items()):
        if i > 0:
            time.sleep(1)
        print(f"  采集 {name}({code})...")
        r = collect_institutional(code, name)
        results[code] = r
        val = r["val"]
        if val:
            pe = val.get("pe_ttm", "N/A")
            pb = val.get("pb", "N/A")
            mv = val.get("total_mv", 0)
            mv_str = f"{mv}亿" if mv else "N/A"
            print(f"    PE:{pe} PB:{pb} 市值:{mv_str}")
    return results

def collect_global_institutional():
    """采集全局机构数据"""
    data = {}
    print("  采集北向资金...")
    data["northbound"] = fetch_northbound_realtime()
    time.sleep(0.5)
    print("  采集龙虎榜...")
    data["dragon_tiger"] = fetch_dragon_tiger(days=5)
    time.sleep(0.5)
    print("  采集大宗交易...")
    data["block_trades"] = fetch_block_trades(days=7)
    return data

if __name__ == "__main__":
    print("=== 测试: 锡业股份(000960) ===")
    r = collect_institutional("000960", "锡业股份")
    val = r["val"]
    if val:
        print(f"  PE(TTM): {val.get('pe_ttm')}  PB: {val.get('pb')}  市值: {val.get('total_mv')}亿")
        print(f"  换手率: {val.get('turnover_rate')}%  60日涨跌: {val.get('60day_change')}%")
    if r["margin"]:
        m = r["margin"][0]
        print(f"  融资余额: {m['rz_balance_yi']}亿 ({m['date']})")
    if r["visits"]:
        v = r["visits"][0]
        print(f"  最近调研: {v['date']} ({v['org_count']}家机构)")

    print("\n=== 测试: 龙虎榜 ===")
    dt = fetch_dragon_tiger(5)
    for d in dt[:5]:
        icon = "🟢" if d["net_buy"] > 0 else "🔴"
        print(f"  {icon} {d['name']}({d['code']}) 净买:{d['net_buy_yi']}亿 原因:{d['reason'][:30]}")

    print("\n=== 测试: 北向资金 ===")
    nb = fetch_northbound_realtime()
    if nb:
        print(f"  沪股通: {nb['hgt_net']}万  深股通: {nb['sgt_net']}万  合计: {nb['total_net_yi']}亿")
