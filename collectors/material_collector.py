"""
AI产业链监控 - 材料价格采集器
采集铜、锡、镍等AI产业链相关材料的价格和库存数据
数据源: 新浪财经期货API + SHFE库存
"""
import sys
import os
import requests
import json
import time
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db import insert_material_price, get_latest_materials, get_material_history

# ============================================================
# 材料配置
# ============================================================
MATERIAL_CONFIG = {
    "copper": {
        "name": "铜",
        "sina_code": "nf_CU0",  # 沪铜主力
        "unit": "元/吨",
        "stockpile_unit": "吨",
        "impact": "PCB/铜缆成本指标，铜价上涨→成本上升→利润承压",
        "related_sectors": ["PCB", "铜缆"],
    },
    "tin": {
        "name": "锡",
        "sina_code": "nf_SN0",  # 沪锡主力
        "unit": "元/吨",
        "stockpile_unit": "吨",
        "impact": "封装焊接材料，锡价上涨→封装成本上升",
        "related_sectors": ["封装"],
    },
    "nickel": {
        "name": "镍",
        "sina_code": "nf_NI0",  # 沪镍主力
        "unit": "元/吨",
        "stockpile_unit": "吨",
        "impact": "不锈钢/合金材料，镍价影响服务器机柜成本",
        "related_sectors": ["服务器"],
    },
    "aluminum": {
        "name": "铝",
        "sina_code": "nf_AL0",  # 沪铝主力
        "unit": "元/吨",
        "stockpile_unit": "吨",
        "impact": "散热材料，铝价影响液冷/散热器成本",
        "related_sectors": ["液冷"],
    },
}

# ============================================================
# 新浪期货API
# ============================================================
def fetch_futures_price(sina_code):
    """从新浪财经获取期货价格"""
    url = f"https://hq.sinajs.cn/list={sina_code}"
    try:
        r = requests.get(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://finance.sina.com.cn/",
        }, timeout=10)
        r.encoding = "gbk"
        text = r.text

        # 解析: var hq_str_nf_CU0="...,今开,昨收,最新,最高,最低,...";
        import re
        match = re.search(r'"([^"]+)"', text)
        if not match:
            return None

        parts = match.group(1).split(",")
        if len(parts) < 15:
            return None

        # 新浪期货格式: 名称,合约乘数(150000),今开,昨结,最高,最低,买1,卖1,...
        # parts[1]=150000 是合约乘数常量，不是价格
        name = parts[0]
        open_price = float(parts[2]) if parts[2] else 0
        prev_settle = float(parts[3]) if parts[3] else 0  # 昨结算
        high = float(parts[4]) if parts[4] else 0
        low = float(parts[5]) if parts[5] else 0

        # 用今开作为最新价（非交易时段），涨跌幅基于昨结算
        latest = open_price
        if prev_settle > 0 and latest > 0:
            change_pct = round((latest - prev_settle) / prev_settle * 100, 2)
        else:
            change_pct = 0

        return {
            "name": name,
            "price": latest,
            "open": open_price,
            "prev_close": prev_settle,
            "high": high,
            "low": low,
            "change_pct": change_pct,
        }
    except Exception as e:
        print(f"    [WARN] 期货价格获取失败 {sina_code}: {e}")
        return None


# ============================================================
# SHFE库存数据
# ============================================================
def fetch_shfe_stockpile(commodity):
    """从SHFE获取库存数据（复用inventory_collector的逻辑）"""
    try:
        from collectors.inventory_collector import get_inventory_trend
        trend = get_inventory_trend(commodity, weeks=2)
        if trend and len(trend) > 0:
            latest = trend[0]
            prev = trend[1] if len(trend) > 1 else None
            change_pct = 0
            if prev and prev.get("stockpile", 0) > 0:
                change_pct = round((latest["stockpile"] - prev["stockpile"]) / prev["stockpile"] * 100, 2)
            return {
                "stockpile": latest["stockpile"],
                "change_pct": change_pct,
            }
    except Exception:
        pass
    return None


# ============================================================
# AI影响分析
# ============================================================
def analyze_material_impact(material, price_data, stockpile_data):
    """分析材料价格变化对AI产业链的影响"""
    config = MATERIAL_CONFIG.get(material, {})
    name = config.get("name", material)
    related = config.get("related_sectors", [])
    impact_desc = config.get("impact", "")

    price_change = price_data.get("change_pct", 0)
    stockpile_change = stockpile_data.get("change_pct", 0) if stockpile_data else 0

    # 判断影响方向
    if price_change > 2 and stockpile_change < -5:
        # 价格涨+库存降 = 供需紧张
        direction = "bullish"
        reason = f"{name}供需紧张，价格上涨{price_change}%+库存下降{abs(stockpile_change)}%，{impact_desc}"
    elif price_change > 2:
        # 价格涨 = 成本上升
        direction = "bearish"
        reason = f"{name}价格上涨{price_change}%，{impact_desc}"
    elif price_change < -2 and stockpile_change > 5:
        # 价格跌+库存增 = 供需宽松
        direction = "bullish"
        reason = f"{name}价格下跌{abs(price_change)}%+库存上升{stockpile_change}%，成本下降利好{', '.join(related)}"
    elif price_change < -2:
        direction = "bullish"
        reason = f"{name}价格下跌{abs(price_change)}%，成本下降利好{', '.join(related)}"
    else:
        direction = "neutral"
        reason = f"{name}价格平稳，对{', '.join(related)}板块影响有限"

    return {
        "direction": direction,
        "reason": reason,
        "related_sectors": related,
    }


# ============================================================
# 综合采集
# ============================================================
def collect_all_materials():
    """采集所有材料价格和库存"""
    print("  === 材料价格采集 ===")
    results = []

    for material, config in MATERIAL_CONFIG.items():
        name = config["name"]
        sina_code = config["sina_code"]

        # 获取期货价格
        price_data = fetch_futures_price(sina_code)
        if not price_data or price_data["price"] <= 0:
            print(f"    {name}: 无数据")
            continue

        # 获取库存数据
        stockpile_data = fetch_shfe_stockpile(material)

        # AI影响分析
        impact = analyze_material_impact(material, price_data, stockpile_data)

        # 存入数据库
        insert_material_price(
            material=material,
            price=price_data["price"],
            unit=config["unit"],
            change_pct=price_data["change_pct"],
            stockpile=stockpile_data["stockpile"] if stockpile_data else None,
            stockpile_unit=config["stockpile_unit"],
            stockpile_change_pct=stockpile_data["change_pct"] if stockpile_data else None,
            source="sina_futures",
            ai_impact=json.dumps(impact, ensure_ascii=False),
        )

        result = {
            "material": material,
            "name": name,
            "price": price_data["price"],
            "unit": config["unit"],
            "change_pct": price_data["change_pct"],
            "stockpile": stockpile_data["stockpile"] if stockpile_data else None,
            "stockpile_unit": config["stockpile_unit"],
            "stockpile_change_pct": stockpile_data["change_pct"] if stockpile_data else None,
            "impact": impact,
        }
        results.append(result)

        icon = "+" if price_data["change_pct"] >= 0 else "-"
        print(f"    {name}: {price_data['price']:.0f}{config['unit']} ({icon}{abs(price_data['change_pct']):.1f}%)")

        time.sleep(0.5)

    print(f"  共采集 {len(results)} 种材料")
    return results


if __name__ == "__main__":
    from db import init_db
    init_db()
    results = collect_all_materials()
    for r in results:
        print(f"\n{r['name']}: {r['price']:.0f}{r['unit']} ({r['change_pct']:+.1f}%)")
        if r['stockpile']:
            print(f"  库存: {r['stockpile']:.0f}{r['stockpile_unit']} ({r['stockpile_change_pct']:+.1f}%)")
        print(f"  AI研判: {r['impact']['reason']}")
