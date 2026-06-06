"""
因果链推理引擎
对多源信号进行因果链分析，输出有理论支撑的传导路径

核心逻辑:
1. 多源交叉: 同一板块被≥2个独立来源指向时触发深度分析
2. LLM推理: 给定信号组合，让LLM推导因果机制和置信度
3. 最佳链排序: 置信度 × 来源数 × severity加权
"""
import sys
import os
import json
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db import get_active_signals, init_db
import config


# ============================================================
# 因果链系统提示词
# ============================================================
CAUSAL_CHAIN_PROMPT = """你是一个产业链因果传导分析师。

## 你的任务
给定一个板块的多源信号组合，推导它们之间的因果关系，输出结构化的传导链。

## 传导类型（选最适合的）
- **成本传导**: 上游原材料价格变化 → 中游利润改善/承压
  例: 铜价下跌10% → PCB/铜缆成本节省3-4% → 利润率提升
- **需求传导**: 下游需求变化 → 中游订单变化
  例: AI爆发 → 光模块订单超预期 → 业绩释放
- **情绪传导**: 海外龙头暴跌 → A股情绪跟跌（隔夜传导）
  例: NVDA-10% → 次日A股AI板块情绪承压
- **资金传导**: 机构净买入/卖出 → 股价先行
  例: 龙虎榜机构席位净买入>1亿 → 领先信号
- **库存传导**: 库存连续下降 → 供需改善 → 价格/利润预期
  例: 锡库存连降4周 → 供给收缩 → 价格支撑

## 信号来源可靠度
- 库存: ★★★★★ 最硬，供需基本面
- 资金(机构席位): ★★★★ 有信息优势
- 商品期货: ★★★ 有时滞(1-3天)
- 海外映射: ★★★ 有隔夜风险
- 公告(中标/扩产): ★★★★ 原始事实

## 输出格式（严格按这个JSON输出，不要额外文字）
{
  "chains": [
    {
      "driver": "驱动力名称（如：铜价下跌15%）",
      "driver_source": "信号来源（如：商品期货）",
      "mechanism": "传导机制（如：铜占PCB成本35%，铜价跌则成本节省）",
      "target_sector": "受影响板块",
      "target_stocks": "关联股票",
      "direction": "bullish 或 bearish",
      "confidence": 0.0到1.0,
      "severity": "S1/S2/S3/S4",
      "corroboration": ["佐证1", "佐证2"],
      "historical_analogy": "历史类似案例（如有）",
      "action": "关注/回避/观望",
      "action_reason": "具体原因"
    }
  ]
}

## 推理要求
- 只输出有≥2个独立来源印证的传导链
- 置信度必须有推理过程支撑，不能凭空给
- 如果多源冲突（如：库存看多+资金看空），标注为"矛盾链"并说明
- 每个链必须有具体的传导机制，不是简单说"有关联"
- 输出不超过3条最佳链"""


def generate_causal_chains():
    """
    主入口：生成因果传导链
    返回: list of causal chain dict
    """
    init_db()
    signals = get_active_signals()

    if len(signals) < 2:
        return []

    # Step 1: 按板块分组，找多源信号组合
    sector_signals = _group_by_sector(signals)

    # Step 2: 筛选有多源印证的板块
    multi_source_sectors = {
        sec: sigs for sec, sigs in sector_signals.items()
        if _has_multiple_sources(sigs)
    }

    if not multi_source_sectors:
        return []

    # Step 3: 对每个多源板块调用LLM推理
    chains = []
    for sector, sigs in multi_source_sectors.items():
        chain = _llm_reason_causal_chain(sector, sigs)
        if chain:
            chains.extend(chain)

    # Step 4: 排序（置信度×来源数×severity）
    chains.sort(key=lambda c: _chain_score(c), reverse=True)

    return chains[:8]


def _group_by_sector(signals):
    """按板块分组"""
    sector_map = defaultdict(list)
    for sig in signals:
        sectors = json.loads(sig.get("target_sectors", "[]"))
        for sec in sectors:
            sector_map[sec].append(sig)
    return sector_map


def _has_multiple_sources(sigs):
    """判断是否有≥2个独立来源"""
    sources = set(s.get("source", "") for s in sigs)
    return len(sources) >= 2


def _chain_score(chain):
    """链评分：用于排序"""
    conf = chain.get("confidence", 0)
    sources = len(chain.get("corroboration", [])) + 1
    sev = {"S1": 100, "S2": 70, "S3": 40, "S4": 15}.get(chain.get("severity", "S4"), 10)
    return conf * sources * sev


# ============================================================
# LLM推理（核心）
# ============================================================
def _llm_reason_causal_chain(sector, signals):
    """调用LLM对板块信号组合进行因果推理"""
    # 清除所有代理环境变量，避免被拦截
    for k in list(os.environ.keys()):
        if 'proxy' in k.lower():
            os.environ.pop(k, None)

    api_base = config.AI_ENGINE.get("api_base", "")
    api_key = config.AI_ENGINE.get("api_key", "")
    model = config.AI_ENGINE.get("model", "MiniMax-M2.7")

    if not api_base or not api_key or not config.AI_ENGINE.get("enabled"):
        return _rule_based_chain(sector, signals)

    try:
        import requests as req

        # 构造信号摘要
        signal_summary = []
        for s in signals:
            signal_summary.append({
                "source": s.get("source"),
                "description": s.get("description", ""),
                "direction": s.get("direction"),
                "confidence": s.get("confidence", 0),
                "severity": s.get("severity", "S4"),
                "timestamp": s.get("timestamp", ""),
            })

        # 按来源去重（同来源多条信号只保留最强的）
        best_per_source = {}
        for s in signal_summary:
            src = s["source"]
            if src not in best_per_source or s["confidence"] > best_per_source[src]["confidence"]:
                best_per_source[src] = s
        signal_summary = list(best_per_source.values())

        user_msg = f"""板块「{sector}」有以下多源信号，请分析因果传导关系：

```json
{json.dumps(signal_summary, ensure_ascii=False, indent=2)}
```

请按你的传导分析框架，输出该板块的最佳因果链。"""

        url = f"{api_base}/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": CAUSAL_CHAIN_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            "max_tokens": 1200,
            "temperature": 0.2,
        }
        session = req.Session()
        session.trust_env = False
        resp = session.post(url, json=payload, headers=headers, timeout=45)

        if resp.status_code == 200:
            data = resp.json()
            content = (data.get("choices", [{}])[0]
                       .get("message", {}).get("content", ""))
            if content:
                # 提取JSON
                chains = _extract_json(content)
                if chains:
                    return chains
        else:
            print(f"  ⚠ 因果链LLM返回 {resp.status_code}")

    except Exception as e:
        print(f"  ⚠ 因果链推理异常: {e}")

    # fallback: 规则引擎
    return _rule_based_chain(sector, signals)


def _extract_json(content):
    """从LLM输出中提取JSON"""
    # 尝试找 ```json ... ``` 包裹的内容
    import re
    match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1))
            return data.get("chains", [])
        except Exception:
            pass

    # 尝试直接解析
    match = re.search(r'\{.*"chains".*\}', content, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group())
            return data.get("chains", [])
        except Exception:
            pass

    return None


# ============================================================
# 规则引擎降级方案（无LLM或LLM失败时）
# ============================================================
def _rule_based_chain(sector, signals):
    """基于规则的因果链（无LLM时的降级方案）"""
    stocks_map = {
        '光模块': '中际旭创/新易盛', '服务器': '工业富联/浪潮信息',
        'PCB': '深南电路/兴森科技', '封装': '长电科技/通富微电',
        '液冷': '英维克', '国产算力': '寒武纪/海光信息',
        '锡': '锡业股份', '铜': '紫金矿业', '铜缆': '沃尔核材',
    }

    # 传导机制规则库
    mechanism_rules = {
        'overseas': {
            '服务器': ('AI服务器需求预期↓', '海外暴跌→A股情绪跟跌，隔夜传导'),
            '光模块': ('光模块需求预期↓', 'Broadcom/TSM暴跌→光模块链承压'),
            'PCB': ('HPC/AI板需求预期↓', '博通暴跌→PCB需求预期下修'),
            '封装': ('先进封装需求预期↓', '台积电暴跌→先进封装链承压'),
            '液冷': ('液冷需求预期↓', 'SMCI暴跌→液冷需求疑虑'),
            '国产算力': ('国产替代逻辑↓', 'ASML暴跌→国产替代压力'),
        },
        'inventory': {
            '锡': ('封装材料成本↓', '锡库存降→供给收缩→锡价支撑→封装成本改善'),
            '铜': ('铜缆/PCB成本↓', '铜库存降→铜价支撑→成本压力缓解'),
        },
        'capital': {
            '光模块': ('机构净买入↑', '融资余额激增→杠杆资金入场'),
            'PCB': ('机构净买入↑', '龙虎榜机构席位净买入→领先信号'),
            '锡': ('机构净买入↑', '融资余额激增→资金关注'),
        },
    }

    chains = []
    sources = set(s.get("source", "") for s in signals)
    best_conf = max((s.get("confidence", 0) for s in signals), default=0)
    best_sev = min(
        (s.get("severity", "S4") for s in signals),
        key=lambda x: {"S1": 1, "S2": 2, "S3": 3, "S4": 4}.get(x, 5)
    )
    direction = signals[0].get("direction", "neutral")

    # 获取主信号
    primary_sig = max(signals, key=lambda s: s.get("confidence", 0))

    for src in sources:
        rules = mechanism_rules.get(src, {})
        if sector in rules:
            mechanism, reason = rules[sector]
            chains.append({
                "driver": primary_sig.get("description", "")[:40] or f"{src}信号",
                "driver_source": src,
                "mechanism": mechanism,
                "target_sector": sector,
                "target_stocks": stocks_map.get(sector, ""),
                "direction": direction,
                "confidence": round(best_conf * 0.9, 3),
                "severity": best_sev,
                "corroboration": list(sources),
                "historical_analogy": "",
                "action": "回避" if direction == "bearish" else "关注",
                "action_reason": reason,
            })
            break  # 只取第一个匹配的

    return chains


if __name__ == "__main__":
    chains = generate_causal_chains()
    print("=" * 60)
    print(f"因果传导链 ({len(chains)}条)")
    print("=" * 60)
    for i, c in enumerate(chains, 1):
        print(f"\n【链{i}】{c['driver']}")
        print(f"  机制: {c['mechanism']}")
        print(f"  板块: {c['target_sector']} ({c['target_stocks']})")
        print(f"  方向: {c['direction']} | 置信度: {c['confidence']} | 等级: {c['severity']}")
        print(f"  印证: {' + '.join(c['corroboration'])}")
        print(f"  建议: {c['action']} - {c['action_reason']}")