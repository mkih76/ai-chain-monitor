"""
AI产业链监控 - 自动调度器
每交易日定时执行: 采集→分析→AI研判→推送→预测记录→回测校准
非交易日自动跳过，支持手动触发
"""
import sys
import os
import time
import signal
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

# ============================================================
# 交易日判断
# ============================================================
def is_trading_day():
    """判断今天是否为A股交易日（简易版：周一到周五）"""
    today = datetime.now()
    if today.weekday() >= 5:  # 周末
        return False
    # TODO: 接入节假日API，排除法定假日
    return True

# ============================================================
# 定时任务
# ============================================================
def job_morning_overseas():
    """每早8:30 - 海外隔夜异动预警（A股开盘前）"""
    if not is_trading_day():
        print(f"[{now()}] 非交易日，跳过海外预警")
        return
    print(f"\n{'='*50}")
    print(f"[{now()}] 晨间任务: 海外隔夜异动预警")
    print(f"{'='*50}")
    try:
        from db import init_db
        from collectors.overseas_collector import collect_overseas_stocks, get_overnight_changes
        from notifiers.telegram_notifier import push_overnight_alert
        init_db()
        collect_overseas_stocks()
        alerts = get_overnight_changes()
        if alerts:
            push_overnight_alert(alerts)
            print(f"  ✓ 推送 {len(alerts)} 条海外异动预警")
        else:
            print(f"  无显著海外异动")
    except Exception as e:
        print(f"  ✗ 海外预警失败: {e}")

def job_afternoon_full():
    """每交易日16:00 - 完整采集+分析+AI研判+推送+预测记录"""
    if not is_trading_day():
        print(f"[{now()}] 非交易日，跳过完整运行")
        return
    print(f"\n{'='*50}")
    print(f"[{now()}] 午后任务: 完整采集分析")
    print(f"{'='*50}")
    try:
        from main import run_full
        result = run_full()

        # 记录AI预测
        if result.get("ai_result"):
            _record_prediction(result["ai_result"])

        # 运行回测校准
        _run_backtest()

        # 先行指标采集+分析
        _run_leading_indicators()
    except Exception as e:
        print(f"  ✗ 完整运行失败: {e}")

def job_night_discover():
    """每晚21:00 - 自动发现新标的（非交易时间，低频）"""
    print(f"\n{'='*50}")
    print(f"[{now()}] 晚间任务: 自动发现新标的")
    print(f"{'='*50}")
    try:
        from discoverer import run_discovery
        suggestions = run_discovery()
        if suggestions:
            print(f"  发现 {len(suggestions)} 个潜在新标的")
        else:
            print(f"  暂无新发现")
    except Exception as e:
        print(f"  ✗ 发现任务失败: {e}")

def job_weekly_backtest():
    """每周日20:00 - 周度回测校准"""
    print(f"\n{'='*50}")
    print(f"[{now()}] 周度任务: 回测校准")
    print(f"{'='*50}")
    try:
        from predictor import weekly_backtest, auto_calibrate
        stats = weekly_backtest()
        if stats:
            calibrations = auto_calibrate(stats)
            if calibrations:
                print(f"  自动校准 {len(calibrations)} 个阈值")
    except Exception as e:
        print(f"  ✗ 回测校准失败: {e}")

def _record_prediction(ai_result):
    """将AI预测结果记录到预测表"""
    try:
        from predictor import save_prediction
        direction = ai_result.get("direction", "neutral")
        confidence = ai_result.get("confidence", "low")

        # 记录全局预测
        save_prediction(
            target="GLOBAL",
            direction=direction,
            confidence=confidence,
            catalyst=ai_result.get("catalyst", ""),
            risk=ai_result.get("risk", ""),
            action=ai_result.get("action", ""),
        )

        # 记录个股预测
        for pick in ai_result.get("top_picks", []):
            save_prediction(
                target=pick.get("code", ""),
                direction=pick.get("direction", "neutral"),
                confidence=confidence,
                catalyst=pick.get("reason", ""),
                risk="",
                action="",
            )
    except Exception as e:
        print(f"  ⚠ 预测记录失败: {e}")

def _run_backtest():
    """运行回测：检查已到期的预测，对比实际涨跌"""
    try:
        from predictor import backtest_expired_predictions
        results = backtest_expired_predictions()
        if results:
            correct = sum(1 for r in results if r["correct"])
            total = len(results)
            print(f"  回测: {correct}/{total} 预测正确 ({correct/total*100:.0f}%)")
    except Exception as e:
        print(f"  ⚠ 回测失败: {e}")

def _run_leading_indicators():
    """运行先行指标采集和分析"""
    try:
        from collectors.leading_collector import collect_all_leading_indicators
        from analyzers.leading_engine import run_leading_analysis
        raw = collect_all_leading_indicators()
        result = run_leading_analysis(raw)
        high_count = result["summary"].get("high_signals", 0)
        resonance_count = result["summary"].get("resonances", 0)
        print(f"  先行指标: {high_count}个高优信号, {resonance_count}个共振板块")
    except Exception as e:
        print(f"  ⚠ 先行指标失败: {e}")

def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# ============================================================
# 调度器启动
# ============================================================
def start_scheduler():
    """启动调度器"""
    scheduler = BlockingScheduler(timezone="Asia/Shanghai")

    # 海外隔夜预警: 每个交易日 08:30
    scheduler.add_job(
        job_morning_overseas,
        CronTrigger(day_of_week="mon-fri", hour=8, minute=30),
        id="morning_overseas",
        name="海外隔夜异动预警",
    )

    # 完整采集分析: 每个交易日 16:00
    scheduler.add_job(
        job_afternoon_full,
        CronTrigger(day_of_week="mon-fri", hour=16, minute=0),
        id="afternoon_full",
        name="完整采集分析",
    )

    # 自动发现新标的: 每天 21:00
    scheduler.add_job(
        job_night_discover,
        CronTrigger(day_of_week="mon-sun", hour=21, minute=0),
        id="night_discover",
        name="自动发现新标的",
    )

    # 周度回测校准: 每周日 20:00
    scheduler.add_job(
        job_weekly_backtest,
        CronTrigger(day_of_week="sun", hour=20, minute=0),
        id="weekly_backtest",
        name="周度回测校准",
    )

    print(f"[{now()}] 调度器已启动")
    print(f"  08:30 海外隔夜异动预警 (周一-周五)")
    print(f"  16:00 完整采集分析 (周一-周五)")
    print(f"  21:00 自动发现新标的 (每天)")
    print(f"  20:00 周度回测校准 (周日)")
    print(f"  按 Ctrl+C 停止")

    # 优雅退出
    def shutdown(sig, frame):
        print(f"\n[{now()}] 调度器停止")
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print(f"\n[{now()}] 调度器已停止")

def run_once():
    """立即执行一次完整流程（用于测试）"""
    print(f"[{now()}] 立即执行一次完整流程")
    job_afternoon_full()

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "once":
        run_once()
    else:
        start_scheduler()
