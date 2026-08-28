#!/usr/bin/env python3
"""
FraqtoOS Master Orchestrator — single source of truth for all bot scheduling.
Runs on boot via systemd (fraqtoos.service).

Schedule:
  Every 30m  Watchdog lightweight (process check)
  Every 2h   Chia AI log watcher (phi4 classifies new errors)
  Every 4h   Watchdog full (AI diagnosis)
  06:00      Portfolio Bot
  07:00      AI Agent — morning market analysis
  08:00      Chia Health Monitor (rule-based daily summary)
  10:00      Utility Bill Bot
  12:00      Watchdog full check
  10:10      IPO Last-Day Alert (closing today, GMP >= 30%) — the only IPO msg
  09:00      Crypto Portfolio Bot (Hive)
  21:00      Crypto Portfolio Bot (Hive)
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
        # Pinned to a dedicated venv, not bare `python3`: the system default
        # python3 moved 3.10 -> 3.12, which orphaned this bot's deps (pyotp,
        # pandas, py5paisa, selenium all lived only in ~/.local/.../python3.10).
        "cmd":     "/home/work/.venvs/portfolio/bin/python portfolio_bot.py",
        "cwd":     "/home/work/portfolio_bot",
        "timeout": 300,
        "retries": 1,
    },
    "utility_bill": {
        "name":    "Utility Bill Bot",
        "cmd":     "node bot.js --once",
        "cwd":     "/home/work/utility-bill-bot",
        "timeout": 300,
        "retries": 1,
    },
    "crypto_portfolio": {
        "name":    "Crypto Portfolio Bot",
        "cmd":     "node index.js --once",
        "cwd":     "/home/work/Desktop/crypto",
        # Worst case: Hive 429 retries (~30s) + phi4 brief (45s) + WhatsApp send (120s)
        "timeout": 300,
        "retries": 1,
    },
    "ipo": {
        "name":    "IPO Bot",
        # NOT SCHEDULED — the full board (open + upcoming) at the 30% floor.
        # Run by hand: `orchestrator.py --run ipo`. The scheduled daily message
        # is `ipo_lastday`; the unfiltered board is the `ipo` WhatsApp keyword.
        # Scheduled runs are filtered to the high-GMP shortlist (user's call,
        # 2026-08-28). The unfiltered board is still one `ipo` WhatsApp keyword
        # away, or `ipo_bot.py` with no flags.
        "cmd":     "/usr/bin/python3.12 ipo_bot.py --min-gmp 30",
        "cwd":     "/home/work/ipo-bot",
        # NSE cookie handshake + one ipo-detail call per open issue + the
        # ipowatch scrape, then a WhatsApp send (~120s worst case).
        "timeout": 240,
        "retries": 1,
    },
    "ipo_lastday": {
        "name":    "IPO Last-Day Alert",
        # THE scheduled IPO message (10:10 daily). Live + last day to apply +
        # GMP >= 30%; upcoming issues are excluded by design.
        # ipo_bot skips the send outright when nothing matches, so a quiet day
        # is silent, not an empty message.
        "cmd":     "/usr/bin/python3.12 ipo_bot.py --min-gmp 30 --closing-today",
        "cwd":     "/home/work/ipo-bot",
        "timeout": 240,
        "retries": 1,
    },
    "chia_health": {
        "name":    "Chia Health Monitor",
        "cmd":     "/usr/bin/python3.12 -c \"import sys; sys.path.insert(0,'/home/work/fraqtoos'); from bots.chia_health import run; print(run())\"",
        "cwd":     "/home/work/fraqtoos",
        "timeout": 60,
        "retries": 0,
        "silent":  True,
    },
    "chia_ai": {
        "name":    "Chia AI Watcher",
        "cmd":     "/usr/bin/python3.12 -c \"import sys; sys.path.insert(0,'/home/work/fraqtoos'); from bots.chia_ai_watcher import run; print(run())\"",
        "cwd":     "/home/work/fraqtoos",
        "timeout": 150,   # phi4 inference can take ~2min on cold log batch
        "retries": 0,
        "silent":  True,  # only WhatsApps on critical — suppresses daily_results noise
    },
}

daily_results = []

# ── Job runners ───────────────────────────────────────────────────────────────

def job(key: str):
    import fcntl
    b = BOTS[key]
    # Guard: skip if working directory doesn't exist
    if not os.path.isdir(b["cwd"]):
        log.error(f"↯ {b['name']} skipped — cwd not found: {b['cwd']}")
        return
    lock_fd = None
    if b.get("firefox_lock"):
        lock_fd = open("/tmp/firefox.lock", "w")
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log.warning(f"↯ {b['name']} skipped — another Firefox bot holds the lock")
            lock_fd.close()
            return
    try:
        r = run_bot(b["name"], b["cmd"], b["cwd"],
                    timeout=b.get("timeout", 300),
                    retries=b.get("retries", 1))
    finally:
        if lock_fd:
            try: fcntl.flock(lock_fd, fcntl.LOCK_UN); lock_fd.close()
            except Exception: pass
    daily_results.append(r)
    if not r["success"] and not b.get("silent"):
        send_alert(b["name"], r["output"][-300:])

def run_ai_agent(task: str):
    """Run gemma agent with a task — fire and forget."""
    log.info(f"AI Agent: {task[:60]}")
    try:
        import subprocess
        log_path = f"/tmp/agent_{int(time.time())}.log"
        with open(log_path, 'w') as lf:
            subprocess.Popen(
                ["python3", "/home/work/gemma-agent/agent.py", task],
                env={**os.environ, "DISPLAY": ":0"}, stdout=lf, stderr=lf
            )
        log.info(f"AI Agent started — output: {log_path}")
    except Exception as e:
        log.error(f"AI Agent launch failed: {e}")

def morning_analysis():
    """Launch gemma-agent with smart router (phi4 classifies → best model)."""
    log.info("AI Agent: morning analysis (smart router)")
    try:
        import subprocess
        log_path = f"/tmp/agent_{int(time.time())}.log"
        with open(log_path, 'w') as lf:
            subprocess.Popen(
                ["python3", "/home/work/gemma-agent/agent.py",
                 "Summarize overnight bot status: read /home/work/fraqtoos/logs/watchdog_latest.json "
                 "and write a 3-point morning action plan to /home/work/fraqtoos/logs/morning_plan.txt"],
                env={**os.environ, "DISPLAY": ":0"}, stdout=lf, stderr=lf
            )
        log.info(f"AI Agent started — output: {log_path}")
    except Exception as e:
        log.error(f"morning_analysis launch failed: {e}")

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
schedule.every(2).hours.do(job, "chia_ai")
schedule.every(4).hours.do(run_full)

schedule.every().day.at("06:00").do(job, "portfolio")
schedule.every().day.at("07:00").do(morning_analysis)
schedule.every().day.at("10:00").do(job, "utility_bill")
schedule.every().day.at("12:00").do(run_full)
schedule.every().day.at("08:00").do(job, "chia_health")
schedule.every().day.at("09:00").do(job, "crypto_portfolio")
schedule.every().day.at("21:00").do(job, "crypto_portfolio")
# One message a day, 10:10 — issues on their LAST DAY to apply, GMP >= 30%.
# Upcoming issues are deliberately excluded (2026-08-28): the decision is made
# on the closing day, when subscription figures are complete.
# 10:10 not 10:05: utility_bill runs at 10:00 with a 300s timeout, and the
# scheduler is serial — a slow bill run would otherwise delay this one.
schedule.every().day.at("10:10").do(job, "ipo_lastday")
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
