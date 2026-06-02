"""
AI产业链监控 - 先行指标分析引擎
将多维度先行指标数据融合为"提前量预警"
核心逻辑: 多信号共振 → 预警置信度提升
"""
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config

# ============================================================
# AI产业链关键词映射
# ============================================================
SECTOR_KEYWORDS = {
    "光模块": ["光模块", "光通信", "CPO", "硅光", "800G", "1.6T", "LPO", "中际旭创", "新易盛"],
    "服务器": ["服务器", "AI服务器", "算力", "数据中心", "液冷服务器", "工业富联", "浪潮信息"],
    "PCB": ["PCB", "印制电路板", "HDI", "IC载板", "深南电路", "兴森科技"],
    "液冷": ["液冷", "温控", "散热", "浸没式", "英维克"],
    "封装": ["封装", "CoWoS", "先进封装", "Chiplet", "2.5D", "3D封装", "长电科技", "通富微电"],
    "铜缆": ["铜缆", "高速铜缆", "DAC", "AEC", "沃尔核材"],
    "锡": ["锡", "锡价", "锡库存", "锡业股份"],
    "铜": ["铜", "铜价", "铜库存", "紫金矿业"],
    "国产算力": ["国产算力", "国产芯片", "寒武纪", "海光信息", "华为昇腾", "信创"],
}


def _match_sectors(text):
    """文本匹配到哪些板块"""
    matched = []
    for sector, keywords in SECTOR_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            matched.append(sector)
    return matched


# ============================================================
# 1. 板块资金流分析
# ============================================================
def analyze_fund_flow(fund_flow_data):
    """
    分析板块资金流向，检测聪明钱轮动
    信号: 资金净流入>2亿 + 涨幅温和(<3%) = 主力吸筹阶段
    信号: 资金净流入>5亿 + 涨幅>3% = 主力拉升阶段
    """
    signals = []
    for item in fund_flow_data:
        net_flow_yi = item.get("net_flow_yi", 0)
        change_pct = item.get("change_pct", 0)
        name = item.get("name", "")

        # 主力吸筹信号: 资金流入但涨幅不大（还没涨但钱已经进来了）
        if net_flow_yi > 2 and -1 < change_pct < 3:
            matched_sectors = _match_sectors(name)
            signals.append({
                "type": "fund_accumulation",
                "source": "板块资金流",
                "title": f"{name} 主力资金持续流入",
                "detail": f"净流入{net_flow_yi}亿，涨幅仅{change_pct}%，疑似主力吸筹",
                "severity": "high" if net_flow_yi > 5 else "medium",
                "affected_sectors": matched_sectors,
                "lead_time": "领先价格1-3天",
                "data": {"net_flow_yi": net_flow_yi, "change_pct": change_pct},
            })

        # 资金大幅流入信号
        elif net_flow_yi > 5:
            matched_sectors = _match_sectors(name)
            signals.append({
                "type": "fund_inflow_surge",
                "source": "板块资金流",
                "title": f"{name} 主力资金大幅流入",
                "detail": f"净流入{net_flow_yi}亿，涨幅{change_pct}%，资金强势",
                "severity": "critical" if net_flow_yi > 10 else "high",
                "affected_sectors": matched_sectors,
                "lead_time": "正在发生",
                "data": {"net_flow_yi": net_flow_yi, "change_pct": change_pct},
            })

    return signals


# ============================================================
# 2. 概念板块异动分析
# ============================================================
def analyze_concept_boards(concept_data):
    """
    分析概念板块异动
    信号: 新兴概念(CoWoS/HBM/硅光)涨>3% = 产业链联动即将传导到A股
    信号: 概念板块涨家数>>跌家数 = 板块共振
    """
    signals = []

    # AI产业链相关概念关键词
    ai_concept_keywords = [
        "AI", "算力", "芯片", "半导体", "光模块", "服务器", "数据中心",
        "GPU", "封装", "PCB", "液冷", "铜缆", "存储", "DRAM", "NAND",
        "英伟达", "台积电", "CoWoS", "HBM", "先进制程", "人工智能",
        "大模型", "AIGC", "智算", "推理", "CPO", "硅光", "Chiplet",
    ]

    for item in concept_data:
        name = item.get("name", "")
        change_pct = item.get("change_pct", 0)
        rise_count = item.get("rise_count", 0)
        fall_count = item.get("fall_count", 0)

        # 只关注AI产业链相关概念
        is_ai_related = any(kw in name for kw in ai_concept_keywords)
        if not is_ai_related:
            continue

        # 概念板块大涨
        if change_pct > 3:
            matched_sectors = _match_sectors(name)
            signals.append({
                "type": "concept_surge",
                "source": "概念板块",
                "title": f"概念板块异动: {name}",
                "detail": f"涨{change_pct}%，领涨: {item.get('leading_stock', '')}({item.get('leading_stock_change', 0)}%)",
                "severity": "high" if change_pct > 5 else "medium",
                "affected_sectors": matched_sectors,
                "lead_time": "概念传导到个股通常1-2天",
                "data": item,
            })

        # 板块共振: 涨家数远大于跌家数
        if rise_count > 0 and fall_count > 0 and rise_count / max(fall_count, 1) > 3 and rise_count >= 10:
            matched_sectors = _match_sectors(name)
            signals.append({
                "type": "concept_resonance",
                "source": "概念板块",
                "title": f"{name} 板块共振上涨",
                "detail": f"涨{rise_count}家/跌{fall_count}家，板块全面走强",
                "severity": "medium",
                "affected_sectors": matched_sectors,
                "lead_time": "板块共振通常持续2-5天",
                "data": item,
            })

    return signals


# ============================================================
# 3. 政策信号分析
# ============================================================
def analyze_policy_signals(policy_data):
    """
    分析政策文件信号
    政策利好从发布到央视报道有1-3天时间差
    在政策发布时就识别，比新闻报道提前布局
    """
    signals = []

    # 高影响政策关键词
    high_impact_keywords = ["补贴", "专项资金", "税收优惠", "产业基金", "国产替代", "自主可控", "新基建"]
    medium_impact_keywords = ["规划", "指导意见", "行动计划", "试点", "示范"]

    for doc in policy_data:
        title = doc.get("title", "")
        matched_sectors = _match_sectors(title)

        if not matched_sectors:
            continue

        if any(kw in title for kw in high_impact_keywords):
            signals.append({
                "type": "policy_high",
                "source": "政策文件",
                "title": f"政策利好: {title[:40]}",
                "detail": f"来源: {doc.get('source', '')}，涉及板块: {', '.join(matched_sectors)}",
                "severity": "high",
                "affected_sectors": matched_sectors,
                "lead_time": "政策传导到市场1-3天",
                "data": doc,
            })
        elif any(kw in title for kw in medium_impact_keywords):
            signals.append({
                "type": "policy_medium",
                "source": "政策文件",
                "title": f"政策关注: {title[:40]}",
                "detail": f"来源: {doc.get('source', '')}，涉及板块: {', '.join(matched_sectors)}",
                "severity": "medium",
                "affected_sectors": matched_sectors,
                "lead_time": "长期影响",
                "data": doc,
            })

    return signals


# ============================================================
# 4. 情绪突变分析
# ============================================================
def analyze_sentiment_signals(sentiment_data):
    """
    分析社交媒体情绪突变
    股吧发帖量暴增往往领先价格1-3天
    """
    signals = []

    for item in sentiment_data:
        code = item.get("code", "")
        name = item.get("name", "")
        sector = item.get("sector", "")
        post_count = item.get("post_count", 0)
        hot_posts = item.get("hot_posts", [])

        # 情绪突变信号
        signals.append({
            "type": "sentiment_spike",
            "source": "股吧情绪",
            "title": f"{name}({code}) 股吧热度飙升",
            "detail": f"帖子数{post_count}，热门话题: {' | '.join(hot_posts[:3])}",
            "severity": item.get("severity", "medium"),
            "affected_sectors": [sector] if sector else [],
            "lead_time": "情绪领先价格1-3天",
            "data": item,
        })

    return signals


# ============================================================
# 5. 商品动量分析
# ============================================================
def analyze_commodity_signals(commodity_data):
    """
    分析商品库存动量
    库存连续下降 + 价格企稳 = 即将上涨的先行信号
    """
    signals = []

    commodity_sector_map = {
        "tin": ["锡", "封装"],  # 锡用于焊接，影响封装板块
        "copper": ["铜", "铜缆", "PCB"],  # 铜用于PCB和铜缆
    }

    for item in commodity_data:
        commodity = item.get("commodity", "")
        signal_type = item.get("signal", "neutral")
        decline_weeks = item.get("decline_weeks", 0)
        current = item.get("current_stockpile", 0)
        avg = item.get("avg_stockpile", 0)

        if signal_type == "bullish":
            sectors = commodity_sector_map.get(commodity, [])
            commodity_name = {"tin": "锡", "copper": "铜"}.get(commodity, commodity)
            signals.append({
                "type": "commodity_bullish",
                "source": "商品动量",
                "title": f"{commodity_name}库存持续下降",
                "detail": f"连续{decline_weeks}周下降，当前{current:.0f}吨，低于均值{avg:.0f}吨15%以上",
                "severity": "high",
                "affected_sectors": sectors,
                "lead_time": "库存领先价格2-4周",
                "data": item,
            })
        elif signal_type == "watch":
            commodity_name = {"tin": "锡", "copper": "铜"}.get(commodity, commodity)
            sectors = commodity_sector_map.get(commodity, [])
            signals.append({
                "type": "commodity_watch",
                "source": "商品动量",
                "title": f"{commodity_name}库存下降趋势",
                "detail": f"连续{decline_weeks}周下降，关注是否跌破警戒线",
                "severity": "medium",
                "affected_sectors": sectors,
                "lead_time": "持续关注",
                "data": item,
            })

    return signals


# ============================================================
# 6. 跨市场联动分析
# ============================================================
def analyze_cross_market(cross_market_data):
    """
    分析跨市场联动信号
    海外龙头异动 → A股滞后1-3天反应
    """
    signals = []

    for item in cross_market_data:
        symbol = item.get("symbol", "")
        name = item.get("name", "")
        affects = item.get("affects", [])
        change_pct = item.get("change_pct", 0)
        cum_change = item.get("cum_change_3d")

        if item.get("type") == "overseas_shock":
            direction = "大涨" if change_pct > 0 else "大跌"
            signals.append({
                "type": "cross_market_shock",
                "source": "跨市场联动",
                "title": f"{name}({symbol}) 海外{direction}",
                "detail": f"涨跌{change_pct:+.1f}%，预计1-3天传导至A股: {', '.join(affects)}",
                "severity": item.get("severity", "medium"),
                "affected_sectors": affects,
                "lead_time": "1-3个交易日",
                "data": item,
            })
        elif item.get("type") == "overseas_trend":
            direction = "持续上涨" if cum_change > 0 else "持续下跌"
            signals.append({
                "type": "cross_market_trend",
                "source": "跨市场联动",
                "title": f"{name}({symbol}) 海外{direction}",
                "detail": f"3日累计{cum_change:+.1f}%，A股{', '.join(affects)}将跟随",
                "severity": "high",
                "affected_sectors": affects,
                "lead_time": "持续趋势",
                "data": item,
            })

    return signals


# ============================================================
# 7. 多信号共振检测
# ============================================================
def detect_resonance(all_signals):
    """
    多信号共振: 当多个不同来源的信号指向同一板块 → 置信度大幅提升
    例如: 资金流入 + 概念板块涨 + 海外龙头涨 → 光模块板块共振
    """
    # 按板块聚合信号
    sector_signals = {}
    for sig in all_signals:
        for sector in sig.get("affected_sectors", []):
            if sector not in sector_signals:
                sector_signals[sector] = []
            sector_signals[sector].append(sig)

    resonance_results = []
    for sector, sigs in sector_signals.items():
        if len(sigs) >= 2:
            # 不同来源的信号
            sources = set(s["source"] for s in sigs)
            if len(sources) >= 2:
                # 计算共振得分
                score = 0
                for s in sigs:
                    if s["severity"] == "critical":
                        score += 3
                    elif s["severity"] == "high":
                        score += 2
                    else:
                        score += 1

                resonance_results.append({
                    "sector": sector,
                    "signal_count": len(sigs),
                    "source_count": len(sources),
                    "score": score,
                    "sources": list(sources),
                    "signals": sigs,
                    "confidence": "high" if score >= 6 else "medium" if score >= 3 else "low",
                })

    # 按得分排序
    resonance_results.sort(key=lambda x: x["score"], reverse=True)
    return resonance_results


# ============================================================
# 8. 综合先行指标分析
# ============================================================
def run_leading_analysis(leading_data):
    """
    综合分析所有先行指标，输出预警信号
    输入: collect_all_leading_indicators() 的输出
    输出: {signals, resonances, summary}
    """
    all_signals = []

    # 分析各维度
    all_signals.extend(analyze_fund_flow(leading_data.get("fund_flow", [])))
    all_signals.extend(analyze_concept_boards(leading_data.get("concepts", [])))
    all_signals.extend(analyze_policy_signals(leading_data.get("policies", [])))
    all_signals.extend(analyze_sentiment_signals(leading_data.get("sentiment", [])))
    all_signals.extend(analyze_commodity_signals(leading_data.get("commodities", [])))
    all_signals.extend(analyze_cross_market(leading_data.get("cross_market", [])))

    # 检测共振
    resonances = detect_resonance(all_signals)

    # 生成摘要
    high_signals = [s for s in all_signals if s["severity"] in ("high", "critical")]
    summary = {
        "total_signals": len(all_signals),
        "high_signals": len(high_signals),
        "resonances": len(resonances),
        "top_resonance": resonances[0] if resonances else None,
        "timestamp": datetime.now().isoformat(),
    }

    # 打印摘要
    print(f"\n  === 先行指标分析结果 ===")
    print(f"  总信号: {len(all_signals)} | 高优: {len(high_signals)} | 共振板块: {len(resonances)}")

    if resonances:
        print(f"\n  多信号共振板块:")
        for r in resonances[:5]:
            print(f"    {r['sector']}: {r['signal_count']}个信号来自{r['source_count']}个来源, 置信度{r['confidence']}")
            for s in r["signals"]:
                print(f"      [{s['source']}] {s['title']}")

    if high_signals:
        print(f"\n  高优预警:")
        for s in high_signals[:10]:
            icon = {"critical": "[!!!]", "high": "[!!]", "medium": "[!]"}.get(s["severity"], "[~]")
            print(f"    {icon} [{s['source']}] {s['title']}")
            print(f"       {s['detail']} | 领先时间: {s['lead_time']}")

    return {
        "signals": all_signals,
        "resonances": resonances,
        "summary": summary,
    }


if __name__ == "__main__":
    from collectors.leading_collector import collect_all_leading_indicators

    print("=== 采集先行指标 ===")
    raw_data = collect_all_leading_indicators()

    print("\n=== 分析先行指标 ===")
    result = run_leading_analysis(raw_data)
