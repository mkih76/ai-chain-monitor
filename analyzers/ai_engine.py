"""
AI多维关联分析引擎
核心差异化模块: 将价格、资金、产业链、上游、海外5个维度的数据融合
通过MiMo LLM Proxy进行关联分析，输出带置信度的综合研判
"""
import requests
import json
import re
from datetime import datetime
import sys
sys.path.insert(0, "/opt/ai-monitor")
from db import (
    get_stock_history, get_overseas_history, get_upstream_latest,
    get_northbound_consecutive_buy, get_ai_analysis_recent,
    insert_ai_analysis, get_conn,
)
from collectors.institutional_collector import (
    fetch_valuation, fetch_margin_trading, fetch_northbound_realtime,
)
from collectors.inventory_collector import get_inventory_trend
import config

# ============================================================
# 1. 数据聚合: 收集单只股票的多维数据
# ============================================================
def gather_stock_context(code):
    """收集单只股票的多维上下文数据"""
    name, sector = config.WATCHLIST.get(code, (code, ""))
    context = {
        "code": code,
        "name": name,
        "sector": sector,
        "dimensions": {},
    }

    # 维度1: 价格技术面
    history = get_stock_history(code, days=20)
    if history and len(history) >= 2:
        latest = history[0]
        prev = history[1]
        chg = round((latest["close"] - prev["close"]) / prev["close"] * 100, 2) if prev["close"] > 0 else 0
        avg_vol = sum(h["volume"] for h in history[1:min(21, len(history))]) / min(20, len(history)-1) if len(history) > 1 else 0
        vol_ratio = round(latest["volume"] / avg_vol, 2) if avg_vol > 0 else 0

        context["dimensions"]["price"] = {
            "close": latest["close"],
            "change_pct": chg,
            "volume_ratio": vol_ratio,
            "date": latest["date"],
            "high_20d": max(h["high"] for h in history),
            "low_20d": min(h["low"] for h in history),
        }

    # 维度2: 资金面 (融资融券)
    margin = fetch_margin_trading(code, days=5)
    if margin and len(margin) >= 2:
        rz_latest = margin[0]["rz_balance"]
        rz_prev = margin[1]["rz_balance"]
        rz_chg = round((rz_latest - rz_prev) / rz_prev * 100, 2) if rz_prev > 0 else 0
        context["dimensions"]["margin"] = {
            "rz_balance_yi": margin[0]["rz_balance_yi"],
            "rz_change_pct": rz_chg,
            "date": margin[0]["date"],
        }

    # 维度3: 估值面
    val = fetch_valuation(code)
    if val:
        context["dimensions"]["valuation"] = {
            "pe_ttm": val.get("pe_ttm"),
            "pb": val.get("pb"),
            "total_mv": val.get("total_mv"),
            "60day_change": val.get("60day_change"),
        }

    # 维度4: 北向资金连续买入
    nb_consec, nb_total = get_northbound_consecutive_buy(code, min_days=3)
    if nb_consec > 0:
        context["dimensions"]["northbound"] = {
            "consecutive_days": nb_consec,
            "total_net_buy": round(nb_total / 1e8, 2),
        }

    # 维度5: 库存数据 (原材料相关)
    if sector in ("锡", "铜"):
        commodity = "tin" if sector == "锡" else "copper"
        trend = get_inventory_trend(commodity, weeks=5)
        if trend.get("latest", 0) > 0:
            context["dimensions"]["inventory"] = {
                "commodity": commodity,
                "latest": trend["latest"],
                "trend": trend["trend"],
                "weeks": trend["weeks"],
            }

    return context

def gather_overseas_context():
    """收集海外标的隔夜表现"""
    context = {}
    for symbol in config.OVERSEAS_STOCKS:
        history = get_overseas_history(symbol, days=3)
        if history:
            latest = history[0]
            context[symbol] = {
                "name": config.OVERSEAS_STOCKS[symbol]["name"],
                "close": latest.get("close", 0),
                "change_pct": latest.get("change_pct", 0),
                "after_hours_change": latest.get("after_hours_change_pct"),
            }
    return context

def gather_upstream_context():
    """收集上游产业数据"""
    context = {}
    source_metrics = [
        ("tsmc", "monthly_revenue_twd_mn"),
        ("lme", "copper_stocks"),
        ("lme", "tin_stocks"),
        ("dram_market", "dram_sentiment"),
    ]
    for source, metric in source_metrics:
        data = get_upstream_latest(source, metric, limit=3)
        if data:
            key = f"{source}_{metric}"
            context[key] = [
                {"date": d["date"], "metric": d["metric"], "value": d["value"],
                 "yoy": d.get("yoy_change"), "mom": d.get("mom_change")}
                for d in data
            ]
    return context

# ============================================================
# 2. AI关联分析: 核心分析逻辑
# ============================================================
def ai_composite_analysis(code):
    """单只股票多维关联分析"""
    stock_ctx = gather_stock_context(code)
    overseas_ctx = gather_overseas_context()
    upstream_ctx = gather_upstream_context()

    prompt = _build_analysis_prompt(stock_ctx, overseas_ctx, upstream_ctx)
    response = _call_mimo(prompt)

    if not response:
        return None

    analysis = _parse_analysis_response(response)
    if analysis:
        # 存入数据库
        insert_ai_analysis(
            target=code,
            analysis_type="composite",
            direction=analysis.get("direction", "neutral"),
            confidence=analysis.get("confidence", "low"),
            catalyst=analysis.get("catalyst", ""),
            risk=analysis.get("risk", ""),
            action=analysis.get("action", ""),
            key_metrics=json.dumps(analysis.get("key_metrics", []), ensure_ascii=False),
            dimensions=json.dumps(list(stock_ctx.get("dimensions", {}).keys())),
            raw=response,
        )
    return analysis

def ai_sector_analysis(sector):
    """板块级关联分析"""
    # 找出该板块的所有股票
    sector_stocks = {c: n for c, (n, s) in config.WATCHLIST.items() if s == sector}
    if not sector_stocks:
        return None

    contexts = []
    for code in sector_stocks:
        ctx = gather_stock_context(code)
        contexts.append(ctx)

    overseas_ctx = gather_overseas_context()
    upstream_ctx = gather_upstream_context()

    prompt = _build_sector_prompt(sector, contexts, overseas_ctx, upstream_ctx)
    response = _call_mimo(prompt)

    if not response:
        return None

    analysis = _parse_analysis_response(response)
    if analysis:
        insert_ai_analysis(
            target=sector,
            analysis_type="sector",
            direction=analysis.get("direction", "neutral"),
            confidence=analysis.get("confidence", "low"),
            catalyst=analysis.get("catalyst", ""),
            risk=analysis.get("risk", ""),
            action=analysis.get("action", ""),
            key_metrics=json.dumps(analysis.get("key_metrics", []), ensure_ascii=False),
            dimensions=json.dumps(["price", "margin", "valuation", "northbound", "inventory"]),
            raw=response,
        )
    return analysis

def ai_global_scan():
    """全局扫描: 找出当前最值得关注的标的"""
    all_contexts = []
    for code, (name, sector) in config.WATCHLIST.items():
        ctx = gather_stock_context(code)
        # 只保留有实质数据的
        if len(ctx.get("dimensions", {})) >= 2:
            all_contexts.append(ctx)

    overseas_ctx = gather_overseas_context()
    upstream_ctx = gather_upstream_context()

    prompt = _build_global_prompt(all_contexts, overseas_ctx, upstream_ctx)
    response = _call_mimo(prompt)

    if not response:
        return None

    analysis = _parse_analysis_response(response)
    if analysis:
        insert_ai_analysis(
            target="GLOBAL",
            analysis_type="global_scan",
            direction=analysis.get("direction", "neutral"),
            confidence=analysis.get("confidence", "low"),
            catalyst=analysis.get("catalyst", ""),
            risk=analysis.get("risk", ""),
            action=analysis.get("action", ""),
            key_metrics=json.dumps(analysis.get("key_metrics", []), ensure_ascii=False),
            dimensions=json.dumps(["price", "margin", "valuation", "northbound", "overseas", "upstream"]),
            raw=response,
        )
    return analysis

# ============================================================
# 3. Prompt构建
# ============================================================
def _build_analysis_prompt(stock_ctx, overseas_ctx, upstream_ctx):
    """构建单股分析prompt"""
    name = stock_ctx["name"]
    code = stock_ctx["code"]
    sector = stock_ctx["sector"]

    dims_text = ""
    for dim_name, dim_data in stock_ctx.get("dimensions", {}).items():
        dims_text += f"\n【{dim_name}】{json.dumps(dim_data, ensure_ascii=False)}"

    overseas_text = ""
    for sym, data in overseas_ctx.items():
        chg = data.get("change_pct", 0)
        ah = data.get("after_hours_change")
        ah_str = f" 盘后{ah:+.1f}%" if ah else ""
        overseas_text += f"\n  {data['name']}({sym}): ${data.get('close', 0):.2f} {chg:+.1f}%{ah_str}"

    upstream_text = ""
    for src, items in upstream_ctx.items():
        if items:
            latest = items[0]
            yoy_str = f" YoY:{latest.get('yoy', 0):+.1f}%" if latest.get("yoy") else ""
            upstream_text += f"\n  {src}: {latest['value']} ({latest['date']}){yoy_str}"

    return f"""你是专业的A股产业链分析师。请对{name}({code})做综合研判。

板块: {sector}
=== 多维数据 ==={dims_text}

=== 海外龙头隔夜表现 ==={overseas_text or "  无数据"}

=== 上游产业数据 ==={upstream_text or "  无数据"}

请输出JSON:
{{
  "direction": "bullish"/"bearish"/"neutral",
  "confidence": "high"/"medium"/"low",
  "catalyst": "可能触发行情的事件",
  "risk": "可能导致判断错误的因素",
  "action": "立即关注"/"等待确认"/"可以忽略",
  "key_metrics": ["接下来最需要关注的指标"],
  "reasoning": "一句话核心逻辑"
}}

多维度信号同向=高置信度，单维度=低置信度。只输出JSON。"""

def _build_sector_prompt(sector, contexts, overseas_ctx, upstream_ctx):
    """构建板块分析prompt"""
    stocks_text = ""
    for ctx in contexts:
        name = ctx["name"]
        dims = ctx.get("dimensions", {})
        price = dims.get("price", {})
        margin = dims.get("margin", {})
        stocks_text += f"\n  {name}: 价格{price.get('change_pct', 0):+.1f}% 量比{price.get('volume_ratio', 0):.1f}x"
        if margin:
            stocks_text += f" 融资{margin.get('rz_change_pct', 0):+.1f}%"

    return f"""你是A股产业链分析师。分析{sector}板块的整体态势。

板块内股票:{stocks_text}

海外龙头: {json.dumps({s: d.get("change_pct", 0) for s, d in overseas_ctx.items()}, ensure_ascii=False)}

请输出JSON:
{{
  "direction": "bullish"/"bearish"/"neutral",
  "confidence": "high"/"medium"/"low",
  "catalyst": "板块催化剂",
  "risk": "板块风险",
  "action": "建议动作",
  "key_metrics": ["关键跟踪指标"],
  "reasoning": "核心逻辑"
}}"""

def _build_global_prompt(contexts, overseas_ctx, upstream_ctx):
    """构建全局扫描prompt"""
    summary = []
    for ctx in contexts:
        dims = ctx.get("dimensions", {})
        signals = []
        if "price" in dims:
            chg = dims["price"].get("change_pct", 0)
            if abs(chg) >= 3:
                signals.append(f"涨跌{chg:+.1f}%")
        if "northbound" in dims:
            nb = dims["northbound"]
            signals.append(f"北向连买{nb['consecutive_days']}天")
        if "margin" in dims:
            rz = dims["margin"].get("rz_change_pct", 0)
            if abs(rz) >= 3:
                signals.append(f"融资{rz:+.1f}%")
        if "inventory" in dims:
            inv = dims["inventory"]
            if inv.get("trend") == "declining":
                signals.append(f"库存下降{inv['weeks']}周")

        if signals:
            summary.append(f"{ctx['name']}({ctx['code']}): {', '.join(signals)}")

    return f"""你是A股AI产业链首席分析师。扫描全部监控标的，找出当前最值得关注的标的。

有异动信号的标的:
{chr(10).join(summary) if summary else "无显著异动"}

海外龙头: {json.dumps({s: d.get("change_pct", 0) for s, d in overseas_ctx.items()}, ensure_ascii=False)}

请输出JSON:
{{
  "top_picks": [
    {{"code": "股票代码", "name": "名称", "direction": "bullish/bearish", "reason": "理由"}}
  ],
  "direction": "整体偏多/偏空/中性",
  "confidence": "high"/"medium"/"low",
  "catalyst": "近期最大催化剂",
  "risk": "最大风险",
  "action": "建议动作"
}}"""

# ============================================================
# 4. LLM调用与解析
# ============================================================
def _call_mimo(prompt):
    """调用MiMo LLM Proxy"""
    mimo_url = config.AI_ENGINE.get("mimo_proxy_url", "")
    if not mimo_url:
        return None

    try:
        cookie_parts = []
        if config.AI_ENGINE.get("mimo_service_token"):
            cookie_parts.append(f"serviceToken={config.AI_ENGINE['mimo_service_token']}")
        if config.AI_ENGINE.get("mimo_user_id"):
            cookie_parts.append(f"userId={config.AI_ENGINE['mimo_user_id']}")
        if config.AI_ENGINE.get("mimo_cookie"):
            cookie_parts.append(config.AI_ENGINE["mimo_cookie"])

        headers = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
        if cookie_parts:
            headers["Cookie"] = "; ".join(cookie_parts)

        payload = {
            "messages": [{"role": "user", "content": prompt}],
            "model": "mimo-v2.5-pro",
            "temperature": 0.1,
            "max_tokens": 1500,
        }

        r = requests.post(mimo_url, json=payload, headers=headers, timeout=30)
        if r.status_code == 200:
            data = r.json()
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

def _parse_analysis_response(response_text):
    """解析AI分析返回"""
    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        pass

    match = re.search(r'```(?:json)?\s*([\s\S]*?)```', response_text)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    match = re.search(r'\{[\s\S]*\}', response_text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return None

# ============================================================
# 5. 综合运行
# ============================================================
def run_ai_analysis(mode="global"):
    """
    运行AI分析
    mode: "global" = 全局扫描, "per_stock" = 逐股分析, "per_sector" = 逐板块
    """
    print("  === AI多维关联分析 ===")

    if mode == "global":
        result = ai_global_scan()
        if result:
            print(f"  全局研判: {result.get('direction', 'N/A')} 置信度:{result.get('confidence', 'N/A')}")
            if result.get("top_picks"):
                for pick in result["top_picks"]:
                    icon = "📈" if pick.get("direction") == "bullish" else "📉"
                    print(f"    {icon} {pick.get('name', '')}({pick.get('code', '')}): {pick.get('reason', '')}")
        return result

    elif mode == "per_stock":
        results = {}
        for code, (name, sector) in config.WATCHLIST.items():
            print(f"  分析 {name}({code})...")
            result = ai_composite_analysis(code)
            if result:
                results[code] = result
                icon = {"bullish": "📈", "bearish": "📉", "neutral": "➡️"}.get(result.get("direction", ""), "")
                print(f"    {icon} {result.get('direction', '')} 置信度:{result.get('confidence', '')} → {result.get('action', '')}")
        return results

    elif mode == "per_sector":
        sectors = set(s for _, (_, s) in config.WATCHLIST.items())
        results = {}
        for sector in sectors:
            print(f"  分析板块: {sector}...")
            result = ai_sector_analysis(sector)
            if result:
                results[sector] = result
        return results

if __name__ == "__main__":
    from db import init_db
    init_db()
    result = run_ai_analysis(mode="global")
    if result:
        print("\n=== AI全局研判 ===")
        print(json.dumps(result, ensure_ascii=False, indent=2))
