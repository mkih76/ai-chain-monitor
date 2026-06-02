"""
AI产业链监控 - 自动发现新标的
扫描新闻高频词，发现不在监控列表中但频繁出现的AI产业链相关公司
通过AI分析判断是否值得加入监控
"""
import sys
import os
import json
import re
import sqlite3
from datetime import datetime, timedelta
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import get_conn, init_db
import config

# ============================================================
# 1. 新闻词频分析
# ============================================================
def extract_stock_mentions(days=7):
    """从最近N天新闻中提取股票/公司名称提及"""
    conn = get_conn()
    since = (datetime.now() - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT title, content, keywords FROM news WHERE timestamp >= ?",
        (since,)
    ).fetchall()
    conn.close()

    # 已在监控列表中的公司
    watched_names = set()
    for code, (name, sector) in config.WATCHLIST.items():
        watched_names.add(name)
    for symbol, info in config.OVERSEAS_STOCKS.items():
        watched_names.add(info["name"])

    # A股公司名模式：2-4个汉字 + 可选的(代码)
    stock_pattern = re.compile(r'([\u4e00-\u9fa5]{2,4})(?:股份|科技|电子|信息|通信|微电|光电|新材|智造)?')

    # 行业关键词关联
    ai_keywords = [
        "AI", "算力", "芯片", "半导体", "光模块", "服务器", "数据中心",
        "GPU", "封装", "PCB", "液冷", "铜缆", "存储", "DRAM", "NAND",
        "英伟达", "台积电", "CoWoS", "HBM", "先进制程",
        "人工智能", "大模型", "AIGC", "智算", "推理芯片",
    ]

    mention_counter = Counter()
    context_map = {}  # 记录提及上下文

    for row in rows:
        title = row[0] or ""
        content = row[1] or ""
        keywords = row[2] or ""
        full_text = f"{title} {content} {keywords}"

        # 检查是否包含AI产业链关键词
        has_ai_keyword = any(kw.lower() in full_text.lower() for kw in ai_keywords)
        if not has_ai_keyword:
            continue

        # 提取公司名
        matches = stock_pattern.findall(full_text)
        for name in matches:
            if len(name) < 2:
                continue
            if name in watched_names:
                continue
            # 过滤常见非公司名
            if name in ("中国", "美国", "全球", "市场", "行业", "产业", "技术", "公司", "集团", "基金", "指数"):
                continue
            mention_counter[name] += 1
            if name not in context_map:
                context_map[name] = title[:50]

    return mention_counter, context_map

def find_potential_codes(company_names):
    """通过东方财富搜索API查找公司股票代码"""
    import requests
    results = []

    for name in company_names:
        try:
            url = "https://searchapi.eastmoney.com/bussiness/Web/GetCMSSearchList"
            params = {
                "type": "8193",
                "keyword": name,
                "pageIndex": 1,
                "pageSize": 3,
            }
            r = requests.get(url, params=params, headers={
                "User-Agent": "Mozilla/5.0"
            }, timeout=10)
            if r.status_code == 200:
                data = r.json()
                items = data.get("Data", []) or data.get("data", []) or []
                if isinstance(items, dict):
                    items = items.get("List", []) or items.get("list", []) or []
                for item in items[:1]:
                    title = item.get("Title", "") or item.get("title", "")
                    # 从标题中提取股票代码
                    code_match = re.search(r'(\d{6})', title)
                    if code_match:
                        code = code_match.group(1)
                        results.append({"name": name, "code": code, "source": title})
                        break
        except Exception:
            pass

    return results

# ============================================================
# 2. AI分析新标的价值
# ============================================================
def ai_analyze_discovery(candidates, mention_counter, context_map):
    """用AI分析候选标的是否值得加入监控"""
    if not candidates:
        return []

    mimo_url = config.AI_ENGINE.get("mimo_proxy_url", "")
    if not mimo_url:
        print("  ⚠ MiMo Proxy未配置，跳过AI分析")
        return _fallback_ranking(candidates, mention_counter)

    # 构建候选描述
    candidates_text = ""
    for c in candidates:
        mentions = mention_counter.get(c["name"], 0)
        ctx = context_map.get(c["name"], "")
        candidates_text += f"\n- {c['name']}({c['code']}): 提及{mentions}次, 上下文: {ctx}"

    # 已有监控列表
    watched = ", ".join(f"{name}({code})" for code, (name, sector) in config.WATCHLIST.items())

    prompt = f"""你是A股AI产业链分析师。以下是在近期新闻中高频出现但尚未被监控的公司。

已有监控标的: {watched}

候选新标的:
{candidates_text}

请判断哪些值得加入AI产业链监控，并说明理由。输出JSON数组:
[
  {{"code": "股票代码", "name": "名称", "sector": "所属板块", "reason": "加入理由", "priority": "high/medium/low"}}
]

判断标准:
1. 是否属于AI产业链上游（芯片/封装/PCB/光模块/服务器/液冷/铜缆/存储/算力）
2. 新闻提及是否与AI需求直接相关（而非蹭热点）
3. 是否有产业链联动逻辑（海外龙头→上游→该标的）

只输出JSON数组。"""

    try:
        from collectors.news_collector import _call_mimo_llm
        response = _call_mimo_llm(prompt, mimo_url)
        if response:
            from analyzers.ai_engine import _parse_analysis_response
            result = _parse_analysis_response(response)
            if isinstance(result, list):
                return result
    except Exception as e:
        print(f"  ⚠ AI分析失败: {e}")

    return _fallback_ranking(candidates, mention_counter)

def _fallback_ranking(candidates, mention_counter):
    """无AI时的备用排序"""
    scored = []
    for c in candidates:
        mentions = mention_counter.get(c["name"], 0)
        scored.append({
            "code": c["code"],
            "name": c["name"],
            "sector": "待确认",
            "reason": f"近期新闻提及{mentions}次",
            "priority": "high" if mentions >= 5 else ("medium" if mentions >= 3 else "low"),
        })
    scored.sort(key=lambda x: mention_counter.get(x["name"], 0), reverse=True)
    return scored

# ============================================================
# 3. 发现结果存储
# ============================================================
def _ensure_discovery_table():
    """确保发现表存在"""
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS discoveries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            name TEXT,
            code TEXT,
            sector TEXT,
            reason TEXT,
            priority TEXT,
            mentions INTEGER,
            status TEXT DEFAULT 'pending',
            reviewed_at TEXT
        )
    """)
    conn.commit()
    conn.close()

def save_discoveries(discoveries, mention_counter):
    """保存发现结果"""
    _ensure_discovery_table()
    conn = get_conn()

    for d in discoveries:
        # 检查是否已存在
        existing = conn.execute(
            "SELECT id FROM discoveries WHERE code=? AND status='pending'",
            (d.get("code", ""),)
        ).fetchone()

        if existing:
            continue

        conn.execute(
            """INSERT INTO discoveries
               (timestamp, name, code, sector, reason, priority, mentions)
               VALUES (?,?,?,?,?,?,?)""",
            (datetime.now().isoformat(), d.get("name", ""), d.get("code", ""),
             d.get("sector", ""), d.get("reason", ""), d.get("priority", "low"),
             mention_counter.get(d.get("name", ""), 0))
        )

    conn.commit()
    conn.close()

def get_pending_discoveries():
    """获取待审核的发现"""
    _ensure_discovery_table()
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM discoveries WHERE status='pending' ORDER BY priority DESC, mentions DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def approve_discovery(discovery_id):
    """批准一个发现，加入监控列表"""
    _ensure_discovery_table()
    conn = get_conn()
    row = conn.execute("SELECT * FROM discoveries WHERE id=?", (discovery_id,)).fetchone()
    if not row:
        conn.close()
        return False
    row = dict(row)
    conn.execute(
        "UPDATE discoveries SET status='approved', reviewed_at=? WHERE id=?",
        (datetime.now().isoformat(), discovery_id)
    )
    conn.commit()
    conn.close()
    print(f"  ✓ 已批准: {row['name']}({row['code']}) → {row['sector']}")
    return True

def reject_discovery(discovery_id):
    """拒绝一个发现"""
    _ensure_discovery_table()
    conn = get_conn()
    conn.execute(
        "UPDATE discoveries SET status='rejected', reviewed_at=? WHERE id=?",
        (datetime.now().isoformat(), discovery_id)
    )
    conn.commit()
    conn.close()

# ============================================================
# 4. 综合运行
# ============================================================
def run_discovery():
    """运行自动发现流程"""
    print("  === 自动发现新标的 ===")

    # 1. 从新闻中提取高频公司名
    print("  扫描近期新闻...")
    mention_counter, context_map = extract_stock_mentions(days=7)

    if not mention_counter:
        print("  未发现新的高频公司")
        return []

    # 只关注提及3次以上的
    top_mentions = {k: v for k, v in mention_counter.most_common(20) if v >= 3}
    if not top_mentions:
        print("  无足够高频的公司名")
        return []

    print(f"  发现 {len(top_mentions)} 个高频提及公司")
    for name, count in list(top_mentions.items())[:5]:
        print(f"    {name}: {count}次 - {context_map.get(name, '')}")

    # 2. 查找股票代码
    print("  查找股票代码...")
    candidates = find_potential_codes(list(top_mentions.keys()))
    if not candidates:
        print("  未能匹配到股票代码")
        return []
    print(f"  匹配到 {len(candidates)} 个候选标的")

    # 3. AI分析价值
    print("  AI分析候选标的...")
    discoveries = ai_analyze_discovery(candidates, mention_counter, context_map)

    if not discoveries:
        print("  AI分析无结果")
        return []

    # 4. 保存结果
    save_discoveries(discoveries, mention_counter)

    # 5. 输出
    print(f"\n  === 发现结果 ===")
    for d in discoveries:
        priority_icon = {"high": "🔴", "medium": "🟡", "low": "⚪"}.get(d.get("priority", "low"), "⚪")
        print(f"  {priority_icon} {d.get('name', '')}({d.get('code', '')}) - {d.get('sector', '')}")
        print(f"     {d.get('reason', '')}")

    return discoveries

if __name__ == "__main__":
    init_db()
    _ensure_discovery_table()
    results = run_discovery()

    if results:
        print(f"\n待审核发现: {len(results)}")
