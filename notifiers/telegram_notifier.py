"""
Telegram 推送通知器
"""
import requests
import json
from datetime import datetime
import sys
sys.path.insert(0, "/opt/ai-monitor")
import config

def send_telegram(text, parse_mode="HTML"):
    """发送Telegram消息"""
    token = config.NOTIFY.get("telegram_bot_token", "")
    chat_id = config.NOTIFY.get("telegram_chat_id", "")

    if not token or not chat_id:
        print(f"[WARN] Telegram未配置，消息仅打印:")
        print(text)
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code == 200:
            return True
        else:
            print(f"[ERROR] Telegram API: {r.status_code} {r.text}")
            return False
    except Exception as e:
        print(f"[ERROR] Telegram发送失败: {e}")
        return False

def format_signal_report(signals):
    """格式化信号报告"""
    if not signals:
        return ""

    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    signals.sort(key=lambda s: severity_order.get(s.get("severity", "low"), 9))

    lines = [f"<b>🧠 AI产业链监控报告</b>",
             f"<i>{datetime.now().strftime('%Y-%m-%d %H:%M')}</i>",
             ""]

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
        lines.append(f"<b>{icons[level]} {labels[level]}（{len(group)}）</b>")
        for s in group:
            lines.append(f"  {s['title']}")
            if s.get("detail"):
                lines.append(f"  <i>{s['detail']}</i>")
            lines.append("")

    lines.append(f"<i>共 {len(signals)} 个信号 | 自动监控中</i>")
    return "\n".join(lines)

def format_daily_summary(stock_data, inventory_data):
    """格式化每日摘要"""
    lines = [
        f"<b>📊 AI产业链每日摘要</b>",
        f"<i>{datetime.now().strftime('%Y-%m-%d')}</i>",
        "",
        "<b>🏷 板块涨跌:</b>",
    ]

    # 按板块分组
    sectors = {}
    for code, info in stock_data.items():
        sector = info["sector"]
        if sector not in sectors:
            sectors[sector] = []
        if info.get("latest"):
            change = 0
            if info["latest"].get("close") and len(info.get("prev_close", [])) > 0:
                pass
            sectors[sector].append({
                "name": info["name"],
                "close": info["latest"]["close"],
            })

    for sector, stocks in sectors.items():
        names = ", ".join(f"{s['name']}({s['close']})" for s in stocks)
        lines.append(f"  <b>{sector}</b>: {names}")

    if inventory_data:
        lines.append("")
        lines.append("<b>📦 库存数据:</b>")
        for commodity, info in inventory_data.items():
            lines.append(f"  {info.get('product', commodity)}: {info['stockpile']}{info.get('unit', '')}")

    return "\n".join(lines)

def push_signals(signals):
    """推送信号到Telegram"""
    if not signals:
        print("  无信号需要推送")
        return

    text = format_signal_report(signals)
    if text:
        success = send_telegram(text)
        if success:
            print(f"  ✓ 已推送 {len(signals)} 个信号到Telegram")
        else:
            print(f"  ✗ 推送失败，信号已存入数据库")

def push_daily_summary(stock_data, inventory_data):
    """推送每日摘要"""
    text = format_daily_summary(stock_data, inventory_data)
    if text:
        send_telegram(text)

if __name__ == "__main__":
    # 测试
    test_signals = [
        {"type": "test", "source": "test", "title": "🧪 测试信号",
         "detail": "这是一个测试", "severity": "medium"},
    ]
    push_signals(test_signals)
