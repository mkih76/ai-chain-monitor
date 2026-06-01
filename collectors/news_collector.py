"""
新闻/公告监控采集器
通过RSS和网页抓取监控行业动态
"""
import requests
import re
import json
from datetime import datetime
import sys
sys.path.insert(0, "/opt/ai-monitor")
import config

# 关键词权重
KEYWORDS = {
    # 高权重 - 直接相关
    "capex": 10, "资本开支": 10, "资本支出": 10,
    "算力": 8, "AI服务器": 8, "光模块": 8, "先进封装": 8,
    "CoWoS": 9, "英伟达": 8, "GPU": 7,
    # 中权重 - 产业链相关
    "数据中心": 6, "液冷": 6, "PCB": 5, "铜缆": 5,
    "半导体": 5, "芯片": 5, "封装": 5,
    # 原材料
    "锡库存": 7, "锡价": 7, "铜库存": 6, "铜价": 6,
    # 低权重 - 宏观
    "人工智能": 3, "大模型": 3, "AIGC": 3,
}

# 关注的RSS源（东方财富/新浪财经等提供RSS）
RSS_FEEDS = [
    # 东方财富 - 科技频道
    "https://rssfeed.eastmoney.com/rss_caijing.xml",
]

def scan_text(text):
    """扫描文本中的关键词，返回匹配和总分"""
    matches = []
    score = 0
    text_lower = text.lower()
    for kw, weight in KEYWORDS.items():
        if kw.lower() in text_lower:
            matches.append(kw)
            score += weight
    return matches, score

def scan_news_from_url(url, title="", source="web"):
    """扫描单条新闻"""
    matches, score = scan_text(f"{title}")
    if score >= 5:  # 阈值
        return {
            "source": source,
            "title": title,
            "url": url,
            "keywords": ",".join(matches),
            "score": score,
            "relevance": "high" if score >= 8 else "medium",
        }
    return None

def fetch_eastmoney_news():
    """从东方财富抓取AI相关新闻"""
    url = "https://searchapi.eastmoney.com/bussiness/Web/GetCMSSearchList"
    keywords_list = ["AI算力", "光模块", "人工智能芯片", "锡价", "AI服务器"]
    results = []

    for kw in keywords_list:
        try:
            params = {
                "type": "8193",  # 财经新闻
                "keyword": kw,
                "pageIndex": 1,
                "pageSize": 5,
            }
            r = requests.get(url, params=params, timeout=10,
                           headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 200:
                data = r.json()
                items = data.get("Data", []) or data.get("data", []) or []
                if isinstance(items, dict):
                    items = items.get("List", []) or items.get("list", []) or []
                for item in items[:5]:
                    title = item.get("Title", "") or item.get("title", "")
                    news_url = item.get("Url", "") or item.get("url", "")
                    news = scan_news_from_url(news_url, title, "eastmoney")
                    if news:
                        news["date"] = item.get("Date", "") or item.get("date", "")
                        results.append(news)
        except Exception as e:
            print(f"  [WARN] 东方财富新闻抓取失败 ({kw}): {e}")

    return results

def collect_news():
    """采集所有新闻"""
    print("  采集行业新闻...")
    all_news = []

    # 东方财富
    em_news = fetch_eastmoney_news()
    all_news.extend(em_news)
    print(f"  ✓ 东方财富: {len(em_news)}条相关")

    # 去重
    seen_titles = set()
    unique_news = []
    for n in all_news:
        if n["title"] not in seen_titles:
            seen_titles.add(n["title"])
            unique_news.append(n)

    # 按分数排序
    unique_news.sort(key=lambda x: x["score"], reverse=True)

    print(f"  共 {len(unique_news)} 条相关新闻")
    return unique_news

if __name__ == "__main__":
    print("=== 采集行业新闻 ===")
    news = collect_news()
    for n in news[:10]:
        icon = "🔴" if n["relevance"] == "high" else "🟡"
        print(f"{icon} [{n['score']}] {n['title']}")
        print(f"   关键词: {n['keywords']}")
