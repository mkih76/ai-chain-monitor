# AI产业链智能监控平台

> 聚合10+数据源，AI自动分析关联，实时信号推送的A股AI产业链监控系统。

## 已有基础

`/opt/ai-monitor/` 目录下已有可运行的数据采集+信号分析系统：

| 模块 | 文件 | 状态 | 说明 |
|------|------|------|------|
| 股价采集 | `collectors/stock_collector.py` | ✅ 生产运行 | 腾讯+新浪API，14只标的60日K线 |
| 库存采集 | `collectors/inventory_collector.py` | ✅ 生产运行 | SHFE官网(自动)+手动录入 |
| 新闻采集 | `collectors/news_collector.py` | ✅ 生产运行 | 东方财富搜索API |
| 机构数据 | `collectors/institutional_collector.py` | ✅ 生产运行 | 估值/融资融券/龙虎榜/大宗交易/机构调研/北向资金 |
| 信号引擎 | `analyzers/signal_engine.py` | ✅ 生产运行 | 价格+库存+日历+估值+融资+龙虎榜信号 |
| 通知推送 | `notifiers/telegram_notifier.py` | ✅ 生产运行 | Telegram格式化推送 |
| 主程序 | `main.py` | ✅ 生产运行 | 完整pipeline: 采集→分析→推送 |
| 管理工具 | `manage.py` | ✅ 生产运行 | CLI管理(库存录入/报告/历史) |
| 配置 | `config.py` | ✅ 生产运行 | 标的/阈值/数据源/日历 |
| 数据库 | `db.py` | ✅ 生产运行 | SQLite: stock_daily/inventory/signals/news |
| 文档 | `docs/INTEGRATION_PLAN.md` | ✅ | 详细集成方案 |

## 当前任务

将上述系统升级为 **Web平台**，新增：
1. Flask Web应用 + REST API
2. ECharts K线图 + 板块热力图
3. 消息聚合流 + AI自动摘要
4. 产业链关联分析图
5. 情绪指数 + 综合分析报告
6. SSE实时信号推送
7. 移动端适配

## 技术栈

- **后端**: Flask + Gunicorn + APScheduler
- **前端**: TailwindCSS CDN + Alpine.js + ECharts (CDN，无需构建工具)
- **数据库**: SQLite (已有 `/opt/ai-monitor/data/monitor.db`)
- **AI**: MiMo LLM Proxy (localhost:3001, cookie auth, 免费)
- **反代**: Caddy (已有，监听 :8795)
- **部署**: systemd service

## 关键约束

1. **不要重构已有采集器**，直接import使用
2. **前端不用npm/webpack**，纯CDN引入（TailwindCSS Play CDN + Alpine.js + ECharts）
3. **SQLite不换PostgreSQL**，数据量够用
4. **AI调用走MiMo proxy**，不要用付费API
5. **所有图表用ECharts**，不引入其他图表库
6. **Python 3.10**，不要用3.12+的语法

## 已验证可用的外部API

```
# 股价K线（腾讯财经，VPS直连）
GET https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sz000960,day,2026-01-01,2026-06-01,60,qfq

# 实时行情（新浪，VPS直连）
GET https://hq.sinajs.cn/list=sz000960
Header: Referer: https://finance.sina.com.cn/

# 腾讯行情（含PE/PB/市值）
GET https://qt.gtimg.cn/q=sz000960

# 东方财富datacenter（龙虎榜/融资融券/大宗交易/机构调研/研报）
GET https://datacenter-web.eastmoney.com/api/data/v1/get
参数: reportName, columns, filter, pageNumber, pageSize, sortColumns, sortTypes, source=WEB, client=WEB

# MiMo LLM Proxy
POST http://localhost:3001/open-apis/bot/chat
Cookie Auth: serviceToken + userId + xiaomichatbot_ph
```

## 监控标的列表

```python
WATCHLIST = {
    "300308": ("中际旭创", "光模块"),
    "300502": ("新易盛", "光模块"),
    "601138": ("工业富联", "服务器"),
    "000977": ("浪潮信息", "服务器"),
    "002916": ("深南电路", "PCB"),
    "002436": ("兴森科技", "PCB"),
    "002837": ("英维克", "液冷"),
    "600584": ("长电科技", "封装"),
    "002156": ("通富微电", "封装"),
    "002130": ("沃尔核材", "铜缆"),
    "000960": ("锡业股份", "锡"),
    "601899": ("紫金矿业", "铜"),
    "688256": ("寒武纪", "国产算力"),
    "688041": ("海光信息", "国产算力"),
}
```

## 产业链关联图（预定义）

```python
CHAIN = {
    "英伟达":   {"type": "上游", "downstream": ["中际旭创", "新易盛", "工业富联", "浪潮信息", "深南电路"]},
    "台积电":   {"type": "上游", "downstream": ["长电科技", "通富微电"]},
    "Meta":     {"type": "终端", "downstream": ["中际旭创", "新易盛", "工业富联"]},
    "微软":     {"type": "终端", "downstream": ["中际旭创", "新易盛", "工业富联", "浪潮信息"]},
    "谷歌":     {"type": "终端", "downstream": ["中际旭创", "新易盛", "工业富联"]},
    "亚马逊":   {"type": "终端", "downstream": ["工业富联", "浪潮信息", "英维克"]},
    "锡价":     {"type": "原材料", "downstream": ["锡业股份", "长电科技", "通富微电"]},
    "铜价":     {"type": "原材料", "downstream": ["紫金矿业", "沃尔核材"]},
    "中际旭创": {"type": "光模块", "upstream": ["英伟达", "Meta", "微软", "谷歌"], "downstream": [], "peer": ["新易盛"]},
    "新易盛":   {"type": "光模块", "upstream": ["英伟达", "Meta", "微软"], "downstream": [], "peer": ["中际旭创"]},
    "工业富联": {"type": "服务器", "upstream": ["英伟达"], "downstream": [], "peer": ["浪潮信息"]},
    "浪潮信息": {"type": "服务器", "upstream": ["英伟达"], "downstream": [], "peer": ["工业富联"]},
    "深南电路": {"type": "PCB", "upstream": ["英伟达"], "downstream": [], "peer": ["兴森科技"]},
    "兴森科技": {"type": "PCB", "upstream": [], "downstream": [], "peer": ["深南电路"]},
    "英维克":   {"type": "液冷", "upstream": [], "downstream": [], "peer": []},
    "长电科技": {"type": "封装", "upstream": ["台积电", "锡价"], "downstream": [], "peer": ["通富微电"]},
    "通富微电": {"type": "封装", "upstream": ["台积电", "锡价"], "downstream": [], "peer": ["长电科技"]},
    "沃尔核材": {"type": "铜缆", "upstream": ["铜价"], "downstream": [], "peer": []},
    "锡业股份": {"type": "锡", "upstream": [], "downstream": [], "peer": []},
    "紫金矿业": {"type": "铜", "upstream": [], "downstream": [], "peer": []},
    "寒武纪":   {"type": "国产算力", "upstream": [], "downstream": [], "peer": ["海光信息"]},
    "海光信息": {"type": "国产算力", "upstream": [], "downstream": [], "peer": ["寒武纪"]},
}
```

## 运行环境

- OS: Ubuntu 22.04 (VPS 23.94.206.159)
- Python: 3.10
- 已安装: requests, beautifulsoup4, lxml, apscheduler, pysocks
- 已有: Caddy反代, systemd, SQLite
- MiMo Proxy: /opt/mimo-proxy/ (port 3001, cookie auth)
- 监控系统: /opt/ai-monitor/ (已有数据库和采集器)

## 项目目录结构（目标）

```
/opt/ai-monitor/
├── AGENTS.md                    # Claude Code 项目指引（本文件）
├── PLAN.md                      # 详细实施计划
├── README.md                    # 项目说明
├── requirements.txt             # Python依赖
├── config.py                    # [已有] 配置
├── db.py                        # [已有] 数据库
├── main.py                      # [已有] 主程序
├── manage.py                    # [已有] CLI管理
├── collectors/                  # [已有] 采集器
│   ├── stock_collector.py
│   ├── inventory_collector.py
│   ├── news_collector.py
│   └── institutional_collector.py
├── analyzers/                   # [已有] 分析器
│   └── signal_engine.py
├── notifiers/                   # [已有] 通知器
│   └── telegram_notifier.py
├── web/                         # [待建] Web应用
│   ├── app.py                   # Flask主应用 + 路由
│   ├── api.py                   # REST API蓝图
│   ├── ai_engine.py             # AI分析引擎 (MiMo调用)
│   ├── chain_graph.py           # 产业链关联图数据
│   ├── sentiment.py             # 情绪指数计算
│   ├── templates/
│   │   ├── base.html            # 基础布局模板
│   │   ├── index.html           # 首页仪表盘
│   │   ├── news.html            # 消息聚合流
│   │   ├── analysis.html        # AI分析页
│   │   └── stock.html           # 个股详情页
│   └── static/
│       ├── css/
│       │   └── app.css          # 自定义样式
│       └── js/
│           ├── app.js           # 全局JS (Alpine.js组件)
│           ├── charts.js        # ECharts图表封装
│           └── sse.js           # SSE实时推送客户端
├── data/                        # [已有] 数据存储
│   └── monitor.db
├── logs/                        # [已有] 日志
│   └── monitor.log
└── docs/
    └── INTEGRATION_PLAN.md      # [已有] 集成方案
```
