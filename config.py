"""
AI产业链监控系统 - 配置文件
"""
import os

# === 监控标的 ===
# 格式: (代码, 名称, 板块分类)
WATCHLIST = {
    # 光模块
    "300308": ("中际旭创", "光模块"),
    "300502": ("新易盛", "光模块"),
    # 服务器
    "601138": ("工业富联", "服务器"),
    "000977": ("浪潮信息", "服务器"),
    # PCB
    "002916": ("深南电路", "PCB"),
    "002436": ("兴森科技", "PCB"),
    # 液冷
    "002837": ("英维克", "液冷"),
    # 先进封装
    "600584": ("长电科技", "封装"),
    "002156": ("通富微电", "封装"),
    # 铜缆
    "002130": ("沃尔核材", "铜缆"),
    # 原材料-锡
    "000960": ("锡业股份", "锡"),
    # 原材料-铜
    "601899": ("紫金矿业", "铜"),
    # 国产算力
    "688256": ("寒武纪", "国产算力"),
    "688041": ("海光信息", "国产算力"),
}

# === 信号阈值 ===
SIGNALS = {
    # 股价信号
    "price_surge_pct": 5.0,       # 单日涨幅超过5%触发
    "price_drop_pct": -5.0,       # 单日跌幅超过5%触发
    "price_new_high_days": 60,    # 创60日新高触发
    "price_new_low_days": 60,     # 创60日新低触发
    "volume_surge_ratio": 2.0,    # 成交量超过20日均量2倍触发

    # 库存信号
    "shfe_tin_low_threshold": 5000,   # SHFE锡库存低于5000吨触发（吨）
    "shfe_tin_decline_weeks": 3,      # 连续下降N周触发
    "shfe_copper_low_threshold": 30000,  # SHFE铜库存阈值

    # 财报日历提醒（提前N天）
    "earnings_remind_days": 7,
}

# === 数据源配置 ===
DATA_SOURCES = {
    # 东方财富 - 个股行情API（免费，无需认证）
    "eastmoney_kline": "https://push2his.eastmoney.com/api/qt/stock/kline/get",
    "eastmoney_realtime": "https://push2.eastmoney.com/api/qt/stock/get",
    # 上期所 - 仓单日报
    "shfe_warehouse": "https://www.shfe.com.cn/data/dailydata/kx/kx{date}.dat",
    # 东方财富 - 板块资金流
    "eastmoney_sector": "https://push2.eastmoney.com/api/qt/clist/get",
}

# === 推送配置 ===
NOTIFY = {
    "telegram_bot_token": os.environ.get("TELEGRAM_BOT_TOKEN", ""),
    "telegram_chat_id": os.environ.get("TELEGRAM_CHAT_ID", "2060694836"),
    "enable_telegram": True,
    "enable_log": True,
}

# === 存储 ===
DB_PATH = "/opt/ai-monitor/data/monitor.db"
LOG_PATH = "/opt/ai-monitor/logs/monitor.log"

# === 定时任务 ===
SCHEDULE = {
    "stock_price": "daily_close",       # 每交易日收盘后
    "inventory": "weekly_friday",       # 每周五
    "earnings_calendar": "daily_morning",  # 每早检查
    "news_scan": "twice_daily",         # 早晚各一次
}

# === 关键日历事件 (手动维护 + 自动提醒) ===
CALENDAR_EVENTS = [
    {"date": "2025-07-10", "event": "台积电6月营收公布", "impact": ["封测", "光模块"], "type": "tsmc_revenue"},
    {"date": "2025-07-17", "event": "台积电Q2财报", "impact": ["全产业链"], "type": "earnings"},
    {"date": "2025-07-23", "event": "谷歌/微软Q2财报周", "impact": ["全产业链"], "type": "earnings"},
    {"date": "2025-07-30", "event": "Meta Q2财报", "impact": ["光模块", "服务器"], "type": "earnings"},
    {"date": "2025-08-01", "event": "亚马逊Q2财报", "impact": ["AWS产业链"], "type": "earnings"},
    {"date": "2025-08-18", "event": "Hot Chips大会", "impact": ["芯片设计"], "type": "conference"},
    {"date": "2025-08-31", "event": "A股中报披露截止", "impact": ["A股AI板块"], "type": "earnings"},
    {"date": "2025-11-01", "event": "SC超算大会", "impact": ["液冷/网络"], "type": "conference"},
]
