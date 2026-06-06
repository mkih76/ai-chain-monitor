"""
检测运行器 — 串联所有检测器 + 关联分析
用法:
  python detect_runner.py          # 运行所有检测器
  python detect_runner.py inventory # 只运行库存检测
  python detect_runner.py test      # 测试模式（不保存）
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import init_db, get_active_signals, get_signal_stats
from detectors.inventory_detector import detect_inventory_signals
from detectors.capital_detector import detect_capital_signals
from detectors.commodity_detector import detect_commodity_signals
from detectors.overseas_detector import detect_overseas_signals
from analyzers.correlator import run_correlation
from datetime import datetime


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def run_all_detectors():
    """运行所有检测器，汇总信号"""
    log("=" * 50)
    log("先行信号检测 — 开始")
    log("=" * 50)

    init_db()
    all_signals = []

    # M1 库存检测
    log("M1 · 库存信号检测...")
    try:
        inv_signals = detect_inventory_signals()
        log(f"  → {len(inv_signals)} 个信号")
        all_signals.extend(inv_signals)
    except Exception as e:
        log(f"  ⚠ 库存检测异常: {e}")

    # M2 资金异动检测
    log("M2 · 资金异动检测...")
    try:
        cap_signals = detect_capital_signals()
        log(f"  → {len(cap_signals)} 个信号")
        all_signals.extend(cap_signals)
    except Exception as e:
        log(f"  ⚠ 资金检测异常: {e}")

    # M3 商品期货检测
    log("M3 · 商品期货检测...")
    try:
        com_signals = detect_commodity_signals()
        log(f"  → {len(com_signals)} 个信号")
        all_signals.extend(com_signals)
    except Exception as e:
        log(f"  ⚠ 商品检测异常: {e}")

    # M7 海外映射检测
    log("M7 · 海外映射检测...")
    try:
        os_signals = detect_overseas_signals()
        log(f"  → {len(os_signals)} 个信号")
        all_signals.extend(os_signals)
    except Exception as e:
        log(f"  ⚠ 海外检测异常: {e}")

    log(f"\n原始信号合计: {len(all_signals)} 个")

    # M4 关联分析
    log("\nM4 · 关联分析...")
    enhanced = run_correlation(all_signals)
    log(f"  → 增强后: {len(enhanced)} 个信号")

    # 统计
    stats = get_signal_stats()
    log(f"\n信号库统计:")
    log(f"  活跃: {stats.get('active', 0)}")
    log(f"  已确认: {stats.get('confirmed', 0)}")
    log(f"  已过期: {stats.get('expired', 0)}")
    log(f"  已验证: {stats.get('verified', 0)}")

    # 打印当前活跃信号
    active = get_active_signals()
    if active:
        log(f"\n{'='*50}")
        log(f"活跃信号 ({len(active)} 个):")
        log(f"{'='*50}")
        for sig in active:
            sev = sig.get("severity", "?")
            conf = sig.get("confidence", 0)
            desc = sig.get("description", "")[:70]
            src = sig.get("source", "?")
            log(f"  [{sev}] {src:12s} conf={conf:.2f} | {desc}")

    return enhanced


def run_single(module):
    """运行单个检测器"""
    init_db()
    detectors = {
        "inventory": detect_inventory_signals,
        "capital": detect_capital_signals,
        "commodity": detect_commodity_signals,
        "overseas": detect_overseas_signals,
    }
    if module not in detectors:
        print(f"未知模块: {module}. 可选: {', '.join(detectors.keys())}")
        return []

    signals = detectors[module]()
    print(f"{module} 检测器: {len(signals)} 个信号")
    for s in signals:
        print(f"  {s.severity} | {s.type} | {s.description}")
    return signals


if __name__ == "__main__":
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "test":
            # 测试模式：运行但不保存
            signals = run_all_detectors()
            print(f"\n测试完成，共 {len(signals)} 个信号")
        elif cmd in ("inventory", "capital", "commodity", "overseas"):
            run_single(cmd)
        else:
            print(f"用法: python detect_runner.py [inventory|capital|commodity|overseas|test]")
    else:
        run_all_detectors()
