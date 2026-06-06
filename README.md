# AI产业链先行信号雷达

> 在新闻出来之前，从原始数据中捕捉价格驱动信号。
> 新闻是验证手段，不是信息来源。

## 核心理念

新闻和研报是**滞后指标**——你看到"某贵金属大涨"时，进场已经算追高。
本系统从**先行指标**中提取信号：

| 数据源 | 为什么领先 | 领先天数 |
|--------|-----------|---------|
| **SHFE/LME库存** | 库存连续下降→供需紧张→价格滞后上涨 | 5-8天 |
| **北向资金** | 外资有信息优势，连续买入=提前布局 | 3-5天 |
| **龙虎榜机构席位** | 机构专用席位大额买入=消息面前建仓 | 3-5天 |
| **商品期货** | 铜/锡期货异动→传导到A股有时滞 | 1-3天 |
| **巨潮公告** | 中标/增持/扩产公告比新闻早1-3天 | 1-3天 |
| **海外龙头** | NVDA盘后异动→A股次日开盘前12h窗口 | 1天 |

## 信号流水线

```
原始数据 ──→ 异常检测 ──→ 多源关联 ──→ AI研判 ──→ 推送/展示
 (采集)       (检测)       (交叉验证)    (综合判断)   (行动建议)
```

## 快速开始

```bash
git clone https://github.com/mkih76/ai-chain-monitor.git
cd ai-chain-monitor
pip install flask flask-cors apscheduler requests beautifulsoup4 lxml

# 采集数据
python main.py collect

# 运行信号检测
python detect_runner.py

# 启动Web服务
python web/app.py
# 浏览器访问 http://localhost:8795/radar
```

## 信号分级

| 级别 | 条件 | 示例 |
|------|------|------|
| **S1 临界** | 多源共振(≥3) + 置信度>0.8 | 库存暴降 + 北向买入 + 期货异动同指一个板块 |
| **S2 高** | 单源强信号 + 1个佐证 | 机构席位净买入>1亿 + 融资余额增加 |
| **S3 中** | 单源中等信号 | 北向连续3天买入某标的 |
| **S4 观察** | 弱信号/待确认 | 股吧热度上升 |

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Flask + APScheduler + SQLite |
| 前端 | Alpine.js + ECharts + GSAP (纯CDN) |
| AI分析 | MiMo LLM Proxy (可选) |
| 数据源 | 新浪/腾讯/东方财富/SHFE/Yahoo Finance |

## 文件结构

```
ai-chain-monitor/
├── config.py                # 配置（标的/阈值/API）
├── db.py                    # 数据库（信号v2表+历史表）
├── models.py                # 信号对象定义
├── main.py                  # 数据采集主入口
├── detect_runner.py         # 信号检测运行器
├── collectors/              # 数据采集层
│   ├── stock_collector.py       # A股行情
│   ├── inventory_collector.py   # SHFE/LME库存
│   ├── institutional_collector.py # 北向/龙虎/融资
│   ├── material_collector.py    # 商品期货价格
│   ├── overseas_collector.py    # 海外标的
│   └── news_collector.py       # 新闻（降级为验证用）
├── detectors/               # 信号检测层（核心）
│   ├── inventory_detector.py    # M1 库存信号
│   ├── capital_detector.py      # M2 资金异动信号
│   ├── commodity_detector.py    # M3 商品期货信号
│   └── overseas_detector.py     # M7 海外映射信号
├── analyzers/               # 分析层
│   ├── correlator.py            # M4 关联分析引擎（中枢）
│   └── ai_engine.py            # M5 AI研判引擎
├── web/                     # 展示层
│   ├── app.py                   # Flask路由
│   └── templates/
│       ├── radar.html           # 信号雷达（核心页面）
│       ├── index.html           # 总览仪表盘
│       ├── news.html            # 消息（辅助验证）
│       └── analysis.html        # AI分析报告
└── data/
    └── monitor.db
```

## 页面说明

| 页面 | 路径 | 功能 |
|------|------|------|
| **信号雷达** | `/radar` | 先行信号流水线、活跃信号列表、置信度/强度 |
| 总览 | `/` | 产业链联动图、板块热力图、海外映射 |
| 消息 | `/news` | 新闻聚合（辅助验证信号） |
| AI分析 | `/analysis` | AI研判报告 |
| 个股 | `/stock/{code}` | K线、估值、资金流向 |

## 配置

编辑 `config.py` 调整：

```python
WATCHLIST = {
    "300308": ("中际旭创", "光模块"),
    # 添加/删除监控标的
}

OVERSEAS_STOCKS = {
    "NVDA": {"name": "NVIDIA", "affects": ["光模块", "服务器"]},
    # 海外关联标的
}
```
