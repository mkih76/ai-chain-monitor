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
            icon = "🔴" if n["relevance"] == "high" else "🟡"
            print(f"{icon} [{n['score']}] {n['title']}")
    else:
        from collectors.stock_collector import collect_all
        from collectors.inventory_collector import collect_inventory
        from collectors.news_collector import collect_news
        collect_all()
        collect_inventory()
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
                          choices=["all", "stock", "inventory", "news"])

    args = parser.parse_args()

    cmds = {
        "run": cmd_run, "test": cmd_test, "report": cmd_report,
        "inventory": lambda: cmd_inventory(args),
        "signals": cmd_signals, "history": lambda: cmd_history(args),
        "stock": lambda: cmd_stock(args), "calendar": cmd_calendar,
        "add-event": lambda: cmd_add_event(args),
        "collect": lambda: cmd_collect(args),
    }

    if args.command in cmds:
        cmds[args.command]()
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
