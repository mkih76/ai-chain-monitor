"""
M6 · 公告雷达信号检测器
基于巨潮资讯原始公告，检测中标/增持/扩产等先行信号

核心逻辑：
- 原始公告比新闻早1-3天（新闻转载有延迟）
- 中标/合同 → 直接利好，金额越大信号越强
- 高管增持/回购 → 内部人看好，最强的看多信号之一
- 产能扩张 → 中长期利好
- 业绩预告 → 短期催化
"""
import sys
import os
import re
import requests
import time
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models import Signal, Severity, Direction, SignalSource
from db import get_conn, init_db
import config


# 公告分类关键词及信号配置
ANNOUNCEMENT_RULES = {
    "contract": {
        "keywords": ["中标", "合同", "订单", "框架协议", "重大合同", "项目中标"],
        "direction": Direction.BULLISH,
        "severity_base": Severity.S3_MEDIUM,
        "severity_boost": Severity.S2_HIGH,  # 金额>1亿时升级
        "lead_time_days": 2,
        "confidence_base": 0.6,
        "extract_amount": True,  # 尝试提取金额
        "description_template": "{name}({code})公告{title}，金额约{amount}",
    },
    "insider_buy": {
        "keywords": ["增持", "回购", "举牌", "控股股东增持", "董事增持", "高管增持"],
        "direction": Direction.BULLISH,
        "severity_base": Severity.S2_HIGH,
        "severity_boost": Severity.S2_HIGH,
        "lead_time_days": 3,
        "confidence_base": 0.7,
        "extract_amount": False,
        "description_template": "{name}({code})公告{title}，内部人看好信号",
    },
    "capacity": {
        "keywords": ["投产", "扩产", "新建产能", "生产线", "产线", "产能建设", "竣工投产"],
        "direction": Direction.BULLISH,
        "severity_base": Severity.S3_MEDIUM,
        "severity_boost": Severity.S3_MEDIUM,
        "lead_time_days": 5,
        "confidence_base": 0.5,
        "extract_amount": False,
        "description_template": "{name}({code})公告{title}，产能扩张",
    },
    "earnings": {
        "keywords": ["预增", "预减", "扭亏", "业绩快报", "业绩预告", "净利润增长"],
        "direction": Direction.BULLISH,  # 需要根据内容判断
        "severity_base": Severity.S3_MEDIUM,
        "severity_boost": Severity.S2_HIGH,
        "lead_time_days": 1,
        "confidence_base": 0.55,
        "extract_amount": False,
        "description_template": "{name}({code})公告{title}",
    },
    "strategic": {
        "keywords": ["战略合作", "合资", "投资设立", "收购", "并购", "参股"],
        "direction": Direction.BULLISH,
        "severity_base": Severity.S3_MEDIUM,
        "severity_boost": Severity.S3_MEDIUM,
        "lead_time_days": 3,
        "confidence_base": 0.45,
        "extract_amount": False,
        "description_template": "{name}({code})公告{title}",
    },
}


def detect_announcement_signals():
    """
    检测公告信号
    1. 从巨潮资讯采集最新公告
    2. 按规则分类并生成信号
    """
    init_db()
    signals = []

    # 采集最新公告
    announcements = _fetch_recent_announcements()
    if not announcements:
        return signals

    for ann in announcements:
        title = ann.get("title", "")
        code = ann.get("code", "")
        name = ann.get("name", "")
        date = ann.get("date", "")
        url = ann.get("url", "")
        sector = config.WATCHLIST.get(code, ("", ""))[1]

        # 匹配公告规则
        for rule_type, rule in ANNOUNCEMENT_RULES.items():
            matched_keyword = None
            for kw in rule["keywords"]:
                if kw in title:
                    matched_keyword = kw
                    break

            if not matched_keyword:
                continue

            # 判断方向（业绩预增=利好，业绩预减=利空）
            direction = rule["direction"]
            if rule_type == "earnings":
                if any(kw in title for kw in ["预减", "预亏", "下降", "减少"]):
                    direction = Direction.BEARISH

            # 尝试提取金额
            amount_str = ""
            severity = rule["severity_base"]
            confidence = rule["confidence_base"]

            if rule.get("extract_amount"):
                amount = _extract_amount(title)
                if amount:
                    amount_str = _format_amount(amount)
                    if amount > 100000000:  # >1亿
                        severity = rule["severity_boost"]
                        confidence = min(confidence + 0.15, 0.9)
                    elif amount > 50000000:  # >5000万
                        confidence = min(confidence + 0.1, 0.85)

            # 生成描述
            desc = rule["description_template"].format(
                name=name, code=code, title=title, amount=amount_str
            )

            signals.append(Signal(
                source=SignalSource.ANNOUNCEMENT,
                type_=f"announcement_{rule_type}",
                target_stocks=[code],
                target_sectors=[sector] if sector else [],
                direction=direction,
                severity=severity,
                description=desc,
                raw_data={
                    "code": code,
                    "name": name,
                    "title": title,
                    "date": date,
                    "url": url,
                    "rule_type": rule_type,
                    "matched_keyword": matched_keyword,
                    "amount": amount_str,
                },
                lead_time_days=rule["lead_time_days"],
                confidence=confidence,
                strength=confidence * 100,
            ))

            break  # 每条公告只匹配一个最高优先级规则

    return signals


def _fetch_recent_announcements():
    """
    从巨潮资讯采集最近3天的公告
    复用已有的cninfo API，但扩展关键词范围
    """
    results = []
    # 扩展的关键词：不仅是行业相关，还要关注重大事件
    important_keywords = [
        "中标", "合同", "订单", "增持", "回购", "举牌",
        "投产", "扩产", "产能", "预增", "扭亏", "业绩",
        "战略合作", "收购", "并购", "投资", "合资",
        "框架协议", "重大合同", "项目", "产品发布",
    ]

    for code, (name, sector) in config.WATCHLIST.items():
        try:
            url = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
            payload = {
                "stock": code,
                "tabName": "fulltext",
                "pageNum": 1,
                "pageSize": 5,
                "column": "szse" if code.startswith(("0", "3")) else "sse",
                "category": "",
                "plate": "",
                "seDate": "",
            }
            r = requests.post(url, data=payload, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://www.cninfo.com.cn/",
                "Accept": "application/json",
            }, timeout=15)

            if r.status_code != 200:
                continue

            data = r.json()
            announcements = data.get("announcements", []) or []

            for ann in announcements:
                raw_title = ann.get("announcementTitle", "")
                # 去除HTML标签
                clean_title = re.sub(r"<[^>]+>", "", raw_title)
                ann_url = (
                    f"https://www.cninfo.com.cn/new/disclosure/detail"
                    f"?stockCode={code}&announcementId={ann.get('announcementId', '')}"
                )
                date_ts = ann.get("announcementTime", 0)
                date_str = (datetime.fromtimestamp(date_ts / 1000).strftime("%Y-%m-%d")
                            if date_ts else "")

                # 只保留重要公告
                if any(kw in clean_title for kw in important_keywords):
                    results.append({
                        "source": "cninfo",
                        "category": "公司公告",
                        "title": clean_title,
                        "url": ann_url,
                        "date": date_str,
                        "code": code,
                        "name": name,
                        "content": "",
                    })

            time.sleep(0.3)  # 避免请求过快
        except Exception:
            pass

    return results


def _extract_amount(text):
    """
    从公告标题中提取金额（单位：元）
    支持格式: "3.5亿元" "3500万元" "3.5亿" 等
    """
    patterns = [
        (r"([\d.]+)\s*亿", 100000000),
        (r"([\d.]+)\s*万", 10000),
        (r"([\d,.]+)\s*元", 1),
    ]
    for pattern, multiplier in patterns:
        match = re.search(pattern, text)
        if match:
            try:
                num_str = match.group(1).replace(",", "")
                return float(num_str) * multiplier
            except ValueError:
                continue
    return None


def _format_amount(amount):
    """格式化金额为可读字符串"""
    if amount >= 100000000:
        return f"{amount / 100000000:.2f}亿"
    elif amount >= 10000:
        return f"{amount / 10000:.0f}万"
    else:
        return f"{amount:.0f}元"


if __name__ == "__main__":
    signals = detect_announcement_signals()
    print(f"公告雷达检测器产生 {len(signals)} 个信号:")
    for s in signals:
        print(f"  {s.severity} | {s.type} | {s.description}")
