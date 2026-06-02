"""
AI产业链监控 Web平台 - Flask应用
Apple设计语言风格
"""
from flask import Flask, render_template, jsonify, Response
from flask_cors import CORS
import sys, os, json
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

app = Flask(__name__)
CORS(app)

# ============================================================
# 页面路由
# ============================================================
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/news")
def news_page():
    return render_template("news.html")

@app.route("/analysis")
def analysis_page():
    return render_template("analysis.html")

@app.route("/stock/<code>")
def stock_detail(code):
    return render_template("stock.html", code=code)

# ============================================================
# REST API
# ============================================================
@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "timestamp": datetime.now().isoformat()})

@app.route("/api/stocks")
def api_stocks():
    """所有监控股票的最新行情"""
    from db import init_db, get_stock_history
    from collectors.institutional_collector import fetch_valuation
    import config
    init_db()

    result = []
    for code, (name, sector) in config.WATCHLIST.items():
        history = get_stock_history(code, days=5)
        val = fetch_valuation(code)
        latest = history[0] if history else {}
        prev = history[1] if len(history) >= 2 else {}
        chg = 0
        if latest and prev and prev.get("close", 0) > 0:
            chg = round((latest["close"] - prev["close"]) / prev["close"] * 100, 2)
        result.append({
            "code": code,
            "name": name,
            "sector": sector,
            "close": latest.get("close", 0),
            "change_pct": chg,
            "volume": latest.get("volume", 0),
            "date": latest.get("date", ""),
            "pe_ttm": val.get("pe_ttm") if val else None,
            "pb": val.get("pb") if val else None,
            "total_mv": val.get("total_mv") if val else None,
        })
    return jsonify(result)

@app.route("/api/stock/<code>/kline")
def api_stock_kline(code):
    """个股K线数据"""
    from db import init_db, get_stock_history
    init_db()
    days = int(__import__("flask").request.args.get("days", 60))
    history = get_stock_history(code, days=days)
    history.reverse()
    return jsonify(history)

@app.route("/api/stock/<code>/detail")
def api_stock_detail(code):
    """个股详情（多维数据）"""
    from db import init_db, get_stock_history, get_northbound_consecutive_buy
    from collectors.institutional_collector import fetch_valuation, fetch_margin_trading
    import config
    init_db()

    name, sector = config.WATCHLIST.get(code, (code, ""))
    history = get_stock_history(code, days=60)
    val = fetch_valuation(code)
    margin = fetch_margin_trading(code, days=10)
    nb_consec, nb_total = get_northbound_consecutive_buy(code, min_days=3)

    return jsonify({
        "code": code, "name": name, "sector": sector,
        "kline": history,
        "valuation": val,
        "margin": margin,
        "northbound": {"consecutive_days": nb_consec, "total_yi": round(nb_total/1e8, 2) if nb_total else 0},
    })

@app.route("/api/overseas")
def api_overseas():
    """海外标的行情"""
    from db import init_db, get_overseas_history
    import config
    init_db()

    result = []
    for symbol, info in config.OVERSEAS_STOCKS.items():
        history = get_overseas_history(symbol, days=5)
        latest = history[0] if history else {}
        result.append({
            "symbol": symbol,
            "name": info["name"],
            "close": latest.get("close", 0),
            "change_pct": latest.get("change_pct", 0),
            "after_hours_price": latest.get("after_hours_price"),
            "after_hours_change_pct": latest.get("after_hours_change_pct"),
            "affects": info["affects"],
            "note": info["note"],
        })
    return jsonify(result)

@app.route("/api/upstream")
def api_upstream():
    """上游产业数据"""
    from db import init_db, get_upstream_latest
    init_db()

    result = []
    metrics = [
        ("tsmc", "monthly_revenue_twd_mn", "TSMC月营收"),
        ("lme", "copper_stocks", "LME铜库存"),
        ("lme", "tin_stocks", "LME锡库存"),
        ("dram_market", "dram_sentiment", "DRAM价格"),
    ]
    for source, metric, label in metrics:
        data = get_upstream_latest(source, metric, limit=12)
        for d in data:
            d["label"] = label
            result.append(d)
    return jsonify(result)

@app.route("/api/news")
def api_news():
    """新闻列表"""
    from db import init_db, get_conn
    init_db()
    limit = int(__import__("flask").request.args.get("limit", 30))
    conn = get_conn()
    rows = conn.execute("SELECT * FROM news ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/signals")
def api_signals():
    """信号列表"""
    from db import init_db, get_conn
    init_db()
    limit = int(__import__("flask").request.args.get("limit", 50))
    conn = get_conn()
    rows = conn.execute("SELECT * FROM signals ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/ai-analysis")
def api_ai_analysis():
    """AI分析结果"""
    from db import init_db, get_ai_analysis_recent
    init_db()
    result = get_ai_analysis_recent(limit=20)
    return jsonify(result)

@app.route("/api/dashboard")
def api_dashboard():
    """仪表盘汇总数据"""
    from db import init_db, get_stock_history, get_conn, get_overseas_history
    from collectors.inventory_collector import get_inventory_trend
    from collectors.institutional_collector import fetch_northbound_realtime
    import config
    init_db()

    # 板块涨跌
    sectors = {}
    for code, (name, sector) in config.WATCHLIST.items():
        if sector not in sectors:
            sectors[sector] = {"stocks": [], "avg_change": 0}
        history = get_stock_history(code, days=2)
        chg = 0
        if len(history) >= 2 and history[1].get("close", 0) > 0:
            chg = round((history[0]["close"] - history[1]["close"]) / history[1]["close"] * 100, 2)
        sectors[sector]["stocks"].append({"code": code, "name": name, "change_pct": chg, "close": history[0]["close"] if history else 0})

    for sector in sectors:
        stocks = sectors[sector]["stocks"]
        if stocks:
            sectors[sector]["avg_change"] = round(sum(s["change_pct"] for s in stocks) / len(stocks), 2)

    # 库存
    tin_trend = get_inventory_trend("tin", weeks=5)
    copper_trend = get_inventory_trend("copper", weeks=5)

    # 北向资金
    nb = fetch_northbound_realtime()

    # 海外
    overseas = []
    for symbol, info in config.OVERSEAS_STOCKS.items():
        history = get_overseas_history(symbol, days=1)
        latest = history[0] if history else {}
        overseas.append({
            "symbol": symbol, "name": info["name"],
            "close": latest.get("close", 0), "change_pct": latest.get("change_pct", 0),
            "affects": info["affects"],
        })

    # 最新信号
    conn = get_conn()
    recent_signals = conn.execute("SELECT * FROM signals ORDER BY id DESC LIMIT 10").fetchall()
    conn.close()

    return jsonify({
        "sectors": sectors,
        "inventory": {"tin": tin_trend, "copper": copper_trend},
        "northbound": nb,
        "overseas": overseas,
        "recent_signals": [dict(s) for s in recent_signals],
        "timestamp": datetime.now().isoformat(),
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8795, debug=True)
