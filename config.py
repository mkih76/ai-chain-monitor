"""
AI产业链监控系统 - 配置文件
包含: 监控标的、信号阈值、数据源、推送、上游产业、海外联动、AI分析引擎
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

# === 海外标的映射 ===
# 海外龙头标的 → A股受益板块，用于跨市场联动分析
OVERSEAS_STOCKS = {
    "NVDA": {
        "name": "NVIDIA",
        "affects": ["光模块", "服务器", "封装", "PCB"],
        "note": "AI需求总龙头，A股AI板块定价锚点",
    },
    "TSM": {
        "name": "台积电",
        "affects": ["封装", "光模块", "PCB"],
        "note": "产能分配决定下游出货量",
    },
    "AVGO": {
        "name": "Broadcom",
        "affects": ["光模块", "PCB"],
        "note": "定制芯片(ASIC)需求，光模块替代逻辑",
    },
    "MU": {
        "name": "美光科技",
        "affects": ["服务器"],
        "note": "存储价格风向标",
    },
    "SMCI": {
        "name": "Super Micro",
        "affects": ["服务器", "液冷"],
        "note": "AI服务器出货量直接指标",
    },
    "ASML": {
        "name": "ASML",
        "affects": ["封装", "国产算力"],
        "note": "设备订单领先产能6-9个月",
    },
}

# === 上游产业数据源 ===
UPSTREAM_SOURCES = {
    # TSMC月度营收（每月10日前公布）
    "tsmc_revenue": {
        "url": "https://investor.tsmc.com/english/quarterly-results",
        "description": "台积电月度营收，领先下游封测/光模块3-6个月",
        "frequency": "monthly",
    },
    # LME铜库存
    "lme_copper": {
        "url": "https://www.lme.com/en/market-data/reports-and-data/stocks",
        "description": "LME铜库存，全球铜供需指标",
        "frequency": "daily",
    },
    # LME锡库存
    "lme_tin": {
        "url": "https://www.lme.com/en/market-data/reports-and-data/stocks",
        "description": "LME锡库存，全球锡供需指标",
        "frequency": "daily",
    },
    # DRAM/NAND现货价格 (TrendForce)
    "dram_price": {
        "url": "https://www.trendforce.com/presscenter",
        "description": "存储芯片现货价格，领先服务器板块2-4周",
        "frequency": "weekly",
    },
}

# === 财联社电报配置 ===
CLS_TELEGRAPH = {
    "api": "https://www.cls.cn/nodeapi/updateTelegraph",
    "keywords": ["AI", "算力", "芯片", "半导体", "光模块", "服务器", "铜", "锡",
                  "数据中心", "英伟达", "GPU", "CoWoS", "封装", "液冷", "PCB"],
}

# === AI分析引擎配置 ===
AI_ENGINE = {
    "enabled": True,
    # MiMo LLM Proxy (本地免费)
    "mimo_proxy_url": os.environ.get("MIMO_PROXY_URL", "http://localhost:3001/open-apis/bot/chat"),
    "mimo_service_token": os.environ.get("MIMO_SERVICE_TOKEN", ""),
    "mimo_user_id": os.environ.get("MIMO_USER_ID", ""),
    "mimo_cookie": os.environ.get("MIMO_COOKIE", ""),
    # 分析参数
    "max_news_per_batch": 20,       # 每批最多分析N条新闻
    "confidence_threshold": "medium",  # 推送最低置信度
    "multi_signal_min": 3,          # 多信号共振最低维度数
}

# === 北向资金连续监控参数 ===
NORTHBOUND_PARAMS = {
    "consecutive_days": 3,     # 连续N天净买入同一股票触发
    "net_buy_threshold": 5e7,  # 单日净买入阈值(元)
    "total_net_alert": 1e8,    # 总净流入预警线(万元=100亿)
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
