"""
M5 · AI研判引擎 v2
混合架构: 规则引擎(量化) + LLM(质化推理)

规则引擎负责:
  - 数据源可靠度权重
  - 信号时间衰减
  - severity加权投票
  - 多源共振检测
  - 量化评分

LLM负责:
  - 信号组合的质化推理
  - 传导链分析
  - 风险评估
  - 行动建议
"""
import sys
import os
import json
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db import get_active_signals, get_conn, init_db
import config


# ============================================================
# 数据源可靠度权重 (0-1)
# 越高 = 该来源的信号越可信
# ============================================================
SOURCE_WEIGHT = {
    "inventory":    1.0,   # 库存: 最硬的先行指标，供需基本面
    "capital":      0.85,  # 资金: 机构有信息优势
    "commodity":    0.80,  # 商品: 价格传导有1-3天时滞
    "announcement": 0.75,  # 公告: 原始公告可靠
    "overseas":     0.70,  # 海外: 有12h窗口但有隔夜风险
    "correlator":   0.90,  # 多源共振: 交叉验证后更可靠
    "news":         0.30,  # 新闻: 最不可靠，滞后+噪音
}

# severity权重
SEVERITY_WEIGHT = {
    "S1": 100,
    "S2": 70,
    "S3": 40,
    "S4": 15,
}

# 时间衰减: 每过24小时置信度衰减的比例
DECAY_PER_DAY = 0.15  # 15%/天


def generate_signal_report():
    """
    生成综合研判报告
    Step 1: 规则引擎量化分析
    Step 2: LLM质化推理（可选）
    """
    init_db()
    signals = get_active_signals()

    if not signals:
        return _empty_report()

    # Step 1: 规则引擎
    quantified = _quantify_signals(signals)
    sector_analysis = _analyze_sectors(quantified)
    global_view = _global_assessment(sector_analysis)
    risk_alerts = _assess_risks(signals, sector_analysis)
    data_gaps = _identify_gaps()

    # Step 2: LLM质化推理
    llm_report = _llm_reasoning(quantified, sector_analysis, global_view, risk_alerts)

    return {
        "timestamp": datetime.now().isoformat(),
        "summary": global_view["summary"],
        "action": global_view["action"],
        "signals_reviewed": len(signals),
        "bullish_sectors": global_view["bullish_count"],
        "bearish_sectors": global_view["bearish_count"],
        "top_calls": sector_analysis[:6],
        "risk_alerts": risk_alerts,
        "data_gaps": data_gaps,
        "ai_enhancement": llm_report,
    }


# ============================================================
# Step 1: 规则引擎 (量化)
# ============================================================

def _quantify_signals(signals):
    """
    对每个信号计算量化分数
    公式: score = severity_weight × source_weight × time_decay × confidence
    """
    now = datetime.now()
    result = []

    for sig in signals:
        source = sig.get("source", "")
        severity = sig.get("severity", "S4")
        confidence = sig.get("confidence", 0)
        timestamp = sig.get("timestamp", "")

        # 基础权重
        sev_w = SEVERITY_WEIGHT.get(severity, 10)
        src_w = SOURCE_WEIGHT.get(source, 0.5)

        # 时间衰减
        try:
            sig_time = datetime.fromisoformat(timestamp)
            age_hours = (now - sig_time).total_seconds() / 3600
            decay = max(0, 1 - (age_hours / 24) * DECAY_PER_DAY)
        except Exception:
            decay = 0.8  # 无法解析时间，给默认值

        # 综合评分
        score = sev_w * src_w * decay * confidence

        result.append({
            **sig,
            "_score": round(score, 2),
            "_sev_weight": sev_w,
            "_src_weight": src_w,
            "_decay": round(decay, 3),
            "_age_hours": round(age_hours, 1) if 'age_hours' in dir() else 0,
        })

    # 按评分排序
    result.sort(key=lambda x: x["_score"], reverse=True)
    return result


def _analyze_sectors(quantified):
    """按板块聚合分析"""
    sector_map = defaultdict(lambda: {
        "bull_score": 0, "bear_score": 0,
        "signals": [], "sources": set(),
        "max_severity": "S4", "max_score": 0,
    })

    for sig in quantified:
        sectors = json.loads(sig.get("target_sectors", "[]"))
        direction = sig.get("direction", "neutral")
        score = sig.get("_score", 0)
        severity = sig.get("severity", "S4")

        for sector in sectors:
            s = sector_map[sector]
            if direction == "bullish":
                s["bull_score"] += score
            elif direction == "bearish":
                s["bear_score"] += score
            s["signals"].append(sig)
            s["sources"].add(sig.get("source", ""))
            if SEVERITY_WEIGHT.get(severity, 0) > SEVERITY_WEIGHT.get(s["max_severity"], 0):
                s["max_severity"] = severity
            s["max_score"] = max(s["max_score"], score)

    # 转为列表并计算综合指标
    result = []
    stocks_map = {
        '光模块':'中际旭创/新易盛','服务器':'工业富联/浪潮信息','PCB':'深南电路/兴森科技',
        '封装':'长电科技/通富微电','液冷':'英维克','国产算力':'寒武纪/海光信息',
        '锡':'锡业股份','铜':'紫金矿业','铜缆':'沃尔核材',
    }

    for sector, data in sector_map.items():
        total_score = data["bull_score"] + data["bear_score"]
        if total_score == 0:
            continue

        # 方向: 用加权分数而非简单计数
        if data["bull_score"] > data["bear_score"] * 1.2:
            direction = "bullish"
        elif data["bear_score"] > data["bull_score"] * 1.2:
            direction = "bearish"
        else:
            direction = "neutral"

        # 综合置信度 = 较大方向分数 / 总分数
        dominant = max(data["bull_score"], data["bear_score"])
        confidence = dominant / total_score if total_score > 0 else 0

        # 来源数
        source_count = len(data["sources"])

        # 行动建议
        action = _recommend_action(direction, confidence, source_count, data["max_severity"])

        # 推理文本
        reasoning = []
        for sig in data["signals"][:4]:
            src_cn = _source_cn(sig.get("source", ""))
            reasoning.append(f"[{src_cn}]{sig.get('description', '')[:45]}")

        result.append({
            "sector": sector,
            "stocks": stocks_map.get(sector, ""),
            "direction": direction,
            "severity": data["max_severity"],
            "confidence": round(confidence, 3),
            "bull_score": round(data["bull_score"], 1),
            "bear_score": round(data["bear_score"], 1),
            "signal_count": len(data["signals"]),
            "source_count": source_count,
            "sources": list(data["sources"]),
            "reasoning": "; ".join(reasoning),
            "action": action,
        })

    # 按dominant score排序
    result.sort(key=lambda x: max(x["bull_score"], x["bear_score"]), reverse=True)
    return result


def _global_assessment(sector_analysis):
    """全局研判"""
    if not sector_analysis:
        return {"summary": "无板块信号", "action": "hold", "bullish_count": 0, "bearish_count": 0}

    # 用加权分数而非简单计数
    total_bull = sum(s["bull_score"] for s in sector_analysis)
    total_bear = sum(s["bear_score"] for s in sector_analysis)
    bullish_count = sum(1 for s in sector_analysis if s["direction"] == "bullish")
    bearish_count = sum(1 for s in sector_analysis if s["direction"] == "bearish")

    # 看空板块的最高severity
    bearish_max_sev = max(
        (SEVERITY_WEIGHT.get(s["severity"], 0) for s in sector_analysis if s["direction"] == "bearish"),
        default=0
    )
    bullish_max_sev = max(
        (SEVERITY_WEIGHT.get(s["severity"], 0) for s in sector_analysis if s["direction"] == "bullish"),
        default=0
    )

    if total_bear > total_bull * 1.5:
        if bearish_max_sev >= 70:  # S2+
            summary = f"看空信号占优({bearish_count}个板块)，且有高严重等级信号，建议防守"
            action = "watch_bearish"
        else:
            summary = f"看空信号略占优({bearish_count}vs{bullish_count})，建议谨慎"
            action = "cautious"
    elif total_bull > total_bear * 1.5:
        if bullish_max_sev >= 70:
            summary = f"看多信号占优({bullish_count}个板块)，建议关注多头机会"
            action = "watch_bullish"
        else:
            summary = f"看多信号略占优，可小仓位试探"
            action = "cautious_bullish"
    else:
        summary = f"多空信号交织(看多{bullish_count}/看空{bearish_count})，建议观望"
        action = "hold"

    return {"summary": summary, "action": action, "bullish_count": bullish_count, "bearish_count": bearish_count}


def _recommend_action(direction, confidence, source_count, max_severity):
    """推荐行动"""
    sev_score = SEVERITY_WEIGHT.get(max_severity, 0)

    if direction == "bullish":
        if confidence > 0.8 and source_count >= 3 and sev_score >= 70:
            return "重点关注，多源共振看多"
        elif confidence > 0.6:
            return "关注，信号偏多"
        return "观察，信号较弱"
    elif direction == "bearish":
        if confidence > 0.8 and source_count >= 3 and sev_score >= 70:
            return "重点回避，多源共振看空"
        elif confidence > 0.6:
            return "谨慎，信号偏空"
        return "观察，信号较弱"
    return "观望"


# ============================================================
# Step 2: LLM质化推理
# ============================================================

# 分析师系统提示词
ANALYST_PROMPT = """你是一个A股产业链分析师，专注于先行信号分析。

## 你的分析框架

### 1. 信号优先级（从高到低）
- **多源共振**: 3个以上独立来源指向同一方向 → 最强信号
- **库存信号**: SHFE/LME库存变化 → 最硬的先行指标，领先价格5-8天
- **资金信号**: 龙虎榜机构席位/融资余额 → 机构有信息优势
- **商品信号**: 期货价格异动 → 传导到A股有1-3天时滞
- **海外信号**: 美股龙头盘后异动 → 12小时预警窗口
- **公告信号**: 中标/增持/扩产 → 比新闻早1-3天

### 2. 你需要特别注意的
- **方向冲突**: 同一板块既有看多又有看空信号 → 高风险，需要明确说明
- **信号质量**: 来源可靠度不同，库存信号比新闻信号可信3倍
- **时间因素**: 信号越老越不可靠，72小时以上的信号需要打折
- **传导逻辑**: 不是简单加总，要看传导链是否合理

### 3. 输出要求
- 一句话总结（30字内）
- 最值得关注的1-2个板块及具体理由
- 最大的风险点
- 明确的建议操作（关注/回避/观望）
- 不超过200字，不要废话"""


def _llm_reasoning(quantified, sector_analysis, global_view, risk_alerts):
    """
    调用LLM进行质化推理
    输入: 规则引擎的量化结果（结构化数据）
    输出: LLM的推理分析（文字报告）
    """
    api_base = config.AI_ENGINE.get("api_base", "")
    api_key = config.AI_ENGINE.get("api_key", "")
    model = config.AI_ENGINE.get("model", "MiniMax-M2.7")

    if not api_base or not api_key or not config.AI_ENGINE.get("enabled"):
        return None

    try:
        import requests as req

        # 构造结构化输入
        input_data = {
            "global": global_view,
            "sectors": sector_analysis[:6],
            "top_signals": [
                {
                    "source": s.get("source"),
                    "severity": s.get("severity"),
                    "direction": s.get("direction"),
                    "confidence": s.get("confidence"),
                    "score": s.get("_score"),
                    "description": s.get("description", "")[:80],
                }
                for s in quantified[:8]
            ],
            "risks": risk_alerts[:3],
        }

        user_msg = f"""请基于以下先行信号数据进行分析：

```json
{json.dumps(input_data, ensure_ascii=False, indent=2)}
```

请按你的分析框架进行研判。"""

        url = f"{api_base}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": ANALYST_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            "max_tokens": 600,
            "temperature": 0.3,
        }

        resp = req.post(url, json=payload, headers=headers, timeout=30)

        if resp.status_code == 200:
            data = resp.json()
            content = (data.get("choices", [{}])[0]
                      .get("message", {}).get("content", ""))
            if content:
                return content
        else:
            print(f"  ⚠ AI API返回 {resp.status_code}: {resp.text[:100]}")
    except Exception as e:
        print(f"  ⚠ AI调用异常: {e}")

    return None


# ============================================================
# 风险评估 + 数据缺口
# ============================================================

def _assess_risks(signals, sector_analysis):
    """评估风险"""
    risks = []

    # 1. 方向冲突
    for sec in sector_analysis:
        if sec["bull_score"] > 0 and sec["bear_score"] > 0:
            ratio = max(sec["bull_score"], sec["bear_score"]) / max(min(sec["bull_score"], sec["bear_score"]), 0.01)
            if ratio < 3:  # 多空分数差距不大=真正冲突
                risks.append({
                    "type": "direction_conflict",
                    "sector": sec["sector"],
                    "description": f"{sec['sector']}板块多空信号冲突(多:{sec['bull_score']:.0f} 空:{sec['bear_score']:.0f})，需谨慎",
                    "severity": "medium",
                })

    # 2. 高置信看空
    for sig in signals:
        if sig.get("direction") == "bearish" and sig.get("confidence", 0) > 0.75:
            sectors = json.loads(sig.get("target_sectors", "[]"))
            risks.append({
                "type": "bearish_alert",
                "sector": sectors[0] if sectors else "",
                "description": sig.get("description", "")[:80],
                "severity": "high",
            })

    # 3. 数据缺口
    active_sources = set(s.get("source") for s in signals)
    expected = {"inventory", "capital", "commodity", "overseas"}
    missing = expected - active_sources
    if missing:
        risks.append({
            "type": "data_gap",
            "description": f"数据源缺失: {', '.join(missing)}，可能影响研判准确性",
            "severity": "low",
        })

    return risks


def _identify_gaps():
    """识别数据缺口"""
    gaps = []
    try:
        conn = get_conn()
        row = conn.execute("SELECT COUNT(*) as cnt FROM inventory").fetchone()
        if row["cnt"] == 0:
            gaps.append("库存数据为空，需运行SHFE采集或手动录入")
        row = conn.execute("SELECT COUNT(*) as cnt FROM material_prices").fetchone()
        if row["cnt"] == 0:
            gaps.append("商品期货数据为空，需运行材料采集")
        conn.close()
    except Exception:
        pass
    return gaps


def _empty_report():
    return {
        "timestamp": datetime.now().isoformat(),
        "summary": "当前无活跃信号，市场暂无明确方向",
        "action": "hold",
        "signals_reviewed": 0,
        "bullish_sectors": 0,
        "bearish_sectors": 0,
        "top_calls": [],
        "risk_alerts": [],
        "data_gaps": [],
        "ai_enhancement": None,
    }


def _source_cn(source):
    return {
        "inventory": "库存", "capital": "资金", "commodity": "商品",
        "announcement": "公告", "overseas": "海外", "correlator": "共振",
        "news": "新闻",
    }.get(source, source)


if __name__ == "__main__":
    report = generate_signal_report()
    print("=" * 50)
    print("AI研判报告 v2")
    print("=" * 50)
    print(f"综合: {report['summary']}")
    print(f"动作: {report['action']}")
    print(f"分析: {report['signals_reviewed']}个信号")
    print()
    for call in report.get("top_calls", []):
        print(f"  [{call['severity']}] {call['sector']}({call.get('stocks','')})")
        print(f"    方向:{call['direction']} 置信:{call['confidence']} "
              f"多分:{call['bull_score']} 空分:{call['bear_score']}")
        print(f"    来源:{call['source_count']}个 信号:{call['signal_count']}个")
        print(f"    建议:{call['action']}")
    print()
    if report.get("risk_alerts"):
        print("风险:")
        for r in report["risk_alerts"]:
            print(f"  [{r['severity']}] {r['description']}")
    print()
    if report.get("ai_enhancement"):
        print("--- LLM分析 ---")
        print(report["ai_enhancement"])
