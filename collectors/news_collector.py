"""
新闻/公告监控采集器 v2
升级: AI语义分析替代关键词打分 + 新增财联社电报源
数据源:
  1. 东方财富搜索API (原有)
  2. 财联社电报 (新增 - 实时性最强)
  3. 巨潮资讯公告 (新增 - 上市公司官方公告)
"""
import requests
import json
import re
import time
from datetime import datetime
import sys
sys.path.insert(0, "/opt/ai-monitor")
from db import insert_stock, get_conn
import config

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.eastmoney.com/",
}

# ============================================================
# 关键词权重 (作为初筛，AI分析替代精排)
# ============================================================
KEYWORDS = {
    # 高权重 - 直接相关
    "capex": 10, "资本开支": 10, "资本支出": 10,
    "AI": 6, "AI服务器": 8, "AI芯片": 8, "AI算力": 8, "AI助手": 5,
    "算力": 8, "光模块": 8, "先进封装": 8,
    "CoWoS": 9, "英伟达": 8, "NVIDIA": 8, "GPU": 7,
    # 中权重 - 产业链相关
    "数据中心": 6, "液冷": 6, "PCB": 5, "铜缆": 5,
    "半导体": 5, "芯片": 5, "封装": 5,
    # 原材料
    "锡库存": 7, "锡价": 7, "铜库存": 6, "铜价": 6,
    "LME": 6, "SHFE": 6, "仓单": 6,
    "镍": 6, "镍价": 7, "镍库存": 7,
    # 低权重 - 宏观
    "人工智能": 5, "大模型": 5, "AIGC": 4, "AGI": 5,
    # 新增: 上游产业关键词
    "台积电": 7, "TSMC": 7, "营收": 5, "出货": 6,
    "扩产": 6, "涨价": 7, "产能": 6, "库存下降": 8,
    "DRAM": 7, "NAND": 6, "存储": 5, "HBM": 8,
}

# ============================================================
# 1. 新浪财经新闻 (替代失效的东方财富搜索API)
# ============================================================
def fetch_sina_finance_news():
    """从新浪财经抓取7x24快讯"""
    url = "https://feed.mix.sina.com.cn/api/roll/get"
    results = []

    try:
        params = {
            "pageid": "153",
            "lid": "2516",  # 财经快讯
            "k": "",
            "num": 30,
            "page": 1,
        }
        r = requests.get(url, params=params, timeout=10,
                       headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            data = r.json()
            items = data.get("result", {}).get("data", [])
            for item in items:
                title = item.get("title", "")
                matches, score = _scan_text(title)
                if score >= 5:
                    ctime = item.get("ctime", 0)
                    date_str = datetime.fromtimestamp(int(ctime)).strftime("%Y-%m-%d %H:%M") if ctime else ""
                    news = {
                        "source": "sina_finance",
                        "title": title,
                        "url": item.get("url", ""),
                        "keywords": ",".join(matches),
                        "score": score,
                        "relevance": "high" if score >= 8 else "medium",
                        "date": date_str,
                        "content": "",
                    }
                    results.append(news)
    except Exception as e:
        print(f"  [WARN] 新浪财经新闻抓取失败: {e}")

    return results

# ============================================================
# 2. 财联社电报 (新增 - 实时性最强)
# ============================================================
def fetch_cls_telegraph():
    """从财联社抓取实时电报"""
    results = []
    cls_config = getattr(config, "CLS_TELEGRAPH", {})
    watch_keywords = cls_config.get("keywords", [])

    # 尝试多个API端点
    urls = [
        "https://www.cls.cn/v1/roll/get_roll_list",
        "https://www.cls.cn/nodeapi/telegraphList",
    ]

    for url in urls:
        try:
            params = {
                "app": "CailianpressWeb",
                "category": "",
                "os": "web",
                "sv": "8.4.6",
                "rn": "50",
            }
            r = requests.get(url, params=params, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://www.cls.cn/telegraph",
            }, timeout=15)

            if r.status_code == 200:
                data = r.json()
                # 尝试多种返回格式
                items = (data.get("data", {}).get("roll_data", []) or
                        data.get("data", {}).get("list", []) or
                        data.get("data", []))
                if not isinstance(items, list):
                    items = []

                for item in items:
                    content = item.get("content", "") or item.get("brief", "")
                    title = item.get("title", "") or content[:80]
                    ctime = item.get("ctime", 0)
                    date_str = datetime.fromtimestamp(ctime).strftime("%Y-%m-%d %H:%M") if ctime else ""

                    # 关键词过滤
                    matched = [kw for kw in watch_keywords if kw.lower() in (title + content).lower()]
                    if not matched:
                        continue

                    score = len(matched) * 5
                    results.append({
                        "source": "cls_telegraph",
                        "title": title,
                        "url": f"https://www.cls.cn/detail/{item.get('id', '')}",
                        "keywords": ",".join(matched),
                        "score": score,
                        "relevance": "high" if score >= 10 else "medium",
                        "date": date_str,
                        "content": content[:500],
                    })

                if results:
                    break  # 成功获取数据，停止尝试其他端点
        except Exception as e:
            pass  # 尝试下一个端点

    return results

# ============================================================
# 3. 巨潮资讯公告 (新增 - 上市公司官方公告)
# ============================================================
def fetch_cninfo_announcements():
    """从巨潮资讯抓取监控标的的公告"""
    print("  采集巨潮公告...")
    results = []

    for code, (name, sector) in config.WATCHLIST.items():
        try:
            url = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
            payload = {
                "stock": f"{code}",
                "tabName": "fulltext",
                "pageNum": 1,
                "pageSize": 3,
                "column": "szse" if code.startswith(("0", "3")) else "sse",
                "category": "",
                "plate": "",
                "seDate": "",
            }
            r = requests.post(url, data=payload, headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://www.cninfo.com.cn/",
                "Accept": "application/json",
            }, timeout=15)

            if r.status_code == 200:
                data = r.json()
                announcements = data.get("announcements", []) or []
                for ann in announcements:
                    title = ann.get("announcementTitle", "")
                    ann_url = f"https://www.cninfo.com.cn/new/disclosure/detail?stockCode={code}&announcementId={ann.get('announcementId', '')}"
                    date_ts = ann.get("announcementTime", 0)
                    date_str = datetime.fromtimestamp(date_ts/1000).strftime("%Y-%m-%d") if date_ts else ""

                    # 只关注重要公告类型
                    important_keywords = ["业绩", "合同", "订单", "中标", "扩产",
                                         "投资", "产能", "合作", "研发", "产品"]
                    if any(kw in title for kw in important_keywords):
                        results.append({
                            "source": "cninfo",
                            "title": f"[{name}] {title}",
                            "url": ann_url,
                            "keywords": name,
                            "score": 8,
                            "relevance": "high",
                            "date": date_str,
                            "content": "",
                            "code": code,
                            "name": name,
                        })
            time.sleep(0.5)
        except Exception as e:
            pass  # 个别股票查询失败不影响整体

    print(f"    巨潮公告: {len(results)}条相关")
    return results

# ============================================================
# AI语义分析 (替代关键词打分)
# ============================================================
def ai_analyze_news(news_list):
    """用AI对新闻进行语义分析，替代简单的关键词打分"""
    if not config.AI_ENGINE.get("enabled", False):
        return news_list

    mimo_url = config.AI_ENGINE.get("mimo_proxy_url", "")
    if not mimo_url:
        print("  ⚠ MiMo Proxy未配置，使用关键词打分")
        return news_list

    max_batch = config.AI_ENGINE.get("max_news_per_batch", 20)
    batch = news_list[:max_batch]

    # 构建批量分析prompt
    titles = "\n".join(f"{i+1}. [{n['source']}] {n['title']}" for i, n in enumerate(batch))
    watchlist_str = ", ".join(f"{name}({code})" for code, (name, _) in config.WATCHLIST.items())

    prompt = f"""你是A股AI产业链分析师。分析以下新闻对监控标的的影响。

监控标的: {watchlist_str}

新闻列表:
{titles}

对每条新闻，请输出JSON数组，每个元素包含:
- index: 新闻序号
- direction: "bullish"/"bearish"/"neutral"
- affected: 受影响的股票代码(逗号分隔)
- time_horizon: "short"(1周内)/"medium"(1-4周)/"long"(1月+)
- confidence: "high"/"medium"/"low"
- reason: 一句话理由

只输出JSON数组，不要其他文字。"""

    try:
        response = _call_mimo_llm(prompt, mimo_url)
        if response:
            analyses = _parse_ai_response(response)
            if analyses:
                for i, analysis in enumerate(analyses):
                    if i < len(batch):
                        batch[i]["ai_direction"] = analysis.get("direction", "neutral")
                        batch[i]["ai_affected"] = analysis.get("affected", "")
                        batch[i]["ai_time_horizon"] = analysis.get("time_horizon", "short")
                        batch[i]["ai_confidence"] = analysis.get("confidence", "low")
                        batch[i]["ai_reason"] = analysis.get("reason", "")
                        # 用AI置信度提升score
                        if analysis.get("confidence") == "high":
                            batch[i]["score"] = max(batch[i].get("score", 0), 10)
                            batch[i]["relevance"] = "high"
                        elif analysis.get("confidence") == "medium":
                            batch[i]["score"] = max(batch[i].get("score", 0), 7)
                print(f"  ✓ AI分析完成: {len(analyses)}条新闻")
            else:
                print("  ⚠ AI返回格式解析失败，保留关键词打分")
        else:
            print("  ⚠ AI分析无响应，保留关键词打分")
    except Exception as e:
        print(f"  ⚠ AI分析异常: {e}，保留关键词打分")

    return news_list

def _call_mimo_llm(prompt, mimo_url):
    """调用MiMo LLM Proxy"""
    try:
        # 构建cookie
        cookie_parts = []
        if config.AI_ENGINE.get("mimo_service_token"):
            cookie_parts.append(f"serviceToken={config.AI_ENGINE['mimo_service_token']}")
        if config.AI_ENGINE.get("mimo_user_id"):
            cookie_parts.append(f"userId={config.AI_ENGINE['mimo_user_id']}")
        if config.AI_ENGINE.get("mimo_cookie"):
            cookie_parts.append(config.AI_ENGINE["mimo_cookie"])

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0",
        }
        if cookie_parts:
            headers["Cookie"] = "; ".join(cookie_parts)

        payload = {
            "messages": [{"role": "user", "content": prompt}],
            "model": "mimo-v2.5-pro",
            "temperature": 0.1,
            "max_tokens": 2000,
        }

        r = requests.post(mimo_url, json=payload, headers=headers, timeout=30)
        if r.status_code == 200:
            data = r.json()
            # 尝试多种返回格式
            if "choices" in data:
                return data["choices"][0]["message"]["content"]
            elif "data" in data and "content" in data["data"]:
                return data["data"]["content"]
            elif "response" in data:
                return data["response"]
            return r.text
    except Exception as e:
        print(f"  [ERROR] MiMo调用失败: {e}")
    return None

def _parse_ai_response(response_text):
    """解析AI返回的JSON"""
    try:
        # 尝试直接解析
        return json.loads(response_text)
    except json.JSONDecodeError:
        pass

    # 尝试从markdown代码块中提取
    match = re.search(r'```(?:json)?\s*([\s\S]*?)```', response_text)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # 尝试找JSON数组
    match = re.search(r'\[[\s\S]*\]', response_text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return None

# ============================================================
# 辅助函数
# ============================================================
def _scan_text(text):
    """扫描文本中的关键词"""
    matches = []
    score = 0
    text_lower = text.lower()
    for kw, weight in KEYWORDS.items():
        if kw.lower() in text_lower:
            matches.append(kw)
            score += weight
    return matches, score

def save_news_to_db(news_list):
    """将新闻存入数据库"""
    conn = get_conn()
    for n in news_list:
        conn.execute(
            "INSERT INTO news (timestamp, source, title, url, keywords, relevance) VALUES (?,?,?,?,?,?)",
            (n.get("date", datetime.now().isoformat()), n["source"], n["title"],
             n.get("url", ""), n.get("keywords", ""), n.get("relevance", "medium"))
        )
    conn.commit()
    conn.close()

# ============================================================
# 综合采集
# ============================================================
def collect_news():
    """采集所有新闻源 + AI分析"""
    print("  === 采集行业新闻 ===")
    all_news = []

    # 新浪财经快讯 (替代失效的东方财富搜索API)
    sina_news = fetch_sina_finance_news()
    all_news.extend(sina_news)
    print(f"  ✓ 新浪财经: {len(sina_news)}条相关")
    time.sleep(1)

    # 财联社电报
    cls_news = fetch_cls_telegraph()
    all_news.extend(cls_news)
    print(f"  ✓ 财联社: {len(cls_news)}条相关")
    time.sleep(1)

    # 巨潮公告
    cn_news = fetch_cninfo_announcements()
    all_news.extend(cn_news)

    # 去重
    seen_titles = set()
    unique_news = []
    for n in all_news:
        title_key = n["title"][:30]  # 用前30字符去重
        if title_key not in seen_titles:
            seen_titles.add(title_key)
            unique_news.append(n)

    # AI语义分析 (替代纯关键词打分)
    if config.AI_ENGINE.get("enabled", False):
        print("  AI语义分析中...")
        unique_news = ai_analyze_news(unique_news)

    # 按分数排序
    unique_news.sort(key=lambda x: x.get("score", 0), reverse=True)

    # 存入数据库
    save_news_to_db(unique_news)

    print(f"  共 {len(unique_news)} 条相关新闻")
    return unique_news

if __name__ == "__main__":
    from db import init_db
    init_db()
    print("=== 采集行业新闻 ===")
    news = collect_news()
    for n in news[:15]:
        icon = "🔴" if n.get("relevance") == "high" else "🟡"
        ai_tag = ""
        if n.get("ai_direction"):
            ai_icon = {"bullish": "📈", "bearish": "📉", "neutral": "➡️"}.get(n["ai_direction"], "")
            ai_tag = f" AI:{ai_icon}{n['ai_confidence']}"
        print(f"{icon} [{n.get('score', 0)}] {n['title']}")
        if ai_tag:
            print(f"   {ai_tag} → {n.get('ai_reason', '')}")
