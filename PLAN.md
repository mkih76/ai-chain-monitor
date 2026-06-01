# 实施计划 — AI产业链智能监控Web平台

> 本文档是 Claude Code 的执行蓝图。每个 Task 包含：目标、文件、代码要求、验收标准。
> 按顺序执行，每个 Task 完成后可独立验证。

---

## Phase 1: Web基础 + 数据面板

### Task 1.1: Flask应用骨架

**目标**: 创建Flask应用，跑在 :8795，能访问首页。

**文件**: `web/app.py`

**要求**:
```python
# web/app.py
from flask import Flask, render_template, jsonify, Response
from flask_cors import CORS
import sys, os
sys.path.insert(0, "/opt/ai-monitor")

app = Flask(__name__)
CORS(app)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8795, debug=False)
```

**验收**: `curl http://localhost:8795/health` 返回 `{"status":"ok"}`

---

### Task 1.2: 基础模板 (base.html)

**目标**: 创建Jinja2基础布局，引入CDN库。

**文件**: `web/templates/base.html`

**要求**:
- CDN引入: TailwindCSS Play CDN, Alpine.js 3.x, ECharts 5.x, Font Awesome 6
- 暗色主题 (bg-gray-900 text-gray-100)
- 左侧导航栏: 首页/消息/AI分析/个股
- 顶部标题栏: "AI产业链智能监控"
- 响应式布局 (移动端折叠侧边栏)
- `{% block content %}{% endblock %}` 内容区

**CDN链接**:
```html
<!-- TailwindCSS Play CDN -->
<script src="https://cdn.tailwindcss.com"></script>
<!-- Alpine.js -->
<script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js"></script>
<!-- ECharts -->
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<!-- Font Awesome -->
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css">
```

**配色**: 深色主题
- 背景: bg-gray-900
- 卡片: bg-gray-800 border-gray-700
- 强调色: blue-500 (主), green-500 (涨), red-500 (跌), yellow-500 (警告)

---

### Task 1.3: REST API — 股票数据

**目标**: 提供股票行情API，前端可调用。

**文件**: `web/api.py`

**要求**:
```python
from flask import Blueprint, jsonify, request
import sys
sys.path.insert(0, "/opt/ai-monitor")
from db import get_stock_history, get_inventory_history, get_unsent_signals
from collectors.stock_collector import fetch_realtime, fetch_kline
from collectors.institutional_collector import fetch_valuation, fetch_margin_trading
import config

api = Blueprint("api", __name__)

@api.route("/api/stocks")
def list_stocks():
    """返回所有监控标的的最新行情"""
    results = []
    for code, (name, sector) in config.WATCHLIST.items():
        history = get_stock_history(code, days=1)
        latest = history[0] if history else None
        rt = fetch_realtime(code)  # 实时行情(盘中)
        results.append({
            "code": code, "name": name, "sector": sector,
            "price": rt.get("price") or (latest["close"] if latest else 0),
            "change_pct": rt.get("change_pct") or 0,
            "volume": rt.get("volume") or (latest["volume"] if latest else 0),
            "date": latest["date"] if latest else "",
        })
    return jsonify(results)

@api.route("/api/stocks/<code>")
def stock_detail(code):
    """单只股票详情(含K线+估值+融资融券)"""
    name = config.WATCHLIST.get(code, (code, ""))[0]
    klines = get_stock_history(code, days=60)
    val = fetch_valuation(code)
    margin = fetch_margin_trading(code, days=10)
    return jsonify({
        "code": code, "name": name,
        "klines": klines, "valuation": val, "margin": margin,
    })

@api.route("/api/stocks/<code>/kline")
def stock_kline(code):
    """K线数据"""
    days = request.args.get("days", 60, type=int)
    klines = get_stock_history(code, days=days)
    return jsonify(klines)

@api.route("/api/signals")
def list_signals():
    """信号列表"""
    limit = request.args.get("limit", 50, type=int)
    severity = request.args.get("severity")  # critical/high/medium/low
    import sqlite3
    conn = sqlite3.connect("/opt/ai-monitor/data/monitor.db")
    conn.row_factory = sqlite3.Row
    query = "SELECT * FROM signals"
    params = []
    if severity:
        query += " WHERE severity=?"
        params.append(severity)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@api.route("/api/inventory")
def list_inventory():
    """库存数据"""
    results = {}
    for commodity in ["tin", "copper"]:
        history = get_inventory_history(commodity, weeks=10)
        results[commodity] = history
    return jsonify(results)
```

**验收**: `curl http://localhost:8795/api/stocks` 返回14只股票JSON

---

### Task 1.4: 首页仪表盘 (index.html)

**目标**: 首页显示信号中心、板块热力图、关键指标卡片。

**文件**: `web/templates/index.html`

**要求**:
- 继承 base.html
- 4个指标卡片(Alpine.js + fetch API):
  - 今日信号数 (count)
  - AI情绪指数 (sentiment/100)
  - 北向资金净流入 (亿元)
  - 锡库存 (吨)
- 信号滚动列表 (从 /api/signals 获取，按severity着色)
- 板块热力图 (ECharts TreeMap，按sector分组，颜色映射涨跌幅)
- 响应式: 移动端单列，桌面端双列

**ECharts TreeMap 示例数据结构**:
```javascript
// 按板块分组，value=市值，color=涨跌幅
const treeData = [
  {
    name: '光模块',
    children: [
      { name: '中际旭创', value: 12741, change: 2.3 },
      { name: '新易盛', value: 6871, change: 1.5 },
    ]
  },
  // ...
];
```

---

### Task 1.5: requirements.txt + systemd配置

**文件**: `requirements.txt`, `docs/deploy.md`

**requirements.txt**:
```
flask>=3.0
flask-cors
requests
beautifulsoup4
lxml
apscheduler
pysocks
gunicorn
```

**systemd service** (`/etc/systemd/system/ai-monitor-web.service`):
```ini
[Unit]
Description=AI Monitor Web
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/ai-monitor
ExecStart=/usr/local/bin/gunicorn -w 2 -b 127.0.0.1:8795 web.app:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

**Caddy配置** (追加到 /etc/caddy/Caddyfile):
```
ai.start19491001.dpdns.org {
    reverse_proxy 127.0.0.1:8795
}
```

---

## Phase 2: 消息聚合

### Task 2.1: 新闻数据库表扩展

**文件**: 修改 `db.py`

**新增表**:
```sql
CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT,
    source TEXT,          -- eastmoney/sina/rss/manual
    type TEXT,            -- news/research/report/announcement
    title TEXT,
    url TEXT,
    content TEXT,         -- 正文(可选)
    summary TEXT,         -- AI一句话摘要
    sentiment TEXT,       -- positive/negative/neutral
    impact_stocks TEXT,   -- 受影响股票代码，逗号分隔
    impact_chain TEXT,    -- 传导链描述
    keywords TEXT,        -- 关键词
    score REAL,           -- 相关性分数
    processed INTEGER DEFAULT 0  -- AI是否已处理
);
```

---

### Task 2.2: AI分析引擎

**文件**: `web/ai_engine.py`

**要求**:
- 封装MiMo LLM调用 (POST http://localhost:3001/open-apis/bot/chat)
- 3个核心函数:

```python
def summarize_news(title: str, content: str = "") -> dict:
    """
    对单条消息生成AI分析
    返回: {"summary": "...", "sentiment": "positive/negative/neutral",
           "impact_stocks": ["300308", "601138"], "chain": "英伟达→中际旭创"}
    Prompt: 你是AI产业链分析师。对以下消息分析：1)一句话摘要(30字内)
    2)利好/利空/中性 3)受影响标的(从列表选) 4)传导逻辑。
    标的列表: 中际旭创(300308),新易盛(300502),工业富联(601138)...
    消息: {title}
    返回JSON格式。
    """

def generate_daily_report(signals: list, stock_data: dict, inventory: dict) -> str:
    """
    生成每日综合分析报告
    返回: markdown格式的分析报告
    """

def analyze_stock(code: str, klines: list, valuation: dict, signals: list) -> str:
    """
    个股AI分析
    返回: markdown格式的个股分析
    """
```

**MiMo Proxy调用方式**:
```python
import requests

MIMO_URL = "http://localhost:3001/open-apis/bot/chat"
MIMO_COOKIES = {
    "serviceToken": "...",  # 从 /opt/mimo-proxy/vpngate_data/ui_auth.json 读取
    "userId": "1237118700",
    "xiaomichatbot_ph": "...",
}

def call_mimo(prompt: str, max_tokens: int = 1000) -> str:
    """调用MiMo LLM"""
    resp = requests.post(MIMO_URL, json={
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }, cookies=MIMO_COOKIES, timeout=30)
    data = resp.json()
    return data.get("choices", [{}])[0].get("message", {}).get("content", "")
```

**注意**: MiMo cookie可能过期(30天)，需要处理过期情况，返回默认值而非报错。

---

### Task 2.3: 消息流页面

**文件**: `web/templates/news.html`

**要求**:
- 继承 base.html
- 筛选栏: 全部/新闻/研报/公告 (Alpine.js tab切换)
- 消息卡片列表:
  - 左侧: 严重程度色标 (红/橙/黄/灰)
  - 标题 (加粗)
  - AI摘要 (斜体，灰色)
  - 受影响标的 (蓝色tag)
  - 来源 + 时间
  - 传导链 (箭头图示: 英伟达 → 中际旭创 → 光模块)
- 加载更多按钮 (分页)
- 搜索框 (标题关键词过滤)

---

### Task 2.4: 消息API

**文件**: 在 `web/api.py` 中新增

```python
@api.route("/api/news")
def list_news():
    """消息列表"""
    type_ = request.args.get("type")
    limit = request.args.get("limit", 30, type=int)
    offset = request.args.get("offset", 0, type=int)
    # 从articles表查询，支持type筛选
    ...

@api.route("/api/news/<int:id>")
def news_detail(id):
    """消息详情(含AI分析)"""
    ...
```

---

## Phase 3: AI分析页 + 关联图

### Task 3.1: 产业链关联图数据

**文件**: `web/chain_graph.py`

**要求**:
- 基于 AGENTS.md 中的 CHAIN 字典
- 生成 Cytoscape.js / ECharts Graph 所需的 nodes + edges 数据
- 当某个节点有信号时，高亮该节点及其关联节点

```python
def get_chain_graph(highlight_codes: list = None) -> dict:
    """
    返回 {nodes: [...], edges: [...]}
    nodes: {id, name, type, size(市值), color(涨跌), highlighted(bool)}
    edges: {source, target, type(upstream/downstream/peer)}
    """
```

---

### Task 3.2: 情绪指数

**文件**: `web/sentiment.py`

**要求**:
- 综合多个维度计算0-100情绪分:
  - 价格信号 (40%): 涨跌比、创新高/低比
  - 融资融券 (20%): 融资余额变化趋势
  - 龙虎榜 (20%): 净买入占比
  - 北向资金 (20%): 净流入方向
- 0-30: 恐慌, 30-50: 偏空, 50-70: 中性偏多, 70-100: 亢奋

```python
def calculate_sentiment() -> dict:
    """
    返回 {"score": 72, "label": "偏多", "color": "green",
          "components": {"price": 75, "margin": 68, "dragon": 70, "northbound": 80}}
    """
```

---

### Task 3.3: AI分析页面

**文件**: `web/templates/analysis.html`

**要求**:
- 产业链关联图 (ECharts Graph，力导向布局)
  - 节点大小=市值，颜色=涨跌幅
  - 有信号的节点脉冲动画
  - 点击节点跳转到个股详情
- 每日综合分析报告 (Markdown渲染)
- 情绪指数仪表盘 (ECharts gauge)
- 历史相似场景 (可选，Phase 4)

---

### Task 3.4: AI分析API

**文件**: 在 `web/api.py` 中新增

```python
@api.route("/api/analysis/chain")
def chain_graph():
    """产业链关联图数据"""
    ...

@api.route("/api/analysis/sentiment")
def sentiment():
    """情绪指数"""
    ...

@api.route("/api/analysis/daily")
def daily_report():
    """每日综合分析(调用AI生成，缓存24h)"""
    ...

@api.route("/api/analysis/stock/<code>")
def stock_analysis(code):
    """个股AI分析"""
    ...
```

---

## Phase 4: 个股详情 + SSE推送 + 部署

### Task 4.1: 个股详情页

**文件**: `web/templates/stock.html`

**要求**:
- K线图 (ECharts candlestick + MA5/MA10/MA20)
- 成交量柱状图 (K线下方)
- 估值面板卡片: PE/PB/市值/换手率/60日涨跌
- 融资融券折线图 (近10日)
- 相关消息列表
- AI个股分析文本
- 信号历史列表

---

### Task 4.2: SSE实时推送

**文件**: `web/api.py` (新增SSE端点), `web/static/js/sse.js`

```python
# 后端
@api.route("/api/stream/signals")
def stream_signals():
    """SSE信号推送"""
    def generate():
        while True:
            # 检查新信号
            unsent = get_unsent_signals()
            if unsent:
                for s in unsent:
                    yield f"data: {json.dumps(s)}\n\n"
                    mark_signal_sent(s["id"])
            time.sleep(30)
    return Response(generate(), mimetype="text/event-stream")
```

```javascript
// 前端 sse.js
const evtSource = new EventSource("/api/stream/signals");
evtSource.onmessage = (e) => {
    const signal = JSON.parse(e.data);
    // 在信号中心插入新信号，播放提示音
};
```

---

### Task 4.3: 部署配置

**文件**: `docs/deploy.md`

**步骤**:
1. `pip install -r requirements.txt`
2. 创建 systemd service
3. 配置 Caddy 反代
4. `systemctl enable --now ai-monitor-web`
5. 验证: 访问 https://ai.start19491001.dpdns.org

---

## 实施顺序

```
Task 1.1 → 1.2 → 1.3 → 1.4 → 1.5  (Phase 1: 能看到页面)
    ↓
Task 2.1 → 2.2 → 2.3 → 2.4         (Phase 2: 消息+AI摘要)
    ↓
Task 3.1 → 3.2 → 3.3 → 3.4         (Phase 3: AI分析+关联图)
    ↓
Task 4.1 → 4.2 → 4.3               (Phase 4: 详情+推送+部署)
```

每个Phase完成后可独立验证和展示。
