#!/usr/bin/env python3
"""
FraqtoOS Watchdog — two modes:
  lightweight  (every 30 min) — process check only, no AI, fast
  full         (every 4 hrs)  — process + log analysis + AI diagnosis
"""
import os, sys, subprocess, json, requests, time, glob
from datetime import datetime
from pathlib import Path

sys.path.insert(0, "/home/work/fraqtoos")
from core.logger   import get_logger
from core.notifier import send_alert
from core          import state as st

log = get_logger("watchdog")
OLLAMA_URL   = "http://localhost:11434/api/generate"
OLLAMA_PROBE = "http://localhost:11434/api/tags"
MODEL_CHAIN  = ["phi4", "deepseek-r1:14b", "gemma4"]
DISK_WARN_PCT = 90

def ensure_ollama_up(attempts: int = 2) -> bool:
    """Probe ollama; if down, try systemctl restart. Alert on persistent failure."""
    for i in range(attempts):
        try:
            r = requests.get(OLLAMA_PROBE, timeout=3)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        if i == 0:
            log.warning("Ollama down — attempting systemctl restart")
            try:
                subprocess.run(
                    ["sudo", "-n", "systemctl", "restart", "ollama"],
                    capture_output=True, timeout=30
                )
            except Exception as e:
                log.error(f"ollama restart failed: {e}")
            time.sleep(8)
    log.error("Ollama unreachable after restart attempt")
    send_alert("FraqtoOS", "⚠ Ollama is DOWN and failed to auto-restart")
    return False

# ── Bot registry ──────────────────────────────────────────────────────────────

def latest_log(pattern: str) -> str:
    """Dynamically find the newest log matching a glob pattern."""
    files = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
    return files[0] if files else None

BOTS = [
    {
        "name":    "Orchestrator",
        "proc":    "orchestrator.py",
        "log":     "/home/work/fraqtoos/logs/fraqtoos.log",
        "critical": True,
    },
    {
        "name":    "Amazon Deletion",
        "proc":    "delete_missing_info.py",
        "log":     None,  # dynamic
        "log_glob": "/home/work/amazon-bot/logs/delete_missing_*.log",
        "critical": False,
    },
    {
        "name":    "Portfolio Bot",
        "proc":    "portfolio_bot.py",
        "log":     "/home/work/portfolio_bot/logs/portfolio.log",
        "critical": False,
    },
    {
        "name":    "Utility Bill Bot",
        "proc":    "bot.js",
        "log":     "/home/work/utility-bill-bot/logs/bot.log",
        "critical": False,
    },
    {
        "name":    "BTC Bot",
        "proc":    "btc_strategy.py",
        "log":     None,
        "critical": False,
    },
]

# ── Collectors ────────────────────────────────────────────────────────────────

def is_running(keyword: str) -> bool:
    r = subprocess.run(["pgrep", "-af", keyword], capture_output=True, text=True)
    return any(keyword in l and "grep" not in l and "watchdog" not in l
               for l in r.stdout.splitlines())

def tail_log(bot: dict, lines: int = 20) -> str:
    path = bot.get("log") or (latest_log(bot["log_glob"]) if bot.get("log_glob") else None)
    if not path or not Path(path).exists():
        return "(no log)"
    r = subprocess.run(["tail", f"-{lines}", path], capture_output=True, text=True)
    return r.stdout.strip()

def sys_stats() -> dict:
    disk = subprocess.run(["df", "-h", "/home/work"], capture_output=True, text=True)
    ram  = subprocess.run(["free", "-h"], capture_output=True, text=True)
    gpu  = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.free,temperature.gpu",
                           "--format=csv,noheader"], capture_output=True, text=True)
    return {
        "disk": disk.stdout.strip().splitlines()[-1] if disk.stdout else "?",
        "ram":  ram.stdout.strip().splitlines()[1]   if ram.stdout  else "?",
        "gpu":  gpu.stdout.strip()                   if gpu.returncode == 0 else "N/A",
    }

# ── AI diagnosis ──────────────────────────────────────────────────────────────

def ai_diagnose(snapshot: dict) -> str:
    if not ensure_ollama_up():
        return "AI unavailable (ollama down — restart failed, alerted)"

    prompt = f"""DevOps watchdog. Analyze this bot health snapshot in under 200 words.
State: OK / WARNING / CRITICAL. List problems and one-line fixes.

{json.dumps(snapshot, indent=2)[:2000]}"""

    for model in MODEL_CHAIN:
        try:
            r = requests.post(OLLAMA_URL, json={
                "model": model, "prompt": prompt, "stream": False,
                "options": {"temperature": 0.1, "num_predict": 400}
            }, timeout=120)
            r.raise_for_status()
            content = r.json()["response"].strip()
            if content and len(content) > 20:
                return content
        except Exception as e:
            log.warning(f"AI model {model} failed: {e}")
    return "AI unavailable"

# ── Main ──────────────────────────────────────────────────────────────────────

def run_lightweight() -> bool:
    """Quick process check — no AI, no log reading. Returns True if all OK."""
    issues = []
    for bot in BOTS:
        running = is_running(bot["proc"])
        if bot["critical"] and not running:
            issues.append(f"CRITICAL: {bot['name']} is NOT running!")
    if issues:
        send_alert("FraqtoOS Watchdog", "\n".join(issues))
        return False
    log.info("Watchdog lightweight: all critical processes OK")
    return True

def run_full(force_alert: bool = False) -> dict:
    """Full check with log analysis and AI diagnosis."""
    log.info("Watchdog full check starting...")
    snapshot = {"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "system": sys_stats(), "bots": []}

    for bot in BOTS:
        running  = is_running(bot["proc"])
        log_tail = tail_log(bot)
        errors   = [l.strip()[:120] for l in log_tail.splitlines()
                    if any(k in l.lower() for k in ["error","traceback","exception","timeout","failed"])]
        snapshot["bots"].append({
            "name": bot["name"], "running": running,
            "critical": bot["critical"], "errors": errors[-3:],
            "log_tail": log_tail[-500:]
        })

    analysis = ai_diagnose(snapshot)
    log.info(f"AI diagnosis: {analysis[:200]}")

    # Save latest report
    with open("/home/work/fraqtoos/logs/watchdog_latest.json", "w") as f:
        json.dump({"snapshot": snapshot, "analysis": analysis}, f, indent=2)

    st.set("last_watchdog", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    critical_down = any(b["critical"] and not b["running"] for b in snapshot["bots"])
    ai_bad = any(k in analysis.upper() for k in ["CRITICAL", "WARNING"])

    # Disk alert
    disk_line = snapshot["system"].get("disk", "")
    disk_full = False
    try:
        pct = int(disk_line.split()[4].rstrip("%"))
        if pct >= DISK_WARN_PCT:
            disk_full = True
            log.warning(f"Disk at {pct}% — alerting")
    except Exception:
        pass

    if force_alert or critical_down or ai_bad or disk_full:
        bots_status = "\n".join([
            f"{'🟢' if b['running'] else ('🔴' if b['critical'] else '🟡')} {b['name']}"
            + (f"\n   ↳ {b['errors'][-1]}" if b['errors'] else "")
            for b in snapshot["bots"]
        ])
        send_alert("FraqtoOS Watchdog", f"{bots_status}\n\n{analysis[:400]}")
    else:
        log.info("Watchdog: all systems healthy")

    return snapshot

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "full"
    if mode == "light":
        run_lightweight()
    else:
        run_full(force_alert="--alert" in sys.argv)
