#!/usr/bin/env python3
"""
FraqtoOS Dashboard — run `python3 dashboard.py` for live bot status.
Shows last run, success/fail, next scheduled run, system stats.
"""
import os, sys, json, subprocess
from datetime import datetime
sys.path.insert(0, "/home/work/fraqtoos")
from core import state as st

def clear(): os.system("clear")

def gpu_stats():
    r = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.used,memory.free,temperature.gpu,utilization.gpu",
                        "--format=csv,noheader"], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else "N/A"

def ram_stats():
    r = subprocess.run(["free", "-h"], capture_output=True, text=True)
    lines = r.stdout.strip().splitlines()
    return lines[1] if lines else "N/A"

def disk_stats():
    r = subprocess.run(["df", "-h", "/home/work"], capture_output=True, text=True)
    lines = r.stdout.strip().splitlines()
    return lines[-1] if lines else "N/A"

def is_running(keyword):
    r = subprocess.run(["pgrep", "-af", keyword], capture_output=True, text=True)
    return any(keyword in l and "grep" not in l for l in r.stdout.splitlines())

BOTS_DISPLAY = [
    ("Orchestrator",     "orchestrator.py"),
    ("Amazon Deletion",  "delete_missing_info.py"),
    ("Amazon Listings",  "fix4_final.py"),
    ("Portfolio Bot",    "portfolio_bot.py"),
    ("Utility Bill Bot", "bot.js"),
    ("BTC Bot",          "btc_strategy.py"),
    ("Gemma Agent",      "agent.py"),
    ("Watchdog",         "watchdog.py"),
]

SCHEDULE = [
    ("06:00", "Portfolio Bot"),
    ("07:00", "AI Agent Analysis"),
    ("08:00", "Amazon (delete + reviews)"),
    ("10:00", "Utility Bill Bot"),
    ("12:00", "Watchdog Full Check"),
    ("18:00", "Amazon (listing update)"),
    ("22:00", "BTC Bot"),
    ("23:00", "Daily WhatsApp Digest"),
]

def render():
    clear()
    now = datetime.now()
    runs = st.get_all_runs()

    print("=" * 65)
    print(f"  🤖  FraqtoOS Dashboard          {now.strftime('%Y-%m-%d  %H:%M:%S')}")
    print("=" * 65)

    print("\n📊 BOT STATUS")
    print(f"  {'Bot':<22} {'Running':<10} {'Last Run':<20} {'Result'}")
    print("  " + "-" * 60)
    for name, proc in BOTS_DISPLAY:
        running = is_running(proc)
        run_data = runs.get(name, {})
        last_run = run_data.get("last_run", "never")
        success  = run_data.get("success", None)
        status   = "🟢 YES" if running else "⚫ NO "
        result   = ("✓ OK" if success else "✗ FAIL") if success is not None else "—"
        print(f"  {name:<22} {status:<10} {last_run:<20} {result}")

    print("\n⏰ TODAY'S SCHEDULE")
    for time_str, task in SCHEDULE:
        past = now.strftime("%H:%M") > time_str
        icon = "✓" if past else "○"
        print(f"  {icon} {time_str}  {task}")

    print("\n💻 SYSTEM")
    print(f"  RAM:  {ram_stats()}")
    print(f"  DISK: {disk_stats()}")
    for line in gpu_stats().splitlines():
        print(f"  GPU:  {line}")

    # Load watchdog report
    try:
        wd = json.load(open("/home/work/fraqtoos/logs/watchdog_latest.json"))
        analysis = wd.get("analysis", "")[:200]
        last_wd  = wd.get("snapshot", {}).get("timestamp", "unknown")
        print(f"\n🔍 LAST WATCHDOG: {last_wd}")
        print(f"  {analysis}")
    except Exception:
        print("\n🔍 WATCHDOG: No report yet")

    print("\n" + "=" * 65)
    print("  Press Ctrl+C to exit  |  Refreshes every 30s")
    print("=" * 65)

if __name__ == "__main__":
    import time
    try:
        while True:
            render()
            time.sleep(30)
    except KeyboardInterrupt:
        print("\nBye!")
