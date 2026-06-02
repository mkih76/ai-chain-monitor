"""
Telegram 推送通知器 v2
新增: 支持上游/海外信号、AI关联分析结果、信号来源标注
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

def format_signal_report(signals, ai_result=None):
    """格式化信号报告 v2"""
    if not signals:
        return ""

    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    signals.sort(key=lambda s: severity_order.get(s.get("severity", "low"), 9))

    lines = [f"<b>🧠 AI产业链监控报告 v2</b>",
             f"<i>{datetime.now().strftime('%Y-%m-%d %H:%M')}</i>",
             ""]

    # 按严重程度分组
    groups = {"critical": [], "high": [], "medium": [], "low": []}
    for s in signals:
        groups.get(s.get("severity", "low"), groups["low"]).append(s)

    icons = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "⚪"}
    labels = {"critical": "紧急", "high": "重要", "medium": "关注", "low": "信息"}

    # 信号类型分组标签
    type_labels = {
        "price_surge": "价格", "price_drop": "价格", "new_high": "价格",
        "new_low": "价格", "volume_surge": "价格",
        "inventory_decline": "库存", "inventory_critical": "库存",
        "calendar_reminder": "日历", "calendar_today": "日历",
        "val_high_pe": "估值", "val_low_pe": "估值", "val_60d_surge": "估值",
        "val_60d_drop": "估值", "val_mega_cap": "估值",
        "margin_rz_surge": "融资", "margin_rz_drop": "融资",
        "dragon_buy": "龙虎榜", "dragon_sell": "龙虎榜",
        "block_premium": "大宗", "block_discount": "大宗",
        "northbound_inflow": "北向", "northbound_outflow": "北向",
        "northbound_consecutive_buy": "北向连续",
        "overseas_linkage": "海外联动",
        "tsmc_revenue_inflection": "上游TSMC", "tsmc_revenue_boom": "上游TSMC",
        "lme_copper_decline": "上游LME", "lme_tin_decline": "上游LME",
        "dram_price_up": "上游DRAM",
    }

    for level in ["critical", "high", "medium", "low"]:
        group = groups[level]
        if not group:
            continue
        lines.append(f"<b>{icons[level]} {labels[level]}（{len(group)}）</b>")
        for s in group:
            # 添加信号来源标签
            sig_type = s.get("type", "")
            tag = type_labels.get(sig_type, "")
            tag_str = f" [{tag}]" if tag else ""
            lines.append(f"  {s['title']}{tag_str}")
            if s.get("detail"):
                lines.append(f"  <i>{s['detail']}</i>")
            lines.append("")

    # AI关联分析结果 (新增)
    if ai_result:
        lines.append("<b>🤖 AI多维关联分析</b>")
        direction = ai_result.get("direction", "N/A")
        confidence = ai_result.get("confidence", "N/A")
        dir_icon = {"bullish": "📈偏多", "bearish": "📉偏空", "neutral": "➡️中性"}.get(direction, direction)
        lines.append(f"  整体研判: {dir_icon} 置信度:{confidence}")

        if ai_result.get("top_picks"):
            lines.append("  <b>重点关注:</b>")
            for pick in ai_result["top_picks"]:
                pick_icon = "📈" if pick.get("direction") == "bullish" else "📉"
                lines.append(f"    {pick_icon} {pick.get('name', '')}({pick.get('code', '')}): {pick.get('reason', '')}")

        if ai_result.get("catalyst"):
            lines.append(f"  催化剂: {ai_result['catalyst']}")
        if ai_result.get("risk"):
            lines.append(f"  ⚠️ 风险: {ai_result['risk']}")
        lines.append("")

    lines.append(f"<i>共 {len(signals)} 个信号 | v2自动监控</i>")
    return "\n".join(lines)

def format_daily_summary(stock_data, inventory_data):
    """格式化每日摘要"""
    lines = [
        f"<b>📊 AI产业链每日摘要</b>",
        f"<i>{datetime.now().strftime('%Y-%m-%d')}</i>",
        "",
        "<b>🏷 板块涨跌:</b>",
    ]

    sectors = {}
    for code, info in stock_data.items():
        sector = info["sector"]
        if sector not in sectors:
            sectors[sector] = []
        if info.get("latest"):
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

def format_overnight_alert(overnight_changes):
    """格式化隔夜海外异动预警"""
    if not overnight_changes:
        return ""

    lines = ["<b>🌏 海外隔夜异动预警</b>",
             f"<i>{datetime.now().strftime('%Y-%m-%d %H:%M')}</i>", ""]

    for item in overnight_changes:
        icon = "🟢" if item["change_pct"] > 0 else "🔴"
        chg = item["change_pct"]
        affects = ", ".join(item.get("affects", []))
        lines.append(f"{icon} <b>{item['name']}</b>: {chg:+.1f}%")
        lines.append(f"  → 影响A股: {affects}")
        if item.get("note"):
            lines.append(f"  <i>{item['note']}</i>")
        lines.append("")

    return "\n".join(lines)

def push_signals(signals, ai_result=None):
    """推送信号到Telegram"""
    if not signals:
        print("  无信号需要推送")
        return

    text = format_signal_report(signals, ai_result=ai_result)
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

def push_overnight_alert(overnight_changes):
    """推送海外隔夜异动预警"""
    text = format_overnight_alert(overnight_changes)
    if text:
        send_telegram(text)

if __name__ == "__main__":
    test_signals = [
        {"type": "overseas_linkage", "source": "NVIDIA(NVDA)", "title": "🚀 NVIDIA 隔夜大涨 6.5%",
         "detail": "影响A股板块: 光模块, 服务器, 封装, PCB。AI需求总龙头",
         "severity": "high"},
        {"type": "northbound_consecutive_buy", "source": "中际旭创(300308)",
         "title": "💰 中际旭创 北向连续3天净买入",
         "detail": "累计净买入 2.3亿，板块: 光模块", "severity": "medium"},
        {"type": "tsmc_revenue_inflection", "source": "TSMC月度营收",
         "title": "🔄 台积电营收YoY由负转正(+5.2%)",
         "detail": "营收拐点确认，下游封测/光模块3-6个月内大概率跟涨", "severity": "high"},
    ]
    test_ai = {
        "direction": "bullish",
        "confidence": "high",
        "top_picks": [
            {"code": "300308", "name": "中际旭创", "direction": "bullish",
             "reason": "台积电营收拐点+北向连续买入+光模块涨价预期"},
        ],
        "catalyst": "台积电Q2财报超预期",
        "risk": "美国对华芯片出口限制升级",
    }
    push_signals(test_signals, ai_result=test_ai)
