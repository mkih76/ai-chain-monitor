#!/usr/bin/env python3
"""
AI产业链监控系统 - 主程序
用法:
  python main.py              # 完整运行（采集+分析+推送）
  python main.py collect      # 仅采集数据
  python main.py analyze      # 仅分析信号
  python main.py report       # 生成报告
  python main.py test         # 测试运行
"""
import sys
import os
import json
from datetime import datetime

sys.path.insert(0, "/opt/ai-monitor")
from db import init_db, get_unsent_signals, mark_signal_sent
from collectors.stock_collector import collect_all as collect_stocks
from collectors.inventory_collector import collect_inventory
from analyzers.signal_engine import run_all_analysis, run_institutional_analysis, run_full_analysis
from notifiers.telegram_notifier import push_signals, push_daily_summary
import config

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")
    os.makedirs(config.LOG_PATH.rsplit("/", 1)[0], exist_ok=True)
    with open(config.LOG_PATH, "a") as f:
        f.write(f"[{ts}] {msg}\n")

def run_full(institutional=True):
    """完整运行流程"""
    log("=" * 50)
    log("AI产业链监控 - 开始运行")
    log("=" * 50)

    # 1. 初始化数据库
    init_db()

    # 2. 采集数据
    log(">>> 第1步: 采集数据")
    stock_data = collect_stocks()
    inventory_data = collect_inventory()

    # 3. 分析信号
    log(">>> 第2步: 分析信号")
    if institutional:
        signals = run_full_analysis()
    else:
        signals = run_all_analysis()

    # 4. 推送通知
    log(">>> 第3步: 推送通知")
    if signals:
        push_signals(signals)
    else:
        log("  无信号需要推送")

    # 5. 标记已发送
    unsent = get_unsent_signals()
    for s in unsent:
        mark_signal_sent(s["id"])

    # 6. 输出摘要
    log(f">>> 运行完成: 股票{len(stock_data)}只, 信号{len(signals)}个")
    log("=" * 50)

    return {
        "stocks": len(stock_data),
        "signals": len(signals),
        "signal_details": signals,
        "inventory": inventory_data,
    }

def run_collect_only():
    """仅采集数据"""
    init_db()
    log("采集股价数据...")
    stock_data = collect_stocks()
    log("采集库存数据...")
    inventory_data = collect_inventory()
    return {"stocks": stock_data, "inventory": inventory_data}

def run_analyze_only():
    """仅分析信号"""
    init_db()
    log("分析信号...")
    signals = run_all_analysis()
    for s in signals:
        icon = {"critical": "🔴", "high": "🟠", "medium": "🟡"}.get(s["severity"], "⚪")
        log(f"  {icon} {s['title']}")
    return signals

def run_report():
    """生成文本报告"""
    init_db()
    signals = run_all_analysis()

    report = []
    report.append(f"📊 AI产业链监控报告")
    report.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    report.append(f"=" * 40)

    if signals:
        for s in signals:
            icon = {"critical": "🔴", "high": "🟠", "medium": "🟡"}.get(s["severity"], "⚪")
            report.append(f"\n{icon} [{s['severity'].upper()}] {s['title']}")
            report.append(f"   {s['detail']}")
    else:
        report.append("\n✅ 无异常信号")

    report.append(f"\n{'=' * 40}")
    report.append(f"共 {len(signals)} 个信号")

    text = "\n".join(report)
    print(text)
    return text

def run_test():
    """测试运行（不推送）"""
    log("🧪 测试模式")
    init_db()

    # 测试股价采集（只取1只）
    log("测试: 采集锡业股份(000960)...")
    from collectors.stock_collector import fetch_kline
    data = fetch_kline("000960", days=5)
    if data:
        log(f"  ✓ 获取 {len(data)} 条数据")
        for d in data:
            log(f"    {d['date']}: 收盘 {d['close']}")
    else:
        log("  ✗ 无数据")

    # 测试库存采集
    log("测试: 采集上期所库存...")
    inv = collect_inventory()

    log("🧪 测试完成")

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "full"

    if mode == "collect":
        run_collect_only()
    elif mode == "analyze":
        run_analyze_only()
    elif mode == "report":
        run_report()
    elif mode == "test":
        run_test()
    else:
        result = run_full()
        # 输出JSON摘要供cron脚本使用
        summary = {
            "timestamp": datetime.now().isoformat(),
            "stocks": result["stocks"],
            "signals": result["signals"],
        }
        print(json.dumps(summary, ensure_ascii=False))
