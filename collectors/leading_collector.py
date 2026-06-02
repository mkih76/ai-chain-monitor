"""
AI产业链监控 - 先行指标采集器
核心逻辑: 检测"央视报道之前"的信号
  1. 板块资金流向 (聪明钱先动)
  2. 概念板块异动 (新概念热度飙升)
  3. 政策文件发布 (从文件到新闻有时间差)
  4. 社交媒体情绪突变 (散户讨论激增领先价格1-3天)
  5. 期货/商品价格动量 (库存下降→价格滞后上涨)
"""
import sys
import os
import re
import json
import requests
from datetime import datetime, timedelta
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ============================================================
# 1. 板块资金流向 — 检测聪明钱轮动
# ============================================================
def fetch_sector_fund_flow():
    """
    从东方财富获取板块资金流向
    当某板块连续N天净流入，且流入金额递增 → 先行信号
    返回: [{name, change_pct, net_flow_3d, net_flow_5d, trend}]
    """
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    results = []

    # 行业板块资金流
    params = {
        "pn": 1, "pz": 50,
        "po": 1,  # 按净流入降序
        "np": 1, "fltt": 2,
        "invt": 2, "fid": "f62",  # f62=主力净流入
        "fs": "m:90+t:2",  # 行业板块
        "fields": "f12,f14,f3,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87",
        # f12=代码 f14=名称 f3=涨跌幅 f62=主力净流入
        # f184=主力净占比 f66=超大单净流入 f72=大单净流入 f78=中单净流入 f84=小单净流入
    }
    try:
        r = requests.get(url, params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        data = r.json()
        items = data.get("data", {}).get("diff", [])
        for item in items:
            name = item.get("f14", "")
            net_flow = item.get("f62", 0)  # 主力净流入(元)
            net_flow_ratio = item.get("f184", 0)  # 主力净占比(%)
            change_pct = item.get("f3", 0)
            results.append({
                "name": name,
                "change_pct": change_pct,
                "net_flow": net_flow,
                "net_flow_yi": round(net_flow / 1e8, 2) if net_flow else 0,  # 转为亿
                "net_flow_ratio": net_flow_ratio,
                "super_large_flow": item.get("f66", 0),  # 超大单
                "large_flow": item.get("f72", 0),        # 大单
            })
    except Exception as e:
        print(f"  ⚠ 板块资金流获取失败: {e}")

    return results


def fetch_concept_boards():
    """
    从东方财富获取概念板块涨跌
    新兴概念(如CoWoS、HBM、硅光)在成为主流新闻前，概念板块已经开始异动
    返回: [{name, change_pct, leading_stock, rise_count, fall_count}]
    """
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    results = []

    params = {
        "pn": 1, "pz": 80,
        "po": 1,
        "np": 1, "fltt": 2,
        "invt": 2, "fid": "f3",
        "fs": "m:90+t:3",  # 概念板块
        "fields": "f12,f14,f3,f8,f104,f105,f128,f136,f140,f141",
        # f3=涨跌幅 f8=换手率 f104=涨家数 f105=跌家数
        # f128=领涨股 f136=领涨股涨幅 f140=领涨股代码 f141=领涨股名称
    }
    try:
        r = requests.get(url, params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        data = r.json()
        items = data.get("data", {}).get("diff", [])
        for item in items:
            results.append({
                "name": item.get("f14", ""),
                "change_pct": item.get("f3", 0),
                "turnover_rate": item.get("f8", 0),
                "rise_count": item.get("f104", 0),
                "fall_count": item.get("f105", 0),
                "leading_stock": item.get("f141", ""),
                "leading_stock_code": item.get("f140", ""),
                "leading_stock_change": item.get("f136", 0),
            })
    except Exception as e:
        print(f"  ⚠ 概念板块获取失败: {e}")

    return results


# ============================================================
# 2. 政策文件扫描 — 从政府网站检测政策信号
# ============================================================
def fetch_policy_documents():
    """
    扫描国务院/工信部/发改委政策文件
    政策利好从发布到央视报道通常有1-3天时间差
    返回: [{source, title, url, date, keywords, relevance}]
    """
    documents = []

    # 来源1: 国务院政策 (gov.cn)
    gov_sources = [
        {
            "name": "国务院",
            "url": "https://www.gov.cn/zhengce/zuixin/",
            "pattern": r'<li[^>]*>.*?<a[^>]*href="([^"]*)"[^>]*>([^<]*)</a>.*?<span[^>]*>([^<]*)</span>.*?</li>',
        },
    ]

    # 来源2: 工信部 (miit.gov.cn)
    miit_url = "https://www.miit.gov.cn/zwgk/zcwj/wjfb/index.html"

    # 来源3: 东方财富-产业政策新闻 (更可靠的API)
    try:
        url = "https://searchapi.eastmoney.com/bussiness/Web/GetCMSSearchList"
        policy_keywords = [
            "芯片政策", "半导体补贴", "算力基建", "数据中心政策",
            "人工智能政策", "集成电路", "新能源政策", "新材料政策",
        ]
        for kw in policy_keywords[:4]:  # 限制请求数
            params = {
                "type": "8197",  # 资讯
                "keyword": kw,
                "pageIndex": 1,
                "pageSize": 5,
            }
            try:
                r = requests.get(url, params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
                data = r.json()
                items = data.get("Data", []) or data.get("data", []) or []
                if isinstance(items, dict):
                    items = items.get("List", []) or items.get("list", []) or []
                for item in items[:3]:
                    title = item.get("Title", "") or item.get("title", "")
                    date = item.get("Date", "") or item.get("date", "")
                    content_url = item.get("Url", "") or item.get("url", "")
                    # 只保留政府/政策相关
                    if any(kw in title for kw in ["政策", "补贴", "规划", "意见", "通知", "方案", "发改委", "工信部", "国务院"]):
                        documents.append({
                            "source": "政策",
                            "title": title,
                            "url": content_url,
                            "date": date[:10] if date else "",
                            "keywords": kw,
                        })
            except Exception:
                pass
    except Exception as e:
        print(f"  ⚠ 政策文件扫描失败: {e}")

    return documents


# ============================================================
# 3. 社交媒体情绪监控 — 检测散户讨论热度突变
# ============================================================
def fetch_guba_heat():
    """
    从东方财富股吧获取热门帖子
    当某股票股吧发帖量突然暴增 → 往往领先价格1-3天
    返回: [{code, name, post_count, hot_posts}]
    """
    results = []

    # 监控标的的股吧
    from config import WATCHLIST
    for code, (name, sector) in list(WATCHLIST.items())[:8]:  # 限制请求数
        try:
            # 东方财富股吧API
            url = f"https://guba.eastmoney.com/interface/GetData.aspx"
            params = {
                "path": "dy/topiclist",
                "param": f"code={code}&ps=10&p=1",
            }
            # 备用: 直接获取股吧首页帖子数
            url2 = f"https://guba.eastmoney.com/list,{code}.html"
            r = requests.get(url2, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "text/html",
            }, timeout=10)

            if r.status_code == 200:
                html = r.text
                # 统计帖子数量（粗略）
                post_count = len(re.findall(r'class="listitem"', html))
                # 提取热门帖子标题
                titles = re.findall(r'class="l3[^"]*"[^>]*><a[^>]*>([^<]+)</a>', html)
                hot_posts = [t.strip() for t in titles[:5] if t.strip() and len(t.strip()) > 4]

                results.append({
                    "code": code,
                    "name": name,
                    "sector": sector,
                    "post_count": post_count,
                    "hot_posts": hot_posts,
                })
        except Exception:
            pass

    return results


def detect_sentiment_spike(guba_data, historical_avg=None):
    """
    检测情绪突变: 当前发帖量 vs 历史均值
    如果发帖量 > 历史均值 * 2 → 情绪突变信号
    """
    signals = []
    for item in guba_data:
        post_count = item.get("post_count", 0)
        # 如果没有历史数据，用经验值判断
        if post_count > 30:  # 个股股吧单页通常15-20条，超过30条说明热度高
            signals.append({
                "type": "sentiment_spike",
                "code": item["code"],
                "name": item["name"],
                "sector": item["sector"],
                "post_count": post_count,
                "hot_posts": item.get("hot_posts", []),
                "severity": "high" if post_count > 50 else "medium",
            })
    return signals


# ============================================================
# 4. 商品价格动量 — 库存下降→价格滞后上涨
# ============================================================
def fetch_commodity_momentum():
    """
    从多个来源获取商品价格动量数据
    库存连续下降 + 价格开始企稳 = 即将上涨的先行信号
    """
    from db import get_conn, init_db
    init_db()
    conn = get_conn()

    results = []
    commodities = ["tin", "copper"]

    for commodity in commodities:
        # 获取库存趋势
        rows = conn.execute(
            """SELECT date, stockpile, change FROM inventory
               WHERE commodity=? ORDER BY date DESC LIMIT 10""",
            (commodity,)
        ).fetchall()

        if len(rows) < 3:
            continue

        rows = [dict(r) for r in rows]

        # 计算库存变化趋势
        recent_3 = rows[:3]
        decline_weeks = 0
        total_change = 0
        for r in recent_3:
            if r["change"] and r["change"] < 0:
                decline_weeks += 1
                total_change += r["change"]

        # 库存绝对水平
        current_stockpile = rows[0]["stockpile"]
        avg_stockpile = sum(r["stockpile"] for r in rows) / len(rows)

        results.append({
            "commodity": commodity,
            "current_stockpile": current_stockpile,
            "avg_stockpile": round(avg_stockpile, 0),
            "decline_weeks": decline_weeks,
            "total_change": round(total_change, 0),
            "below_avg": current_stockpile < avg_stockpile * 0.85,
            "signal": "bullish" if decline_weeks >= 3 and current_stockpile < avg_stockpile * 0.85
                      else "watch" if decline_weeks >= 2
                      else "neutral",
        })

    conn.close()
    return results


# ============================================================
# 5. 跨市场联动信号 — 海外龙头异动 → A股滞后反应
# ============================================================
def fetch_cross_market_signals():
    """
    检测海外龙头异动，预判A股滞后反应
    逻辑: NVDA涨5% → 2-3天后A股光模块板块大概率跟涨
    """
    from db import get_conn, init_db, get_overseas_history
    import config
    init_db()

    signals = []

    for symbol, info in config.OVERSEAS_STOCKS.items():
        history = get_overseas_history(symbol, days=5)
        if len(history) < 2:
            continue

        latest = history[0]
        prev = history[1]

        # 检测单日大幅异动
        change = latest.get("change_pct", 0)
        if abs(change) >= 3:
            signals.append({
                "type": "overseas_shock",
                "symbol": symbol,
                "name": info["name"],
                "change_pct": change,
                "affects": info["affects"],
                "note": info["note"],
                "severity": "high" if abs(change) >= 5 else "medium",
                "lead_time": "1-3个交易日",
            })

        # 检测连续异动（3天累计涨跌超8%）
        if len(history) >= 4:
            cum_3d = sum(h.get("change_pct", 0) for h in history[:3])
            if abs(cum_3d) >= 8:
                signals.append({
                    "type": "overseas_trend",
                    "symbol": symbol,
                    "name": info["name"],
                    "cum_change_3d": round(cum_3d, 2),
                    "affects": info["affects"],
                    "note": info["note"],
                    "severity": "high",
                    "lead_time": "持续趋势，A股将跟随",
                })

    return signals


# ============================================================
# 6. 综合先行指标采集
# ============================================================
def collect_all_leading_indicators():
    """采集所有先行指标数据"""
    print("  === 先行指标采集 ===")

    # 1. 板块资金流向
    print("  采集板块资金流向...")
    fund_flow = fetch_sector_fund_flow()
    print(f"    获取 {len(fund_flow)} 个板块资金数据")

    # 2. 概念板块异动
    print("  采集概念板块异动...")
    concepts = fetch_concept_boards()
    print(f"    获取 {len(concepts)} 个概念板块")

    # 3. 政策文件
    print("  扫描政策文件...")
    policies = fetch_policy_documents()
    print(f"    发现 {len(policies)} 条政策相关")

    # 4. 股吧情绪
    print("  采集股吧情绪...")
    guba = fetch_guba_heat()
    sentiment_signals = detect_sentiment_spike(guba)
    print(f"    扫描 {len(guba)} 只股票股吧，发现 {len(sentiment_signals)} 个情绪突变")

    # 5. 商品动量
    print("  分析商品动量...")
    commodities = fetch_commodity_momentum()
    print(f"    分析 {len(commodities)} 个商品")

    # 6. 跨市场联动
    print("  检测跨市场联动...")
    cross_market = fetch_cross_market_signals()
    print(f"    发现 {len(cross_market)} 个跨市场信号")

    return {
        "fund_flow": fund_flow,
        "concepts": concepts,
        "policies": policies,
        "sentiment": sentiment_signals,
        "commodities": commodities,
        "cross_market": cross_market,
        "timestamp": datetime.now().isoformat(),
    }


if __name__ == "__main__":
    data = collect_all_leading_indicators()

    print(f"\n=== 先行指标汇总 ===")
    print(f"板块资金流: {len(data['fund_flow'])} 个板块")
    print(f"概念板块: {len(data['concepts'])} 个概念")
    print(f"政策文件: {len(data['policies'])} 条")
    print(f"情绪突变: {len(data['sentiment'])} 个信号")
    print(f"商品动量: {len(data['commodities'])} 个商品")
    print(f"跨市场信号: {len(data['cross_market'])} 个")

    # 打印资金流入前5
    if data["fund_flow"]:
        print(f"\n资金净流入前5:")
        for f in sorted(data["fund_flow"], key=lambda x: x["net_flow"], reverse=True)[:5]:
            print(f"  {f['name']}: {f['net_flow_yi']}亿 ({f['change_pct']}%)")

    # 打印跨市场信号
    if data["cross_market"]:
        print(f"\n跨市场联动信号:")
        for s in data["cross_market"]:
            print(f"  {s['symbol']} {s['change_pct']:+.1f}% → 影响: {', '.join(s['affects'])}")
