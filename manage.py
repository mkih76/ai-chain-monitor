#!/usr/bin/env python3
"""
AI产业链监控 - 管理工具
用法:
  python manage.py run              # 完整运行
  python manage.py test             # 测试采集
  python manage.py report           # 生成报告
  python manage.py inventory --tin 4500 --copper 35000  # 手动录入库存
  python manage.py signals          # 查看未发送信号
  python manage.py history          # 查看历史信号
  python manage.py stock 000960     # 查看单只股票数据
  python manage.py calendar         # 查看近期日历事件
  python manage.py add-event --date 2025-07-15 --event "某公司财报" --impact "光模块,服务器"
"""
import sys
import os
import json
import argparse
from datetime import datetime, timedelta

sys.path.insert(0, "/opt/ai-monitor")
from db import init_db, get_unsent_signals, get_stock_history, get_inventory_history
import config

def cmd_run():
    from main import run_full
    run_full()

def cmd_test():
    from main import run_test
    run_test()

def cmd_report():
    from main import run_report
    run_report()

def cmd_inventory(args):
    init_db()
    from collectors.inventory_collector import manual_inventory
    tin = int(args.tin) if args.tin else None
    copper = int(args.copper) if args.copper else None
    if tin is None and copper is None:
        print("请指定库存值: --tin 4500 或 --copper 35000")
        return
    manual_inventory(tin=tin, copper=copper, date_str=args.date)

def cmd_signals():
    init_db()
    signals = get_unsent_signals()
    if not signals:
        print("✅ 无待发送信号")
        return
    for s in signals:
        icon = {"critical": "🔴", "high": "🟠", "medium": "🟡"}.get(s["severity"], "⚪")
        print(f"{icon} [{s['id']}] {s['title']}")
        print(f"   {s['detail']}")
        print(f"   时间: {s['timestamp']} | 类型: {s['type']}")
        print()

def cmd_history(args):
    init_db()
    import sqlite3
    conn = sqlite3.connect("/opt/ai-monitor/data/monitor.db")
    conn.row_factory = sqlite3.Row
    limit = args.limit or 20
    rows = conn.execute("SELECT * FROM signals ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    if not rows:
        print("暂无历史信号")
        return
    for r in rows:
        icon = {"critical": "🔴", "high": "🟠", "medium": "🟡"}.get(r["severity"], "⚪")
        sent = "✓已发" if r["sent"] else "⏳待发"
        print(f"{icon} [{r['timestamp'][:16]}] {r['title']}  {sent}")

def cmd_stock(args):
    init_db()
    code = args.code
    name = config.WATCHLIST.get(code, (code, ""))[0]
    history = get_stock_history(code, days=args.days or 20)
    if not history:
        print(f"无 {name}({code}) 的历史数据")
        return
    print(f"\n📊 {name}({code}) 近{len(history)}日数据:")
    print(f"{'日期':<12} {'开盘':>8} {'最高':>8} {'最低':>8} {'收盘':>8} {'成交量':>12}")
    print("-" * 60)
    for h in history:
        print(f"{h['date']:<12} {h['open']:>8.2f} {h['high']:>8.2f} "
              f"{h['low']:>8.2f} {h['close']:>8.2f} {h['volume']:>12.0f}")

def cmd_calendar():
    today = datetime.now().date()
    print(f"\n📅 近期日历事件 (今天: {today}):")
    print(f"{'日期':<12} {'距今':>6} {'事件':<30} {'影响板块'}")
    print("-" * 70)
    for event in sorted(config.CALENDAR_EVENTS, key=lambda e: e["date"]):
        event_date = datetime.strptime(event["date"], "%Y-%m-%d").date()
        days = (event_date - today).days
        status = "🔔今天" if days == 0 else (f"⏳{days}天后" if days > 0 else f"已过{-days}天")
        impact = ", ".join(event["impact"])
        print(f"{event['date']:<12} {status:>6} {event['event']:<30} {impact}")

def cmd_add_event(args):
    config.CALENDAR_EVENTS.append({
        "date": args.date,
        "event": args.event,
        "impact": args.impact.split(","),
        "type": "custom",
    })
    print(f"✓ 已添加事件: {args.date} - {args.event}")

def cmd_ai():
    """AI多维关联分析"""
    init_db()
    from analyzers.ai_engine import run_ai_analysis
    print("🤖 AI多维关联分析...")
    result = run_ai_analysis(mode="global")
    if result:
        direction = result.get("direction", "N/A")
        confidence = result.get("confidence", "N/A")
        print(f"\n整体研判: {direction} 置信度:{confidence}")
        if result.get("top_picks"):
            print("\n重点关注:")
            for pick in result["top_picks"]:
                icon = "📈" if pick.get("direction") == "bullish" else "📉"
                print(f"  {icon} {pick.get('name', '')}({pick.get('code', '')}): {pick.get('reason', '')}")
        if result.get("catalyst"):
            print(f"\n催化剂: {result['catalyst']}")
        if result.get("risk"):
            print(f"风险: {result['risk']}")
    else:
        print("  AI分析无结果（检查MiMo Proxy配置）")

def cmd_upstream(args):
    """查看上游产业数据"""
    init_db()
    from db import get_upstream_latest
    source = args.source if hasattr(args, "source") else "all"

    sources_map = {
        "tsmc": ("TSMC月营收", "tsmc", "monthly_revenue_twd_mn"),
        "lme": ("LME库存", "lme", None),
        "dram": ("DRAM价格", "dram_market", None),
    }

    if source == "all":
        targets = list(sources_map.items())
    else:
        targets = [(source, sources_map[source])]

    print("\n📈 上游产业数据:")
    print(f"{'来源':<15} {'日期':<12} {'指标':<25} {'数值':>15} {'YoY':>8} {'MoM':>8}")
    print("-" * 80)

    for key, (label, db_source, db_metric) in targets:
        if db_metric:
            data = get_upstream_latest(db_source, db_metric, limit=5)
        else:
            from db import get_conn
            conn = get_conn()
            rows = conn.execute(
                "SELECT * FROM upstream_data WHERE source=? ORDER BY date DESC LIMIT 5",
                (db_source,)
            ).fetchall()
            conn.close()
            data = [dict(r) for r in rows]

        for d in data:
            yoy = f"{d.get('yoy_change', 0):+.1f}%" if d.get("yoy_change") else "-"
            mom = f"{d.get('mom_change', 0):+.1f}%" if d.get("mom_change") else "-"
            print(f"{label:<15} {d['date']:<12} {d['metric']:<25} {d['value']:>15,.0f} {yoy:>8} {mom:>8}")

    if not any(get_upstream_latest(s, m, limit=1) for _, s, m in sources_map.values()):
        print("  暂无上游数据，请先运行: python manage.py collect upstream")

def cmd_overseas():
    """查看海外标的行情"""
    init_db()
    from db import get_overseas_history

    print("\n🌏 海外标的行情:")
    print(f"{'标的':<15} {'最新价':>10} {'涨跌幅':>8} {'盘后价':>10} {'盘后涨跌':>8}")
    print("-" * 55)

    for symbol, info in config.OVERSEAS_STOCKS.items():
        history = get_overseas_history(symbol, days=1)
        if history:
            latest = history[0]
            close = latest.get("close", 0)
            chg = latest.get("change_pct", 0) or 0
            ah_price = latest.get("after_hours_price")
            ah_chg = latest.get("after_hours_change_pct")

            chg_str = f"{chg:+.1f}%"
            ah_price_str = f"${ah_price:.2f}" if ah_price else "-"
            ah_chg_str = f"{ah_chg:+.1f}%" if ah_chg else "-"

            icon = "🟢" if chg > 0 else ("🔴" if chg < 0 else "⚪")
            print(f"{icon} {info['name']:<12} ${close:>8.2f} {chg_str:>8} {ah_price_str:>10} {ah_chg_str:>8}")
        else:
            print(f"⚪ {info['name']:<12} {'N/A':>10}")

    print(f"\n影响映射:")
    for symbol, info in config.OVERSEAS_STOCKS.items():
        print(f"  {info['name']}({symbol}) → {', '.join(info['affects'])}")

def cmd_collect(args):
    """仅采集数据"""
    init_db()
    if args.source == "stock":
        from collectors.stock_collector import collect_all
        collect_all()
    elif args.source == "inventory":
        from collectors.inventory_collector import collect_inventory
        collect_inventory()
    elif args.source == "news":
        from collectors.news_collector import collect_news
        news = collect_news()
        for n in news[:10]:
            icon = "🔴" if n.get("relevance") == "high" else "🟡"
            ai_tag = ""
            if n.get("ai_direction"):
                ai_tag = f" AI:{n['ai_direction']}({n.get('ai_confidence', '')})"
            print(f"{icon} [{n.get('score', 0)}] {n['title']}{ai_tag}")
    elif args.source == "upstream":
        from collectors.upstream_collector import collect_upstream_data
        collect_upstream_data()
    elif args.source == "overseas":
        from collectors.overseas_collector import collect_overseas_stocks
        collect_overseas_stocks()
    else:
        from collectors.stock_collector import collect_all
        from collectors.inventory_collector import collect_inventory
        from collectors.news_collector import collect_news
        from collectors.upstream_collector import collect_upstream_data
        from collectors.overseas_collector import collect_overseas_stocks
        collect_all()
        collect_inventory()
        collect_upstream_data()
        collect_overseas_stocks()
        collect_news()

def main():
    parser = argparse.ArgumentParser(description="AI产业链监控管理工具")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("run", help="完整运行")
    sub.add_parser("test", help="测试采集")
    sub.add_parser("report", help="生成报告")

    p_inv = sub.add_parser("inventory", help="手动录入库存")
    p_inv.add_argument("--tin", type=int, help="锡库存(吨)")
    p_inv.add_argument("--copper", type=int, help="铜库存(吨)")
    p_inv.add_argument("--date", type=str, help="日期(YYYYMMDD)")

    sub.add_parser("signals", help="查看待发送信号")

    p_hist = sub.add_parser("history", help="查看历史信号")
    p_hist.add_argument("--limit", type=int, default=20)

    p_stock = sub.add_parser("stock", help="查看股票数据")
    p_stock.add_argument("code", help="股票代码")
    p_stock.add_argument("--days", type=int, default=20)

    sub.add_parser("calendar", help="查看日历事件")

    p_event = sub.add_parser("add-event", help="添加日历事件")
    p_event.add_argument("--date", required=True)
    p_event.add_argument("--event", required=True)
    p_event.add_argument("--impact", required=True, help="影响板块，逗号分隔")

    p_collect = sub.add_parser("collect", help="采集数据")
    p_collect.add_argument("source", nargs="?", default="all",
                          choices=["all", "stock", "inventory", "news", "upstream", "overseas"])

    # 新增: AI分析命令
    sub.add_parser("ai", help="AI多维关联分析")

    # 新增: 上游数据查看
    p_upstream = sub.add_parser("upstream", help="查看上游产业数据")
    p_upstream.add_argument("--source", default="all",
                           choices=["all", "tsmc", "lme", "dram"])

    # 新增: 海外标的查看
    sub.add_parser("overseas", help="查看海外标的行情")

    args = parser.parse_args()

    cmds = {
        "run": cmd_run, "test": cmd_test, "report": cmd_report,
        "inventory": lambda: cmd_inventory(args),
        "signals": cmd_signals, "history": lambda: cmd_history(args),
        "stock": lambda: cmd_stock(args), "calendar": cmd_calendar,
        "add-event": lambda: cmd_add_event(args),
        "collect": lambda: cmd_collect(args),
        "ai": cmd_ai, "upstream": lambda: cmd_upstream(args),
        "overseas": cmd_overseas,
    }

    if args.command in cmds:
        cmds[args.command]()
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
