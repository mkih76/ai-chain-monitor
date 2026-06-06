"""
AI产业链监控 Web平台 - Flask应用
Apple设计语言风格
"""
from flask import Flask, render_template, jsonify, Response, redirect
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
    return redirect("/signal")

@app.route("/signal")
def signal_page():
    """①信号 — 决策核心"""
    return render_template("signal.html")

@app.route("/market")
def market_page():
    """②市场 — 先行指标全景"""
    return render_template("market.html")

@app.route("/report")
def report_page():
    """③报告 — AI研判+消息验证"""
    return render_template("report.html")

@app.route("/review")
def review_page():
    """④复盘 — 准确率+反馈"""
    return render_template("review.html")

@app.route("/stock/<code>")
def stock_detail(code):
    return render_template("signal.html")  # 个股详情暂用信号页

# 旧路径兼容
@app.route("/radar")
def radar_redirect():
    return redirect("/signal")

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
    """新闻列表（支持分类/方向/时间过滤）"""
    from db import init_db, get_conn
    init_db()
    req = __import__("flask").request
    limit = int(req.args.get("limit", 50))
    category = req.args.get("category", "")
    direction = req.args.get("direction", "")
    time_filter = req.args.get("time", "")

    conn = get_conn()
    sql = "SELECT * FROM news WHERE 1=1"
    params = []

    if category:
        sql += " AND category=?"
        params.append(category)
    if direction:
        sql += " AND ai_direction=?"
        params.append(direction)
    if time_filter == "today":
        sql += " AND timestamp >= date('now', 'start of day')"
    elif time_filter == "week":
        sql += " AND timestamp >= date('now', '-7 days')"

    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/news/categories")
def api_news_categories():
    """新闻分类统计"""
    from db import init_db, get_conn
    init_db()
    conn = get_conn()
    rows = conn.execute(
        "SELECT category, COUNT(*) as cnt FROM news GROUP BY category ORDER BY cnt DESC"
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/materials")
def api_materials():
    """材料价格数据"""
    from db import init_db, get_latest_materials
    init_db()
    materials = get_latest_materials()
    return jsonify(materials)


@app.route("/api/inventory/history")
def api_inventory_history():
    """库存历史数据（按品种分组）"""
    from db import init_db, get_conn
    init_db()
    conn = get_conn()
    rows = conn.execute("SELECT * FROM inventory ORDER BY date ASC").fetchall()
    conn.close()
    result = {}
    for r in rows:
        d = dict(r)
        commodity = d["commodity"]
        if commodity not in result:
            result[commodity] = []
        result[commodity].append(d)
    return jsonify(result)


@app.route("/api/materials/history")
def api_materials_history():
    """材料价格历史（按品种分组）"""
    from db import init_db, get_conn
    init_db()
    conn = get_conn()
    rows = conn.execute("SELECT * FROM material_prices ORDER BY timestamp ASC").fetchall()
    conn.close()
    result = {}
    for r in rows:
        d = dict(r)
        material = d["material"]
        if material not in result:
            result[material] = []
        # 只保留日期部分
        d["date"] = d["timestamp"][:10]
        result[material].append(d)
    return jsonify(result)


@app.route("/api/news/summary")
def api_news_summary():
    """AI研判总结"""
    from db import init_db, get_conn
    init_db()
    conn = get_conn()
    # 统计最近新闻的AI方向分布
    rows = conn.execute(
        """SELECT ai_direction, COUNT(*) as cnt
           FROM news WHERE ai_direction != '' AND ai_direction IS NOT NULL
           AND timestamp >= date('now', '-7 days')
           GROUP BY ai_direction"""
    ).fetchall()
    conn.close()

    direction_counts = {r["ai_direction"]: r["cnt"] for r in rows}
    bullish = direction_counts.get("bullish", 0)
    bearish = direction_counts.get("bearish", 0)
    total = bullish + bearish

    if total > 0:
        ratio = round(bullish / total * 100)
        if ratio > 60:
            overall = "偏多"
        elif ratio < 40:
            overall = "偏空"
        else:
            overall = "中性"
    else:
        overall = "数据不足"
        ratio = 50

    return jsonify({
        "overall": overall,
        "bullish_pct": ratio,
        "bullish_count": bullish,
        "bearish_count": bearish,
        "total_analyzed": total,
    })

@app.route("/api/signals")
def api_signals():
    """信号列表（旧版）"""
    from db import init_db, get_conn
    init_db()
    limit = int(__import__("flask").request.args.get("limit", 50))
    conn = get_conn()
    rows = conn.execute("SELECT * FROM signals ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


# ============================================================
# 先行信号 v2 API
# ============================================================
@app.route("/api/signals/v2")
def api_signals_v2():
    """活跃先行信号列表"""
    from db import init_db, get_active_signals, get_signal_stats
    init_db()
    signals = get_active_signals(limit=50)
    stats = get_signal_stats()
    return jsonify({"signals": signals, "stats": stats})


@app.route("/api/signals/v2/all")
def api_signals_v2_all():
    """所有信号（带过滤）"""
    from db import init_db, get_all_signals
    init_db()
    req = __import__("flask").request
    status = req.args.get("status")
    source = req.args.get("source")
    limit = int(req.args.get("limit", 100))
    signals = get_all_signals(limit=limit, status=status, source=source)
    return jsonify(signals)


@app.route("/api/signals/v2/sector/<sector>")
def api_signals_v2_sector(sector):
    """按板块查询信号"""
    from db import init_db, get_signals_by_sector
    init_db()
    signals = get_signals_by_sector(sector)
    return jsonify(signals)


@app.route("/api/signals/v2/run-detect", methods=["POST"])
def api_run_detect():
    """手动触发信号检测"""
    from detect_runner import run_all_detectors
    signals = run_all_detectors()
    return jsonify({
        "detected": len(signals),
        "message": f"检测完成，产生 {len(signals)} 个信号"
    })


@app.route("/api/report")
def api_report():
    """AI研判报告"""
    from analyzers.ai_engine import generate_signal_report
    report = generate_signal_report()
    return jsonify(report)


@app.route("/api/verify", methods=["POST"])
def api_verify():
    """运行信号验证"""
    from verifier import verify_signals, get_accuracy_by_source, get_accuracy_by_severity
    results = verify_signals()
    results["by_source"] = get_accuracy_by_source()
    results["by_severity"] = get_accuracy_by_severity()
    return jsonify(results)


@app.route("/api/verify/stats")
def api_verify_stats():
    """验证统计"""
    from verifier import (get_accuracy_by_source, get_accuracy_by_type,
                          get_accuracy_by_severity, get_recent_verifications)
    return jsonify({
        "by_source": get_accuracy_by_source(),
        "by_type": get_accuracy_by_type(),
        "by_severity": get_accuracy_by_severity(),
        "recent": get_recent_verifications(20),
    })

@app.route("/api/ai-analysis")
def api_ai_analysis():
    """AI分析结果"""
    from db import init_db, get_ai_analysis_recent
    init_db()
    result = get_ai_analysis_recent(limit=20)
    return jsonify(result)

@app.route("/api/predictions")
def api_predictions():
    """预测统计"""
    from db import init_db
    from predictor import get_prediction_stats, get_calibration_history
    init_db()
    stats = get_prediction_stats()
    calibrations = get_calibration_history(limit=10)
    return jsonify({"stats": stats, "calibrations": calibrations})

@app.route("/api/discoveries")
def api_discoveries():
    """发现的新标的"""
    from db import init_db
    from discoverer import get_pending_discoveries
    init_db()
    discoveries = get_pending_discoveries()
    return jsonify(discoveries)

@app.route("/api/leading-indicators")
def api_leading_indicators():
    """先行指标数据"""
    from db import init_db
    from collectors.leading_collector import collect_all_leading_indicators
    from analyzers.leading_engine import run_leading_analysis
    init_db()
    raw = collect_all_leading_indicators()
    result = run_leading_analysis(raw)
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
