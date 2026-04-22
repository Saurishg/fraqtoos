#!/usr/bin/env python3
"""
FraqtoOS Master Orchestrator — single source of truth for all bot scheduling.
Runs on boot via systemd (fraqtoos.service).

Schedule:
  Every 30m  Watchdog lightweight (process check)
  Every 4h   Watchdog full (AI diagnosis)
  06:00      Portfolio Bot
  07:00      AI Agent — morning market analysis
  08:00      Amazon: delete waste + request reviews
  10:00      Utility Bill Bot
  12:00      Watchdog full check
  18:00      Amazon: update listings
  22:00      BTC Strategy Bot
  23:00      Daily WhatsApp digest
"""
import schedule, time, sys, os
sys.path.insert(0, "/home/work/fraqtoos")

from core.logger   import get_logger
from core.runner   import run_bot
from core.notifier import send, send_alert
from core          import state as st
from watchdog.watchdog import run_lightweight, run_full
from datetime import datetime

log = get_logger("orchestrator")

# ── Bot definitions ───────────────────────────────────────────────────────────

BOTS = {
    "portfolio": {
        "name":    "Portfolio Bot",
        "cmd":     "python3 portfolio_bot.py",
        "cwd":     "/home/work/portfolio_bot",
        "timeout": 300,
        "retries": 1,
    },
    "amazon_delete": {
        "name":    "Amazon Deletion",
        "cmd":     "python3 scripts/delete_missing_info.py",
        "cwd":     "/home/work/amazon-bot",
        "timeout": 900,
        "retries": 0,
        "silent":  True,
    },
    "amazon_reviews": {
        "name":    "Amazon Reviews",
        "cmd":     "python3 scripts/fix1_request_reviews.py",
        "cwd":     "/home/work/amazon-bot",
        "timeout": 300,
        "retries": 1,
        "silent":  True,
    },
    "amazon_listing": {
        "name":    "Amazon Listings",
        "cmd":     "python3 scripts/fix4_final.py",
        "cwd":     "/home/work/amazon-bot",
        "timeout": 600,
        "retries": 1,
        "silent":  True,
    },
    "utility_bill": {
        "name":    "Utility Bill Bot",
        "cmd":     "node bot.js --once",
        "cwd":     "/home/work/utility-bill-bot",
        "timeout": 300,
        "retries": 1,
    },
    "crypto": {
        "name":    "BTC Strategy Bot",
        "cmd":     "python3 btc_strategy.py",
        "cwd":     "/home/work/crypto-trading-bot",
        "timeout": 300,
        "retries": 0,
    },
}

daily_results = []

# ── Job runners ───────────────────────────────────────────────────────────────

def job(key: str):
    b = BOTS[key]
    r = run_bot(b["name"], b["cmd"], b["cwd"],
                timeout=b.get("timeout", 300),
                retries=b.get("retries", 1))
    daily_results.append(r)
    if not r["success"] and not b.get("silent"):
        send_alert(b["name"], r["output"][-300:])

def run_ai_agent(task: str):
    """Run gemma agent with a task — fire and forget."""
    log.info(f"AI Agent: {task[:60]}")
    try:
        import subprocess
        subprocess.Popen(
            ["python3", "/home/work/gemma-agent/agent.py", "--model", "phi4", task],
            env={**os.environ, "DISPLAY": ":0"}
        )
    except Exception as e:
        log.error(f"AI Agent launch failed: {e}")

def morning_analysis():
    run_ai_agent(
        "Check Amazon account health: read /home/work/amazon-bot/logs/phi4_account_health.txt "
        "and /home/work/amazon-bot/logs/delete_missing_20260419_1125.log last 10 lines. "
        "Write a 3-point morning action plan to /home/work/fraqtoos/logs/morning_plan.txt"
    )

def send_daily_digest():
    global daily_results
    from core.ai_context import generate_digest
    log.info("Generating AI daily digest (llama4 → phi4 fallback)...")
    try:
        digest = generate_digest()
    except Exception as e:
        log.error(f"Digest generation failed: {e}")
        now = datetime.now().strftime("%d %b %Y")
        ok = sum(1 for r in daily_results if r["success"])
        digest = (f"*FraqtoOS Daily — {now}*\n"
                  f"{ok}/{len(daily_results)} bots OK\n(AI digest failed: {e})")
    send(digest)
    daily_results = []
    log.info("Daily digest sent.")

# ── Schedule ──────────────────────────────────────────────────────────────────

schedule.every(30).minutes.do(run_lightweight)
schedule.every(4).hours.do(run_full)

schedule.every().day.at("06:00").do(job, "portfolio")
schedule.every().day.at("07:00").do(morning_analysis)
schedule.every().day.at("08:00").do(job, "amazon_delete")
schedule.every().day.at("08:45").do(job, "amazon_reviews")
schedule.every().day.at("10:00").do(job, "utility_bill")
schedule.every().day.at("12:00").do(run_full)
schedule.every().day.at("18:00").do(job, "amazon_listing")
schedule.every().day.at("22:00").do(job, "crypto")
schedule.every().day.at("23:00").do(send_daily_digest)

# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    args = sys.argv[1:]

    if "--run" in args:
        key = args[args.index("--run") + 1]
        dispatch = {
            "digest":    send_daily_digest,
            "watchdog":  lambda: run_full(force_alert=True),
            "ai":        morning_analysis,
            **{k: (lambda k=k: job(k)) for k in BOTS},
        }
        if key in dispatch:
            dispatch[key]()
        else:
            print(f"Options: {list(dispatch.keys())}")
        sys.exit(0)

    if "--dashboard" in args:
        os.execv(sys.executable, [sys.executable,
                 "/home/work/fraqtoos/dashboard.py"])

    log.info("=" * 55)
    log.info("  FraqtoOS Orchestrator STARTED")
    log.info(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 55)
    for j in schedule.jobs:
        log.info(f"  {j}")

    while True:
        schedule.run_pending()
        time.sleep(30)
