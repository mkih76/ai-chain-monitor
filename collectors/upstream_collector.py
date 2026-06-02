"""
上游产业数据采集器
领先指标: TSMC月营收、LME铜锡库存、DRAM/NAND价格、半导体设备BB Ratio
这些数据领先A股相关板块3-6个月，是"提前布局"的核心数据源
"""
import requests
import json
import re
import time
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import sys
sys.path.insert(0, "/opt/ai-monitor")
from db import insert_upstream, get_upstream_latest
import config

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
}

# ============================================================
# 1. TSMC月度营收 (台积电IR官网)
#    每月10日前公布上月营收，领先封测/光模块3-6个月
# ============================================================
def fetch_tsmc_revenue():
    """从台积电IR页面抓取月度营收数据"""
    print("  采集TSMC月度营收...")
    url = "https://investor.tsmc.com/english/quarterly-results"
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        if r.status_code != 200:
            print(f"  ⚠ TSMC页面返回 {r.status_code}")
            return []

        # 尝试从页面中提取营收数据链接
        soup = BeautifulSoup(r.text, "lxml")
        results = []

        # 查找月度营收表格或链接
        # TSMC IR页面通常有Revenue by Month的表格
        tables = soup.find_all("table")
        for table in tables:
            rows = table.find_all("tr")
            for row in rows:
                cells = row.find_all(["td", "th"])
                text = " ".join(c.get_text(strip=True) for c in cells)
                # 匹配类似 "Jan. 2026  293,248" 的格式
                match = re.search(r'(\w+\.?\s*\d{4})\s+([\d,]+)', text)
                if match:
                    period_str = match.group(1).strip()
                    revenue_str = match.group(2).replace(",", "")
                    try:
                        revenue = float(revenue_str)
                        # 解析日期
                        for fmt in ["%b. %Y", "%b %Y", "%B %Y"]:
                            try:
                                dt = datetime.strptime(period_str, fmt)
                                date_str = dt.strftime("%Y-%m")
                                results.append({
                                    "source": "tsmc",
                                    "date": date_str,
                                    "metric": "monthly_revenue_twd_mn",
                                    "value": revenue,
                                    "unit": "TWD百万",
                                })
                                break
                            except ValueError:
                                continue
                    except ValueError:
                        continue

        # 如果页面结构变了，尝试备用API
        if not results:
            results = _fetch_tsmc_revenue_fallback()

        # 计算YoY和MoM变化
        results = _calculate_changes(results, "tsmc", "monthly_revenue_twd_mn")

        for r in results:
            yoy_str = f" YoY:{r.get('yoy', 0):+.1f}%" if r.get("yoy") else ""
            mom_str = f" MoM:{r.get('mom', 0):+.1f}%" if r.get("mom") else ""
            print(f"    {r['date']}: {r['value']:,.0f} TWD mn{yoy_str}{mom_str}")

        return results

    except Exception as e:
        print(f"  [ERROR] TSMC营收采集失败: {e}")
        return []

def _fetch_tsmc_revenue_fallback():
    """备用: 从财经数据聚合站获取TSMC营收"""
    results = []
    try:
        # 尝试从macromicro等数据站获取
        url = "https://api.macromicro.me/charts/42364/tsmc-monthly-revenue"
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code == 200:
            data = r.json()
            if "data" in data:
                for item in data["data"][-12:]:  # 最近12个月
                    results.append({
                        "source": "tsmc",
                        "date": item.get("date", "")[:7],
                        "metric": "monthly_revenue_twd_mn",
                        "value": float(item.get("value", 0)),
                        "unit": "TWD百万",
                    })
    except Exception:
        pass
    return results

# ============================================================
# 2. LME铜锡库存 (伦敦金属交易所)
#    全球供需指标，与SHFE库存互补
# ============================================================
def fetch_lme_inventory():
    """采集LME铜锡库存数据"""
    print("  采集LME库存数据...")
    results = []

    # LME数据通常需要通过数据聚合站获取
    # 尝试从Trading Economics等免费源
    commodities = {
        "copper": {"name": "铜", "keywords": ["copper", "LME铜"]},
        "tin": {"name": "锡", "keywords": ["tin", "LME锡"]},
    }

    for commodity, info in commodities.items():
        try:
            data = _fetch_trading_economics_inventory(commodity)
            if data:
                results.extend(data)
                if data:
                    latest = data[-1]
                    print(f"    LME {info['name']}: {latest['value']:,.0f} 吨 ({latest['date']})")
        except Exception as e:
            print(f"    ⚠ LME {info['name']} 采集失败: {e}")
        time.sleep(1)

    return results

def _fetch_trading_economics_inventory(commodity):
    """从Trading Economics获取LME库存"""
    url_map = {
        "copper": "https://api.tradingeconomics.com/markets/commodity/copper-stocks",
        "tin": "https://api.tradingeconomics.com/markets/commodity/tin-stocks",
    }
    url = url_map.get(commodity)
    if not url:
        return []

    results = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list) and len(data) > 0:
                item = data[0]
                date_str = (item.get("date", "") or "")[:10]
                value = float(item.get("value", 0) or 0)
                if value > 0:
                    # 计算变化
                    prev = get_upstream_latest("lme", f"{commodity}_stocks", limit=1)
                    prev_val = prev[0]["value"] if prev else None
                    yoy = ((value - prev_val) / prev_val * 100) if prev_val and prev_val > 0 else None
                    results.append({
                        "source": "lme",
                        "date": date_str,
                        "metric": f"{commodity}_stocks",
                        "value": value,
                        "unit": "吨",
                        "yoy": yoy,
                    })
    except Exception:
        pass
    return results

# ============================================================
# 3. DRAM/NAND现货价格 (存储芯片价格风向标)
#    领先服务器板块2-4周
# ============================================================
def fetch_dram_nand_price():
    """采集DRAM/NAND现货价格"""
    print("  采集存储芯片价格...")
    results = []

    try:
        # 从TrendForce新闻中提取价格信息
        url = "https://www.trendforce.com/presscenter"
        r = requests.get(url, headers=HEADERS, timeout=20)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "lxml")
            articles = soup.find_all("div", class_="panel-text")
            for article in articles[:10]:
                text = article.get_text(strip=True)
                if any(kw in text for kw in ["DRAM", "NAND", "memory", "存储"]):
                    # 提取价格变动信息
                    price_info = _extract_price_from_text(text)
                    if price_info:
                        results.append(price_info)
    except Exception as e:
        print(f"    ⚠ TrendForce采集失败: {e}")

    # 备用: 从DRAMeXchange/行业媒体获取
    if not results:
        results = _fetch_dram_price_fallback()

    for r in results:
        print(f"    {r['metric']}: {r['value']} {r['unit']} ({r['date']})")

    return results

def _extract_price_from_text(text):
    """从文本中提取价格信息"""
    # 匹配类似 "DDR4 8Gb price rose to $1.85" 的模式
    patterns = [
        r'(DDR\w)\s+(\d+Gb)\s+.*?(\$[\d.]+)',
        r'(NAND\s*\d+).*?(\$[\d.]+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return {
                "source": "dram_market",
                "date": datetime.now().strftime("%Y-%m-%d"),
                "metric": f"{match.group(1)}_{match.group(2) if len(match.groups()) > 1 else ''}",
                "value": float(match.group(-1).replace("$", "")),
                "unit": "USD",
            }
    return None

def _fetch_dram_price_fallback():
    """备用DRAM价格采集"""
    results = []
    try:
        # 从行业新闻聚合获取
        url = "https://searchapi.eastmoney.com/bussiness/Web/GetCMSSearchList"
        params = {
            "type": "8193",
            "keyword": "DRAM价格",
            "pageIndex": 1,
            "pageSize": 5,
        }
        r = requests.get(url, params=params, headers=HEADERS, timeout=10)
        if r.status_code == 200:
            data = r.json()
            items = data.get("Data", []) or data.get("data", []) or []
            if isinstance(items, dict):
                items = items.get("List", []) or items.get("list", []) or []
            for item in items[:3]:
                title = item.get("Title", "") or item.get("title", "")
                date = (item.get("Date", "") or item.get("date", ""))[:10]
                if "涨" in title or "跌" in title:
                    direction = "up" if "涨" in title else "down"
                    results.append({
                        "source": "news_dram",
                        "date": date,
                        "metric": "dram_sentiment",
                        "value": 1 if direction == "up" else -1,
                        "unit": "sentiment",
                    })
    except Exception:
        pass
    return results

# ============================================================
# 4. 半导体设备BB Ratio (SEMI)
#    BB>1 → 未来产能扩张，利好上游材料
# ============================================================
def fetch_semi_bb_ratio():
    """采集SEMI半导体设备BB Ratio"""
    print("  采集SEMI设备BB Ratio...")
    results = []

    try:
        # 从SEMI或数据聚合站获取
        url = "https://searchapi.eastmoney.com/bussiness/Web/GetCMSSearchList"
        params = {
            "type": "8193",
            "keyword": "半导体设备出货额",
            "pageIndex": 1,
            "pageSize": 5,
        }
        r = requests.get(url, params=params, headers=HEADERS, timeout=10)
        if r.status_code == 200:
            data = r.json()
            items = data.get("Data", []) or data.get("data", []) or []
            if isinstance(items, dict):
                items = items.get("List", []) or items.get("list", []) or []
            for item in items[:3]:
                title = item.get("Title", "") or item.get("title", "")
                date = (item.get("Date", "") or item.get("date", ""))[:10]
                # 提取数字
                num_match = re.search(r'(\d+\.?\d*)\s*(亿|百万|%)', title)
                if num_match:
                    results.append({
                        "source": "semi",
                        "date": date,
                        "metric": "equipment_billings",
                        "value": float(num_match.group(1)),
                        "unit": num_match.group(2),
                    })
    except Exception as e:
        print(f"    ⚠ SEMI数据采集失败: {e}")

    return results

# ============================================================
# 辅助函数
# ============================================================
def _calculate_changes(data, source, metric):
    """计算YoY和MoM变化"""
    if len(data) < 2:
        return data

    # 按日期排序
    data.sort(key=lambda x: x["date"])

    for i, item in enumerate(data):
        # MoM: 与上一期比较
        if i > 0:
            prev_val = data[i-1]["value"]
            if prev_val > 0:
                item["mom"] = round((item["value"] - prev_val) / prev_val * 100, 2)

        # YoY: 与去年同期比较
        try:
            current_date = datetime.strptime(item["date"], "%Y-%m")
            yoy_date = current_date - timedelta(days=365)
            yoy_str = yoy_date.strftime("%Y-%m")
            yoy_item = next((d for d in data if d["date"] == yoy_str), None)
            if yoy_item and yoy_item["value"] > 0:
                item["yoy"] = round((item["value"] - yoy_item["value"]) / yoy_item["value"] * 100, 2)
        except (ValueError, StopIteration):
            pass

    return data

# ============================================================
# 综合采集
# ============================================================
def collect_upstream_data():
    """采集所有上游产业数据"""
    print("  === 采集上游产业数据 ===")
    all_data = []

    # TSMC月营收
    tsmc_data = fetch_tsmc_revenue()
    for d in tsmc_data:
        insert_upstream(d["source"], d["date"], d["metric"], d["value"],
                       d.get("unit", ""), d.get("yoy"), d.get("mom"))
    all_data.extend(tsmc_data)
    time.sleep(2)

    # LME库存
    lme_data = fetch_lme_inventory()
    for d in lme_data:
        insert_upstream(d["source"], d["date"], d["metric"], d["value"],
                       d.get("unit", ""), d.get("yoy"))
    all_data.extend(lme_data)
    time.sleep(1)

    # DRAM/NAND价格
    dram_data = fetch_dram_nand_price()
    for d in dram_data:
        insert_upstream(d["source"], d["date"], d["metric"], d["value"], d.get("unit", ""))
    all_data.extend(dram_data)
    time.sleep(1)

    # SEMI BB Ratio
    semi_data = fetch_semi_bb_ratio()
    for d in semi_data:
        insert_upstream(d["source"], d["date"], d["metric"], d["value"], d.get("unit", ""))
    all_data.extend(semi_data)

    print(f"  上游数据采集完成: {len(all_data)}条")
    return all_data

if __name__ == "__main__":
    from db import init_db
    init_db()
    data = collect_upstream_data()
    print(f"\n共采集 {len(data)} 条上游数据")
