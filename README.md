# 🧠 AI产业链监控系统

自动化监控AI产业链上下游关键标的，检测价格/库存/日历信号，推送告警。

## 快速开始

```bash
cd /opt/ai-monitor

# 测试运行
python3 manage.py test

# 完整运行（采集+分析+推送）
python3 main.py full

# 仅采集数据
python3 manage.py collect

# 仅分析信号
python3 main.py analyze

# 生成报告
python3 main.py report
```

## 监控标的

| 板块 | 标的 |
|------|------|
| 光模块 | 中际旭创(300308)、新易盛(300502) |
| 服务器 | 工业富联(601138)、浪潮信息(000977) |
| PCB | 深南电路(002916)、兴森科技(002436) |
| 液冷 | 英维克(002837) |
| 封装 | 长电科技(600584)、通富微电(002156) |
| 铜缆 | 沃尔核材(002130) |
| 锡 | 锡业股份(000960) |
| 铜 | 紫金矿业(601899) |
| 国产算力 | 寒武纪(688256)、海光信息(688041) |

## 信号类型

| 信号 | 触发条件 | 严重程度 |
|------|----------|----------|
| 🚀 单日大涨 | ≥5% | medium/high(≥7%) |
| 📉 单日大跌 | ≤-5% | medium/high(≤-7%) |
| 📈 创新高 | 突破60日最高价 | medium |
| ⚠️ 创新低 | 跌破60日最低价 | medium |
| 🔊 放量 | 成交量≥20日均量2倍 | medium |
| 🔻 库存下降 | 连续3周下降 | medium/high |
| 🚨 库存警戒 | 低于阈值 | critical |
| 📅 日历提醒 | 提前7天 | medium |

## 手动录入库存

SHFE官网有WAF拦截，库存数据需手动录入：

```bash
# 录入锡库存
python3 manage.py inventory --tin 4500

# 录入铜库存
python3 manage.py inventory --copper 35000

# 同时录入
python3 manage.py inventory --tin 4500 --copper 35000

# 指定日期
python3 manage.py inventory --tin 4500 --date 20260601
```

## 日历管理

```bash
# 查看近期事件
python3 manage.py calendar

# 添加事件
python3 manage.py add-event --date 2025-07-15 --event "某公司财报" --impact "光模块,服务器"
```

## 定时任务

通过Hermes Agent管理，每交易日16:00(UTC+8)自动运行：

```bash
# 查看任务
hermes cron list

# 手动触发
hermes cron run <job_id>
```

## 数据源

- **股价**: 腾讯财经API（主）+ 新浪财经API（备）
- **库存**: 上期所官网（尝试）+ 手动录入（备）
- **新闻**: 东方财富搜索API

## 配置

编辑 `config.py` 调整：
- `WATCHLIST`: 监控标的
- `SIGNALS`: 信号阈值
- `CALENDAR_EVENTS`: 日历事件
- `NOTIFY`: 推送配置

## 文件结构

```
/opt/ai-monitor/
├── main.py              # 主程序
├── manage.py            # 管理工具
├── config.py            # 配置
├── db.py                # 数据库
├── collectors/
│   ├── stock_collector.py    # 股价采集
│   ├── inventory_collector.py # 库存采集
│   └── news_collector.py     # 新闻采集
├── analyzers/
│   └── signal_engine.py      # 信号分析
├── notifiers/
│   └── telegram_notifier.py  # 推送通知
├── data/
│   └── monitor.db            # SQLite数据库
└── logs/
    └── monitor.log           # 运行日志
```
