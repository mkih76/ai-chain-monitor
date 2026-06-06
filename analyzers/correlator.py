"""
M4 · 关联分析引擎（中枢）
接收所有检测器的Signal，做交叉验证，计算综合置信度

核心逻辑：
- 同一板块内，不同来源的信号互相印证
- 多源独立信号的置信度合并: P = 1 - Π(1 - Pi)
- 3源共振 → S1级信号
- 信号之间建立corroboration关系
"""
import sys
import os
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models import Signal, Severity, Direction, SignalSource
from db import (get_conn, init_db, insert_signal_v2, get_active_signals,
                update_signal_corroboration, expire_old_signals)
import json


def run_correlation(signals: list) -> list:
    """
    关联分析主入口

    输入: 各检测器产生的原始Signal列表
    输出: 经关联增强后的Signal列表（原地修改confidence和severity，并持久化）

    流程:
    1. 按板块分组
    2. 板块内按来源去重（同一来源只取最强信号）
    3. 多源信号互相印证 → 提升置信度和severity
    4. 持久化到数据库
    """
    if not signals:
        return []

    init_db()

    # 过期老信号
    expire_old_signals()

    # Step 1: 按板块分组
    sector_groups = defaultdict(list)
    for sig in signals:
        for sector in sig.target_sectors:
            sector_groups[sector].append(sig)
        # 没有板块的信号也保留，按标的分组
        if not sig.target_sectors:
            sector_groups["_unclassified"].append(sig)

    enhanced_signals = []

    for sector, group_signals in sector_groups.items():
        if sector == "_unclassified":
            # 未分类信号直接保存
            for sig in group_signals:
                insert_signal_v2(sig)
                enhanced_signals.append(sig)
            continue

        # Step 2: 按来源去重（同一来源取最强信号）
        by_source = {}
        for sig in group_signals:
            src = sig.source
            if src not in by_source or sig.confidence > by_source[src].confidence:
                by_source[src] = sig

        unique_signals = list(by_source.values())

        # Step 3: 多源印证
        if len(unique_signals) >= 2:
            # 计算综合置信度（假设独立信号）
            combined_conf = 1.0
            for sig in unique_signals:
                combined_conf *= (1 - sig.confidence)
            combined_conf = 1 - combined_conf

            # 来源数量加成
            if len(unique_signals) >= 3:
                combined_conf = min(combined_conf * 1.2, 0.99)
                new_severity = Severity.S1_CRITICAL
            elif len(unique_signals) >= 2:
                combined_conf = min(combined_conf * 1.1, 0.95)
                new_severity = Severity.S2_HIGH
            else:
                new_severity = Severity.S3_MEDIUM

            # 判断方向一致性
            directions = set(s.direction for s in unique_signals)
            if len(directions) == 1:
                # 方向一致，增强
                direction = unique_signals[0].direction
            elif Direction.NEUTRAL in directions:
                # 有中性的，取非中性方向
                direction = [d for d in directions if d != Direction.NEUTRAL][0]
            else:
                # 方向冲突，降级
                new_severity = Severity.S4_WATCH
                direction = Direction.NEUTRAL
                combined_conf *= 0.5

            # 合并描述
            source_desc = " + ".join(f"[{_source_name(s.source)}]{s.type}" for s in unique_signals)
            merged_desc = (
                f"{sector}板块多源共振({len(unique_signals)}源): "
                + "; ".join(s.description for s in unique_signals)
            )

            # 合并标的（去重）
            all_stocks = []
            for s in unique_signals:
                all_stocks.extend(s.target_stocks)
            all_stocks = list(dict.fromkeys(all_stocks))  # 保序去重

            # 合并原始数据
            merged_raw = {}
            for s in unique_signals:
                merged_raw[f"{s.source}_{s.type}"] = s.raw_data

            # 创建增强信号
            enhanced = Signal(
                source="correlator",
                type_=f"multi_source_{sector}",
                target_stocks=all_stocks,
                target_sectors=[sector],
                direction=direction,
                severity=new_severity,
                description=merged_desc,
                raw_data=merged_raw,
                lead_time_days=min(s.lead_time_days for s in unique_signals),
                confidence=round(combined_conf, 3),
                strength=min(sum(s.strength for s in unique_signals) / len(unique_signals) * 1.2, 99),
            )

            # 建立互相佐证关系
            for sig in unique_signals:
                sig.corroboration.append(enhanced.id)
                enhanced.corroboration.append(sig.id)

            # 保存所有信号
            for sig in unique_signals:
                insert_signal_v2(sig)
            insert_signal_v2(enhanced)
            enhanced_signals.append(enhanced)

        else:
            # 单源信号，直接保存
            for sig in unique_signals:
                insert_signal_v2(sig)
                enhanced_signals.append(sig)

    return enhanced_signals


def _source_name(source):
    """来源代码转中文"""
    names = {
        "inventory": "库存",
        "capital": "资金",
        "commodity": "商品",
        "announcement": "公告",
        "overseas": "海外",
        "news": "新闻",
    }
    return names.get(source, source)


def get_sector_summary():
    """
    获取板块信号汇总（供前端展示）
    返回: {sector: {signals: [...], max_severity, combined_confidence, direction}}
    """
    active = get_active_signals()
    by_sector = defaultdict(list)

    for sig_data in active:
        sectors = json.loads(sig_data.get("target_sectors", "[]"))
        for sector in sectors:
            by_sector[sector].append(sig_data)

    summary = {}
    for sector, sigs in by_sector.items():
        severity_order = {"S1": 1, "S2": 2, "S3": 3, "S4": 4}
        best = min(sigs, key=lambda s: severity_order.get(s.get("severity", "S4"), 5))
        confidences = [s.get("confidence", 0) for s in sigs]

        summary[sector] = {
            "signal_count": len(sigs),
            "source_count": len(set(s.get("source") for s in sigs)),
            "max_severity": best.get("severity"),
            "direction": best.get("direction"),
            "combined_confidence": round(
                1 - prod(1 - c for c in confidences), 3
            ) if confidences else 0,
            "signals": sigs,
        }

    return summary


def prod(values):
    """连乘"""
    result = 1
    for v in values:
        result *= v
    return result


if __name__ == "__main__":
    # 测试：手动创建几个信号测试关联
    from models import Signal, Severity, Direction, SignalSource

    test_signals = [
        Signal(
            source=SignalSource.INVENTORY,
            type_="inventory_decline",
            target_stocks=["000960"],
            target_sectors=["锡"],
            direction=Direction.BULLISH,
            severity=Severity.S3_MEDIUM,
            description="锡库存连续3周下降",
            confidence=0.7,
            strength=65,
        ),
        Signal(
            source=SignalSource.CAPITAL,
            type_="northbound_consecutive",
            target_stocks=["000960"],
            target_sectors=["锡"],
            direction=Direction.BULLISH,
            severity=Severity.S3_MEDIUM,
            description="北向连续3天买入锡业股份",
            confidence=0.6,
            strength=55,
        ),
        Signal(
            source=SignalSource.COMMODITY,
            type_="commodity_surge",
            target_stocks=["000960"],
            target_sectors=["锡"],
            direction=Direction.BULLISH,
            severity=Severity.S3_MEDIUM,
            description="沪锡今日+3.5%",
            confidence=0.55,
            strength=50,
        ),
    ]

    enhanced = run_correlation(test_signals)
    print(f"\n关联分析结果: {len(enhanced)} 个信号")
    for s in enhanced:
        print(f"  {s.severity} | conf={s.confidence} | {s.description[:60]}...")
