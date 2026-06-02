#!/usr/bin/env python3
"""
AI产业链监控系统 v2 - 主程序
用法:
  python main.py              # 完整运行（采集+分析+推送）
  python main.py collect      # 仅采集数据
  python main.py analyze      # 仅分析信号
  python main.py ai           # AI多维关联分析
  python main.py report       # 生成报告
  python main.py test         # 测试运行
"""
import sys
import os
import json
from datetime import datetime

# Windows GBK编码兼容: 强制stdout使用utf-8
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.insert(0, "/opt/ai-monitor")
from db import init_db, get_unsent_signals, mark_signal_sent
from collectors.stock_collector import collect_all as collect_stocks
from collectors.inventory_collector import collect_inventory
from collectors.news_collector import collect_news
from collectors.upstream_collector import collect_upstream_data
from collectors.overseas_collector import collect_overseas_stocks, get_overnight_changes
from analyzers.signal_engine import (
    run_all_analysis, run_institutional_analysis,
    run_upstream_analysis, run_full_analysis,
)
from analyzers.ai_engine import run_ai_analysis
from notifiers.telegram_notifier import push_signals, push_daily_summary
import config

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    try:
        print(line)
    except UnicodeEncodeError:
        print(line.encode("utf-8", errors="replace").decode("utf-8", errors="replace"))
    os.makedirs(config.LOG_PATH.rsplit("/", 1)[0], exist_ok=True)
    with open(config.LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def run_full(institutional=True, use_ai=True):
    """完整运行流程 v2"""
    log("=" * 50)
    log("AI产业链监控 v2 - 开始运行")
    log("=" * 50)

    # 1. 初始化数据库
    init_db()

    # 2. 采集数据 (新增: 上游产业 + 海外标的)
    log(">>> 第1步: 采集数据")

    # 2a. A股数据
    log("  [1/5] A股行情...")
    stock_data = collect_stocks()

    # 2b. 库存数据
    log("  [2/5] 库存数据...")
    inventory_data = collect_inventory()

    # 2c. 上游产业数据 (新增)
    log("  [3/5] 上游产业数据...")
    upstream_data = collect_upstream_data()

    # 2d. 海外标的行情 (新增)
    log("  [4/5] 海外标的行情...")
    overseas_data = collect_overseas_stocks()

    # 2e. 新闻+AI语义分析 (升级)
    log("  [5/5] 新闻采集+AI分析...")
    news_data = collect_news()

    # 3. 信号分析 (新增: 上游+海外联动)
    log(">>> 第2步: 信号分析")
    if institutional:
        signals = run_full_analysis()
    else:
        signals = run_all_analysis()

    # 4. AI多维关联分析 (新增)
    ai_result = None
    if use_ai and config.AI_ENGINE.get("enabled", False):
        log(">>> 第3步: AI多维关联分析")
        try:
            ai_result = run_ai_analysis(mode="global")
            if ai_result and ai_result.get("top_picks"):
                for pick in ai_result["top_picks"]:
                    icon = "📈" if pick.get("direction") == "bullish" else "📉"
                    log(f"  {icon} {pick.get('name', '')}({pick.get('code', '')}): {pick.get('reason', '')}")
        except Exception as e:
            log(f"  ⚠ AI分析异常: {e}")

    # 5. 推送通知
    log(">>> 第4步: 推送通知")
    if signals:
        push_signals(signals, ai_result=ai_result)
    else:
        log("  无信号需要推送")

    # 6. 标记已发送
    unsent = get_unsent_signals()
    for s in unsent:
        mark_signal_sent(s["id"])

    # 7. 输出摘要
    log(f">>> 运行完成: 股票{len(stock_data)}只, 信号{len(signals)}个, "
        f"上游{len(upstream_data)}条, 海外{len(overseas_data)}只, 新闻{len(news_data)}条")
    log("=" * 50)

    return {
        "stocks": len(stock_data),
        "signals": len(signals),
        "signal_details": signals,
        "inventory": inventory_data,
        "upstream": len(upstream_data),
        "overseas": len(overseas_data),
        "news": len(news_data),
        "ai_result": ai_result,
    }

def run_collect_only():
    """仅采集数据"""
    init_db()
    log("采集股价数据...")
    stock_data = collect_stocks()
    log("采集库存数据...")
    inventory_data = collect_inventory()
    log("采集上游产业数据...")
    upstream_data = collect_upstream_data()
    log("采集海外标的...")
    overseas_data = collect_overseas_stocks()
    log("采集新闻...")
    news_data = collect_news()
    return {
        "stocks": stock_data,
        "inventory": inventory_data,
        "upstream": upstream_data,
        "overseas": overseas_data,
        "news": news_data,
    }

def run_analyze_only():
    """仅分析信号"""
    init_db()
    log("分析信号...")
    signals = run_full_analysis()
    for s in signals:
        icon = {"critical": "🔴", "high": "🟠", "medium": "🟡"}.get(s["severity"], "⚪")
        log(f"  {icon} {s['title']}")
    return signals

def run_ai_only():
    """仅运行AI分析"""
    init_db()
    log("AI多维关联分析...")
    result = run_ai_analysis(mode="global")
    if result:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return result

def run_report():
    """生成文本报告"""
    init_db()
    signals = run_full_analysis()

    report = []
    report.append(f"📊 AI产业链监控报告 v2")
    report.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    report.append(f"=" * 40)

    if signals:
        # 按严重程度分组
        groups = {"critical": [], "high": [], "medium": [], "low": []}
        for s in signals:
            groups.get(s.get("severity", "low"), groups["low"]).append(s)

        icons = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "⚪"}
        labels = {"critical": "紧急", "high": "重要", "medium": "关注", "low": "信息"}

        for level in ["critical", "high", "medium", "low"]:
            group = groups[level]
            if not group:
                continue
            report.append(f"\n{icons[level]} {labels[level]}（{len(group)}）")
            for s in group:
                report.append(f"  {s['title']}")
                if s.get("detail"):
                    report.append(f"    {s['detail']}")
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

    # 测试海外标的
    log("测试: 采集NVDA行情...")
    from collectors.overseas_collector import fetch_yahoo_quote
    quote = fetch_yahoo_quote("NVDA")
    if quote:
        log(f"  ✓ NVDA: ${quote.get('close', 0):.2f} {quote.get('change_pct', 0):+.1f}%")
    else:
        log("  ⚠ NVDA数据不可用")

    # 测试上游数据
    log("测试: 采集TSMC营收...")
    from collectors.upstream_collector import fetch_tsmc_revenue
    tsmc = fetch_tsmc_revenue()
    log(f"  TSMC数据: {len(tsmc)}条")

    log("🧪 测试完成")

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "full"

    if mode == "collect":
        run_collect_only()
    elif mode == "analyze":
        run_analyze_only()
    elif mode == "ai":
        run_ai_only()
    elif mode == "report":
        run_report()
    elif mode == "test":
        run_test()
    else:
        result = run_full()
        summary = {
            "timestamp": datetime.now().isoformat(),
            "stocks": result["stocks"],
            "signals": result["signals"],
            "upstream": result["upstream"],
            "overseas": result["overseas"],
            "news": result["news"],
        }
        print(json.dumps(summary, ensure_ascii=False))
