"""
库存数据采集器 - 多源策略
1. SHFE官网（VPS可能被WAF拦截，作为首选尝试）
2. 手动输入（用户通过命令行录入）
3. 新闻提取（从财经新闻中提取库存数据）
"""
import requests
import json
import re
from datetime import datetime, timedelta
import sys
sys.path.insert(0, "/opt/ai-monitor")
from db import insert_inventory, get_inventory_history

# SHFE被WAF拦截时的替代方案
# 用户可以通过命令手动录入: python manage.py inventory --tin 4500 --copper 35000

def fetch_shfe_warehouse(date_str=None):
    """尝试从上期所获取仓单数据"""
    if date_str is None:
        for i in range(7):
            d = datetime.now() - timedelta(days=i)
            if d.weekday() < 5:
                date_str = d.strftime("%Y%m%d")
                result = _fetch_single_date(date_str)
                if result:
                    return result
        return {}
    return _fetch_single_date(date_str)

def _fetch_single_date(date_str):
    url = f"https://www.shfe.com.cn/data/dailydata/kx/kx{date_str}.dat"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.shfe.com.cn/statements/dataview.html",
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json",
    }
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code != 200 or "<html" in r.text[:100].lower():
            return {}
        data = r.json()
        if not data.get("o_cursor"):
            return {}
        results = {}
        for item in data["o_cursor"]:
            product = item.get("VARNAME", "").strip()
            stockpile = item.get("WRTWGHTS", 0)
            if "锡" in product and "锡精矿" not in product:
                results["tin"] = {"commodity": "tin", "product": product,
                                  "stockpile": float(stockpile or 0), "date": date_str, "unit": "吨"}
            elif "铜" in product and "铜精矿" not in product:
                results["copper"] = {"commodity": "copper", "product": product,
                                     "stockpile": float(stockpile or 0), "date": date_str, "unit": "吨"}
        return results
    except Exception as e:
        print(f"[ERROR] SHFE fetch: {e}")
        return {}

def manual_inventory(tin=None, copper=None, date_str=None):
    """手动录入库存数据"""
    if date_str is None:
        date_str = datetime.now().strftime("%Y%m%d")
    results = {}
    if tin is not None:
        history = get_inventory_history("tin", weeks=1)
        change = tin - history[0]["stockpile"] if history else 0
        insert_inventory("tin", date_str, tin, change, "manual")
        results["tin"] = {"stockpile": tin, "change": change}
        print(f"  ✓ 锡库存: {tin}吨 (变化 {'+' if change >= 0 else ''}{change:.0f})")
    if copper is not None:
        history = get_inventory_history("copper", weeks=1)
        change = copper - history[0]["stockpile"] if history else 0
        insert_inventory("copper", date_str, copper, change, "manual")
        results["copper"] = {"stockpile": copper, "change": change}
        print(f"  ✓ 铜库存: {copper}吨 (变化 {'+' if change >= 0 else ''}{change:.0f})")
    return results

def collect_inventory():
    """采集库存数据（自动尝试 + 记录状态）"""
    print("  采集上期所仓单数据...")
    data = fetch_shfe_warehouse()
    if not data:
        print("  ⚠ SHFE数据不可用（可能被WAF拦截或非交易日）")
        print("  提示: 手动录入 → python manage.py inventory --tin 4500")
        return {}
    for commodity, info in data.items():
        history = get_inventory_history(commodity, weeks=1)
        change = info["stockpile"] - history[0]["stockpile"] if history else 0
        insert_inventory(commodity, info["date"], info["stockpile"], change, "SHFE")
        print(f"  ✓ {info['product']}: {info['stockpile']}{info['unit']}"
              f" (较上次 {'+' if change >= 0 else ''}{change:.0f})")
    return data

def get_inventory_trend(commodity, weeks=5):
    """获取库存趋势"""
    history = get_inventory_history(commodity, weeks=weeks)
    if len(history) < 2:
        return {"trend": "unknown", "latest": history[0]["stockpile"] if history else 0,
                "change_total": 0, "weeks": len(history), "data": history}
    values = [h["stockpile"] for h in history]
    declining = all(values[i] > values[i+1] for i in range(len(values)-1))
    rising = all(values[i] < values[i+1] for i in range(len(values)-1))
    trend = "declining" if declining else ("rising" if rising else "mixed")
    return {"trend": trend, "latest": values[0], "change_total": values[0] - values[-1],
            "weeks": len(values), "data": history}

if __name__ == "__main__":
    print("=== 采集库存数据 ===")
    collect_inventory()
