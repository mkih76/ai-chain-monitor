# AI产业链监控系统

A股AI产业链全链路监控平台，覆盖上游材料→中游制造→下游应用，自动采集、AI研判、信号推送，辅助判断后期是否要涨。

## 核心功能

- **产业链联动监控** — 光模块/服务器/PCB/液冷/封装/铜缆/存储/国产算力，16+标的实时行情
- **先行指标引擎** — 板块资金流向、概念板块异动、政策文件、舆情热度、商品动量、跨市场信号，多信号共振检测
- **消息模块** — 分类展示（财联社/财经快讯/券商研报/公司公告），AI语义分析研判方向，点击跳转原文
- **材料供需** — 铜/锡/镍/铝期货价格+SHFE库存，自动分析对产业链成本影响
- **海外映射** — NVDA/TSM/AVGO/MU/SMCI/ASML 隔夜行情+A股关联标的联动分析
- **AI自进化** — 预测记录→回测验证→自动校准→新标的自动发现
- **Web仪表盘** — GSAP动画、产业链流向图、板块热力图、ECharts交互图表

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Flask + APScheduler + SQLite |
| 前端 | Alpine.js + ECharts + GSAP |
| AI分析 | MiMo LLM Proxy (可选) |
| 数据源 | 新浪财经/东方财富/巨潮资讯/SHFE/Yahoo Finance |
| 部署 | Python 3.10+ / Nginx反向代理 / Systemd |

## 快速开始

```bash
# 克隆仓库
git clone https://github.com/mkih76/ai-chain-monitor.git
cd ai-chain-monitor

# 安装依赖
pip install flask flask-cors apscheduler requests

# 初始化数据库 + 测试运行
python manage.py test

# 启动Web服务
python web/app.py
# 浏览器访问 http://localhost:8795

# 完整采集分析
python main.py full

# 启动定时调度器
python scheduler.py
```

## 云部署

### 方式一：Linux服务器部署（推荐）

以Ubuntu/CentOS为例，部署到 `/opt/ai-monitor`：

```bash
# 1. 上传代码
scp -r . root@your-server:/opt/ai-monitor/

# 2. SSH登录服务器
ssh root@your-server

# 3. 安装依赖
cd /opt/ai-monitor
pip3 install flask flask-cors apscheduler requests

# 4. 测试运行
python3 web/app.py &  # 启动后访问 http://your-server:8795

# 5. 配置Systemd服务（开机自启+自动重启）
cat > /etc/systemd/system/ai-monitor.service << 'EOF'
[Unit]
Description=AI产业链监控系统
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/ai-monitor
ExecStart=/usr/bin/python3 web/app.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

# 6. 启用并启动服务
systemctl daemon-reload
systemctl enable ai-monitor
systemctl start ai-monitor
systemctl status ai-monitor

# 7. 配置Nginx反向代理（可选，绑定域名）
cat > /etc/nginx/sites-available/ai-monitor << 'EOF'
server {
    listen 80;
    server_name monitor.yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:8795;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
EOF
ln -s /etc/nginx/sites-available/ai-monitor /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
```

### 方式二：Docker部署

```dockerfile
# Dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir flask flask-cors apscheduler requests
EXPOSE 8795
CMD ["python", "web/app.py"]
```

```bash
# 构建并运行
docker build -t ai-chain-monitor .
docker run -d -p 8795:8795 -v $(pwd)/data:/opt/ai-monitor/data --name ai-monitor ai-chain-monitor

# 查看日志
docker logs -f ai-monitor
```

### 方式三：宝塔面板部署

```bash
# 1. 上传代码到 /www/wwwroot/ai-monitor
# 2. 宝塔 → 网站 → 添加Python项目
#    - 项目路径: /www/wwwroot/ai-monitor
#    - 启动文件: web/app.py
#    - 端口: 8795
#    - Python版本: 3.10+
# 3. 启动项目，绑定域名即可访问
```

### 定时采集调度

```bash
# 方式A: Systemd Timer
cat > /etc/systemd/system/ai-monitor-scheduler.service << 'EOF'
[Unit]
Description=AI产业链监控定时调度

[Service]
Type=simple
WorkingDirectory=/opt/ai-monitor
ExecStart=/usr/bin/python3 scheduler.py
EOF

cat > /etc/systemd/system/ai-monitor-scheduler.timer << 'EOF'
[Unit]
Description=AI产业链监控定时器

[Timer]
OnCalendar=Mon..Fri *-*-* 16:00:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl enable --now ai-monitor-scheduler.timer

# 方式B: Crontab
# 每交易日16:00完整采集
0 16 * * 1-5 cd /opt/ai-monitor && python3 scheduler.py once >> /var/log/ai-monitor.log 2>&1
```

## 监控标的

| 板块 | 标的 | 说明 |
|------|------|------|
| 光模块 | 中际旭创(300308)、新易盛(300502) | AI算力核心 |
| 服务器 | 工业富联(601138)、浪潮信息(000977) | AI基础设施 |
| PCB | 深南电路(002916)、兴森科技(002436) | 铜价敏感 |
| 液冷 | 英维克(002837) | 散热方案 |
| 封装 | 长电科技(600584)、通富微电(002156) | 先进封装/CoWoS |
| 铜缆 | 沃尔核材(002130) | 铜价敏感 |
| 锡 | 锡业股份(000960) | 封装焊接材料 |
| 铜 | 紫金矿业(601899) | 原材料 |
| 国产算力 | 寒武纪(688256)、海光信息(688041) | 国产替代 |

## 数据源

| 数据 | 来源 | 频率 |
|------|------|------|
| A股行情 | 新浪财经/腾讯财经 | 实时 |
| 海外标的 | Yahoo Finance | 每日 |
| 资金流向 | 东方财富 | 每日 |
| 新闻资讯 | 新浪财经/财联社/巨潮资讯 | 每次采集 |
| 券商研报 | 东方财富研报API | 每次采集 |
| 材料价格 | 新浪期货API (铜/锡/镍/铝) | 每小时 |
| 库存数据 | SHFE + 手动录入 | 每周 |
| 北向资金 | 东方财富 | 每日 |

## 信号类型

| 信号 | 触发条件 | 严重程度 |
|------|----------|----------|
| 单日大涨 | >=5% | medium/high(>=7%) |
| 单日大跌 | <=-5% | medium/high(<=-7%) |
| 创新高 | 突破60日最高价 | medium |
| 创新低 | 跌破60日最低价 | medium |
| 放量 | 成交量>=20日均量2倍 | medium |
| 库存下降 | 连续3周下降 | medium/high |
| 库存警戒 | 低于阈值 | critical |
| 先行指标共振 | 多信号指向同一板块 | high |

## 配置

编辑 `config.py` 调整：

```python
WATCHLIST = {
    "300308": ("中际旭创", "光模块"),
    # 添加/删除监控标的
}

OVERSEAS_STOCKS = {
    "NVDA": {"name": "英伟达", "affects": "算力"},
    # 海外关联标的
}

AI_ENGINE = {
    "enabled": True,           # 启用AI分析
    "mimo_proxy_url": "...",   # MiMo LLM地址
}
```

## 文件结构

```
ai-chain-monitor/
├── main.py                  # 主程序入口
├── manage.py                # 管理工具
├── config.py                # 全局配置
├── db.py                    # SQLite数据库模块
├── scheduler.py             # 定时调度器 (APScheduler)
├── predictor.py             # 预测回测系统
├── discoverer.py            # 新标的自动发现
├── collectors/
│   ├── stock_collector.py       # A股行情
│   ├── overseas_collector.py    # 海外标的
│   ├── institutional_collector.py # 北向资金/两融
│   ├── inventory_collector.py   # 库存数据
│   ├── news_collector.py        # 新闻采集 (新浪/财联社/巨潮/券商研报)
│   ├── material_collector.py    # 材料价格 (铜/锡/镍/铝期货)
│   ├── leading_collector.py     # 先行指标
│   └── upstream_collector.py    # 上游产业数据
├── analyzers/
│   ├── signal_engine.py         # 信号分析引擎
│   ├── ai_engine.py             # AI分析引擎
│   └── leading_engine.py        # 先行指标分析+共振检测
├── notifiers/
│   └── telegram_notifier.py     # Telegram推送
├── web/
│   ├── app.py                   # Flask API
│   └── templates/
│       ├── base.html            # 基础布局+导航
│       ├── index.html           # 总览仪表盘
│       ├── news.html            # 消息模块 (分类+材料+AI研判)
│       ├── analysis.html        # AI分析
│       ├── stock.html           # 个股详情
│       └── evolution.html       # 进化系统
└── data/
    └── monitor.db               # SQLite数据库
```

## 页面说明

| 页面 | 路径 | 功能 |
|------|------|------|
| 总览 | `/` | 板块涨跌、产业链流向、库存趋势、海外映射、先行指标 |
| 消息 | `/news` | 分类新闻、材料供需、AI研判总结、原文跳转 |
| AI分析 | `/analysis` | AI多空研判、催化剂/风险/建议 |
| 个股 | `/stock/{code}` | K线、估值、北向资金、两融 |
| 进化 | `/evolution` | 预测回测、准确率、自动校准、新标的发现 |
