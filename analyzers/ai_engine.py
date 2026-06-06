"""
M5 · AI研判引擎
综合所有活跃信号，输出人类可读的结论和行动建议

与旧版的区别：
- 旧版：分析新闻标题 → 输出"利好/利空"（事后诸葛亮）
- 新版：分析原始信号组合 → 输出"建议关注/建议回避"（事前研判）
"""
import sys
import os
import json
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db import get_active_signals, get_conn, init_db
import config


def generate_signal_report():
    """
    基于活跃信号生成综合研判报告（不需要AI，纯规则引擎版本）
    有MiMo Proxy时可调用AI增强，但基本功能不依赖AI

    返回: dict，包含summary/top_calls/risk_alerts/data_gaps
    """
    init_db()
    signals = get_active_signals()

    if not signals:
        return {
            "timestamp": datetime.now().isoformat(),
            "summary": "当前无活跃信号，市场暂无明确方向",
            "action": "hold",
            "signals_reviewed": 0,
            "top_calls": [],
            "risk_alerts": [],
            "data_gaps": [],
        }

    # 按板块分组
    by_sector = defaultdict(list)
    for sig in signals:
        sectors = json.loads(sig.get("target_sectors", "[]"))
        for sector in sectors:
            by_sector[sector].append(sig)

    # 生成top_calls
    top_calls = []
    for sector, sigs in sorted(by_sector.items(),
                                key=lambda x: _sector_score(x[1]),
                                reverse=True):
        # 统计方向
        bullish = sum(1 for s in sigs if s.get("direction") == "bullish")
        bearish = sum(1 for s in sigs if s.get("direction") == "bearish")
        direction = "bullish" if bullish > bearish else "bearish" if bearish > bullish else "neutral"

        # 最高severity
        sev_order = {"S1": 1, "S2": 2, "S3": 3, "S4": 4}
        best_sev = min(sigs, key=lambda s: sev_order.get(s.get("severity", "S4"), 5))

        # 综合置信度
        confs = [s.get("confidence", 0) for s in sigs]
        combined_conf = 1 - _prod(1 - c for c in confs)

        # 信号来源
        sources = list(set(s.get("source", "") for s in sigs))

        # 受影响标的
        all_stocks = []
        for s in sigs:
            all_stocks.extend(json.loads(s.get("target_stocks", "[]")))
        unique_stocks = list(dict.fromkeys(all_stocks))

        # 推理文本
        reasoning_parts = []
        for s in sigs:
            src_name = _source_cn(s.get("source", ""))
            reasoning_parts.append(f"[{src_name}]{s.get('description', '')[:50]}")

        top_calls.append({
            "sector": sector,
            "direction": direction,
            "severity": best_sev.get("severity", "S4"),
            "confidence": round(combined_conf, 3),
            "signal_count": len(sigs),
            "source_count": len(sources),
            "sources": sources,
            "affected_stocks": unique_stocks[:5],
            "reasoning": "; ".join(reasoning_parts),
            "action": _recommend_action(direction, combined_conf, len(sources)),
        })

    # 风险提示
    risk_alerts = _assess_risks(signals, by_sector)

    # 数据缺口
    data_gaps = _identify_gaps()

    # 综合判断
    bullish_sectors = sum(1 for c in top_calls if c["direction"] == "bullish")
    bearish_sectors = sum(1 for c in top_calls if c["direction"] == "bearish")

    if bullish_sectors > bearish_sectors * 2:
        overall = "市场偏多信号占优，建议关注多头机会"
        action = "watch_bullish"
    elif bearish_sectors > bullish_sectors * 2:
        overall = "市场偏空信号占优，建议防守为主"
        action = "watch_bearish"
    else:
        overall = "多空信号交织，建议观望等待明确方向"
        action = "hold"

    # 尝试调用AI增强（可选）
    ai_enhancement = _try_ai_enhance(top_calls, risk_alerts)

    return {
        "timestamp": datetime.now().isoformat(),
        "summary": overall,
        "action": action,
        "signals_reviewed": len(signals),
        "bullish_sectors": bullish_sectors,
        "bearish_sectors": bearish_sectors,
        "top_calls": top_calls,
        "risk_alerts": risk_alerts,
        "data_gaps": data_gaps,
        "ai_enhancement": ai_enhancement,
    }


def _sector_score(sigs):
    """板块综合评分（用于排序）"""
    sev_weight = {"S1": 100, "S2": 70, "S3": 40, "S4": 15}
    score = 0
    for s in sigs:
        score += sev_weight.get(s.get("severity", "S4"), 0)
        score += s.get("confidence", 0) * 50
    return score


def _prod(values):
    result = 1
    for v in values:
        result *= v
    return result


def _recommend_action(direction, confidence, source_count):
    """根据信号强度推荐动作"""
    if direction == "bullish":
        if confidence > 0.8 and source_count >= 3:
            return "重点关注，多源共振看多"
        elif confidence > 0.6:
            return "关注，信号偏多"
        else:
            return "观察，信号较弱"
    elif direction == "bearish":
        if confidence > 0.8 and source_count >= 3:
            return "重点回避，多源共振看空"
        elif confidence > 0.6:
            return "谨慎，信号偏空"
        else:
            return "观察，信号较弱"
    return "观望"


def _assess_risks(signals, by_sector):
    """评估风险"""
    risks = []

    # 检查是否有方向冲突
    for sector, sigs in by_sector.items():
        directions = set(s.get("direction") for s in sigs)
        if "bullish" in directions and "bearish" in directions:
            risks.append({
                "type": "direction_conflict",
                "sector": sector,
                "description": f"{sector}板块出现多空信号冲突，需谨慎",
                "severity": "medium",
            })

    # 检查高置信度看空信号
    for sig in signals:
        if sig.get("direction") == "bearish" and sig.get("confidence", 0) > 0.7:
            sectors = json.loads(sig.get("target_sectors", "[]"))
            risks.append({
                "type": "bearish_alert",
                "sector": sectors[0] if sectors else "",
                "description": sig.get("description", "")[:80],
                "severity": "high",
            })

    # 数据缺口风险
    active_sources = set(s.get("source") for s in signals)
    expected = {"inventory", "capital", "commodity", "overseas"}
    missing = expected - active_sources
    if missing:
        risks.append({
            "type": "data_gap",
            "description": f"以下数据源暂无信号: {', '.join(missing)}，可能是数据未采集而非无信号",
            "severity": "low",
        })

    return risks


def _identify_gaps():
    """识别数据缺口"""
    gaps = []
    try:
        conn = get_conn()
        # 检查库存数据
        row = conn.execute("SELECT COUNT(*) as cnt FROM inventory").fetchone()
        if row["cnt"] == 0:
            gaps.append("库存数据为空，需运行SHFE采集或手动录入")
        # 检查北向数据
        row = conn.execute("SELECT COUNT(*) as cnt FROM northbound_history").fetchone()
        if row["cnt"] == 0:
            gaps.append("北向资金数据为空，需运行资金采集")
        # 检查商品数据
        row = conn.execute("SELECT COUNT(*) as cnt FROM material_prices").fetchone()
        if row["cnt"] == 0:
            gaps.append("商品期货数据为空，需运行材料采集")
        conn.close()
    except Exception:
        pass
    return gaps


def _try_ai_enhance(top_calls, risk_alerts):
    """
    尝试调用MiMo Proxy增强分析（可选）
    如果MiMo不可用，返回None，不影响整体功能
    """
    mimo_url = config.AI_ENGINE.get("mimo_proxy_url", "")
    if not mimo_url or not config.AI_ENGINE.get("enabled"):
        return None

    try:
        import requests as req

        # 构造prompt
        signal_summary = json.dumps(top_calls[:5], ensure_ascii=False, indent=2)
        risk_summary = json.dumps(risk_alerts[:3], ensure_ascii=False, indent=2)

        prompt = f"""你是A股AI产业链分析师。基于以下先行信号数据，给出简洁的综合研判。

活跃信号:
{signal_summary}

风险提示:
{risk_summary}

要求:
1. 一句话总结当前市场信号格局
2. 最值得关注的1-2个板块及理由
3. 最大的风险点
4. 建议操作（关注/回避/观望）

简洁回答，不超过200字。"""

        # 尝试读取cookie
        cookie = config.AI_ENGINE.get("mimo_cookie", "")
        cookies = {}
        if cookie:
            cookies = {"serviceToken": cookie}

        resp = req.post(mimo_url, json={
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }, cookies=cookies, timeout=15)

        if resp.status_code == 200:
            data = resp.json()
            content = (data.get("choices", [{}])[0]
                      .get("message", {}).get("content", ""))
            if content:
                return content
    except Exception:
        pass

    return None


def _source_cn(source):
    """来源代码转中文"""
    return {
        "inventory": "库存", "capital": "资金", "commodity": "商品",
        "announcement": "公告", "overseas": "海外", "news": "新闻",
        "correlator": "关联",
    }.get(source, source)


if __name__ == "__main__":
    report = generate_signal_report()
    print("=" * 50)
    print("AI研判报告")
    print("=" * 50)
    print(f"时间: {report['timestamp']}")
    print(f"综合: {report['summary']}")
    print(f"分析信号: {report['signals_reviewed']} 个")
    print(f"\n重点关注:")
    for call in report.get("top_calls", []):
        print(f"  [{call['severity']}] {call['sector']}: {call['direction']} "
              f"conf={call['confidence']} | {call['action']}")
    print(f"\n风险提示:")
    for risk in report.get("risk_alerts", []):
        print(f"  [{risk['severity']}] {risk['description']}")
    if report.get("data_gaps"):
        print(f"\n数据缺口:")
        for gap in report["data_gaps"]:
            print(f"  - {gap}")
    if report.get("ai_enhancement"):
        print(f"\nAI增强分析:")
        print(f"  {report['ai_enhancement']}")
