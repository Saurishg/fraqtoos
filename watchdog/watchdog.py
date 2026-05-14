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
MODEL_CHAIN  = ["phi4", "deepseek-r1:14b", "qwen3:14b"]
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
    log.error("Ollama is DOWN and failed to auto-restart (WhatsApp suppressed)")
    return False

# ── Bot registry ──────────────────────────────────────────────────────────────

def latest_log(pattern: str) -> str:
    """Dynamically find the newest log matching a glob pattern."""
    files = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
    return files[0] if files else None

BOTS = [
    # ── Persistent daemons (always-running, alert if not found) ──────────────
    {
        "name":     "Orchestrator",
        "proc":     "orchestrator.py",
        "log":      "/home/work/fraqtoos/logs/fraqtoos.log",
        "critical": True,
    },
    {
        "name":     "WhatsApp Service",
        "proc":     "wa-service",
        "log":      None,
        "critical": True,
    },
    # ── Scheduled one-shots (run briefly at scheduled time, never persistent) ─
    # scheduled=True → watchdog skips the "is it running?" check and only
    # checks the log for recent errors.
    {
        "name":      "Portfolio Bot",
        "proc":      "portfolio_bot.py",
        "log":       "/home/work/portfolio_bot/logs/portfolio.log",
        "critical":  False,
        "scheduled": True,   # one-shot at 06:00 — not a daemon
        "max_age_h": 30,
    },
    {
        "name":      "Utility Bill Bot",
        "proc":      "bot.js",
        "log":       "/home/work/fraqtoos/logs/fraqtoos.log",  # logged via orchestrator runner
        "critical":  False,
        "scheduled": True,   # one-shot at 10:00
        "max_age_h": 30,
    },
    {
        "name":      "BTC Strategy Bot",
        "proc":      "btc_strategy.py",
        "log":       "/home/work/fraqtoos/logs/fraqtoos.log",
        "critical":  False,
        "scheduled": True,   # one-shot at 22:00
        "max_age_h": 30,
    },
    {
        "name":      "Chia Health Monitor",
        "proc":      "chia_health",
        "log":       "/home/work/fraqtoos/logs/fraqtoos.log",
        "critical":  False,
        "scheduled": True,   # one-shot at 08:00
        "max_age_h": 30,
    },
    {
        "name":      "Chia AI Watcher",
        "proc":      "chia_ai_watcher",
        "log":       "/home/work/fraqtoos/logs/chia_ai_latest.json",
        "critical":  False,
        "scheduled": True,   # every 2h
        "max_age_h": 6,
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
    # Timeouts matter: nvidia-smi can hang indefinitely during GPU IPC firmware
    # stalls (see fraqtoos memory: nvidia_ipc_fix). Without timeout the entire
    # watchdog blocks and orchestrator never schedules anything else.
    def _run(cmd, t=10):
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=t)
        except (subprocess.TimeoutExpired, Exception):
            return None
    disk = _run(["df", "-h", "/home/work"], 5)
    ram  = _run(["free", "-h"], 5)
    gpu  = _run(["nvidia-smi", "--query-gpu=memory.used,memory.free,temperature.gpu",
                 "--format=csv,noheader"], 10)
    return {
        "disk": disk.stdout.strip().splitlines()[-1] if disk and disk.stdout else "?",
        "ram":  ram.stdout.strip().splitlines()[1]   if ram  and ram.stdout  else "?",
        "gpu":  gpu.stdout.strip() if gpu and gpu.returncode == 0 else "N/A",
    }

def scheduled_run_health(bot: dict) -> tuple[list[str], str]:
    """Return errors and display tail for one-shot jobs from canonical state.json.

    Scheduled bots share the orchestrator log, so scanning that log for words like
    "exception" attributes unrelated watchdog/AI prose to every scheduled bot.
    state.json is the per-bot source of truth for these jobs.
    """
    run = st.get_all_runs().get(bot["name"], {})
    if not run:
        return [f"{bot['name']} has never recorded a run"], "(no recorded run)"

    tail = run.get("last_output") or ""
    errors = []
    if not run.get("success", False):
        errors.append(f"last run failed: {tail[:120] or 'no output'}")

    max_age_h = bot.get("max_age_h")
    last_run = run.get("last_run")
    age_h = None
    if max_age_h and last_run:
        try:
            age_h = (datetime.now() - datetime.strptime(last_run, "%Y-%m-%d %H:%M:%S")).total_seconds() / 3600
            if age_h > max_age_h:
                errors.append(f"stale: last run {age_h:.1f}h ago")
        except Exception:
            errors.append(f"invalid last_run timestamp: {last_run}")

    status = "OK" if not errors else "ISSUE"
    age_text = f" age={age_h:.1f}h" if age_h is not None else ""
    output_text = f"\n{tail}" if errors and tail else ""
    display = (
        f"{status} last_run={run.get('last_run', '?')} "
        f"duration={run.get('duration', '?')}s{age_text} success={run.get('success', False)}"
        f"{output_text}"
    ).strip()
    return errors[-3:], display[-500:]

# ── AI diagnosis ──────────────────────────────────────────────────────────────

def ai_diagnose(snapshot: dict) -> str:
    if not ensure_ollama_up():
        return "AI unavailable (ollama down — restart failed, alerted)"

    prompt = f"""DevOps watchdog. Analyze this bot health snapshot in under 200 words.
State: OK / WARNING / CRITICAL. List problems and one-line fixes.

RULES:
- Bots marked scheduled=true are one-shot scripts. "running: false" is NORMAL — do NOT flag it.
- Only flag scheduled bots if their logs show recent errors or they haven't run in >24h.
- For scheduled bots, trust their "errors" array. If errors is empty, the scheduled bot is OK.
- Do not infer stale status from last_run text; stale scheduled runs are already listed in errors.
- Disk usage below 90% is NORMAL and acceptable — do NOT flag it. Only flag disk if use% >= 90.
- Disk threshold is 90%. Current usage around 70% is fine.

{json.dumps(snapshot, indent=2)[:2500]}"""

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
        if bot.get("scheduled"):
            continue  # one-shot bots are never persistently running — skip
        running = is_running(bot["proc"])
        if bot["critical"] and not running:
            issues.append(f"CRITICAL: {bot['name']} is NOT running!")
    if issues:
        log.warning("Watchdog issues (WhatsApp suppressed): " + "; ".join(issues))
        return False
    log.info("Watchdog lightweight: all critical processes OK")
    return True

def run_full(force_alert: bool = False) -> dict:
    """Full check with log analysis and AI diagnosis."""
    log.info("Watchdog full check starting...")
    snapshot = {"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "system": sys_stats(), "bots": []}

    # SearXNG health (web search backend used by agent)
    try:
        from core.web_search import is_up as _searx_up
        snapshot["searxng_up"] = _searx_up()
    except Exception as e:
        snapshot["searxng_up"] = False
        log.warning(f"web_search probe failed: {e}")

    for bot in BOTS:
        running  = False if bot.get("scheduled") else is_running(bot["proc"])
        if bot.get("scheduled"):
            errors, log_tail = scheduled_run_health(bot)
        else:
            log_tail = tail_log(bot)
            # Only scan lines that start with a log timestamp (YYYY-MM-DD HH:MM:SS).
            # Raw AI-prose lines (markdown bullets, numbered lists) bleed into the log
            # without a timestamp prefix and would create false-positive error matches.
            import re as _re
            _ts = _re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")
            errors   = [l.strip()[:120] for l in log_tail.splitlines()
                        if _ts.match(l.strip())
                        and any(k in l.lower() for k in ["error","traceback","exception","timeout","failed"])
                        and "watchdog"    not in l.lower()
                        and "ruflo_fixer" not in l.lower()
                        and "context:"    not in l.lower()]
        # For daemon logs: keep only timestamped operational lines.
        # Exclude watchdog/fixer meta-lines — phi4 reads log_tail and would
        # re-diagnose its own previous diagnosis in an infinite feedback loop.
        _skip_loggers = ("watchdog", "ruflo_fixer", "ai diagnosis")
        clean_tail = "\n".join(
            l for l in log_tail.splitlines()
            if _ts.match(l.strip())
            and not any(s in l.lower() for s in _skip_loggers)
        ) if not bot.get("scheduled") else log_tail

        snapshot["bots"].append({
            "name":      bot["name"],
            "running":   running,
            "scheduled": bot.get("scheduled", False),
            "critical":  bot["critical"],
            "errors":    errors[-3:],
            "log_tail":  clean_tail[-500:]
        })

    analysis = ai_diagnose(snapshot)
    # Log only the first line (state) — full multi-line AI prose in the log
    # creates a self-referential feedback loop on the next scan.
    log.info(f"AI diagnosis: {analysis.splitlines()[0].strip()[:120]}")

    # Save latest report
    with open("/home/work/fraqtoos/logs/watchdog_latest.json", "w") as f:
        json.dump({"snapshot": snapshot, "analysis": analysis}, f, indent=2)

    # Push to ruflo memory for agent context (non-blocking, best-effort)
    try:
        import importlib.util as _ilu
        _spec = _ilu.spec_from_file_location(
            "ruflo_report", "/home/work/fraqtoos/watchdog/ruflo_report.py")
        _mod = _ilu.module_from_spec(_spec); _spec.loader.exec_module(_mod)
        _mod.push_to_ruflo(snapshot, analysis)
    except Exception as _e:
        log.warning(f"ruflo push failed: {_e}")

    st.set("last_watchdog", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    # ── RuFlo auto-fixer ──────────────────────────────────────────────────────
    # Spawn Claude Code agents to fix any code-level errors, then commit+push.
    fixer_results = []
    any_errors = any(b.get("errors") for b in snapshot["bots"])
    if any_errors:
        try:
            from watchdog.ruflo_fixer import run_fixer, format_wa_summary
            fixer_results = run_fixer(snapshot)
            if fixer_results:
                summary = format_wa_summary(fixer_results)
                if summary:
                    log.info(f"RuFlo fixer result (silent): {summary[:100]}")
        except Exception as _fe:
            log.warning(f"ruflo_fixer error: {_fe}")

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

    searx_down = snapshot.get("searxng_up") is False
    if searx_down:
        log.warning("SearXNG is DOWN — web context will be empty")

    if force_alert or critical_down or ai_bad or disk_full or searx_down:
        bots_status = "\n".join([
            f"{'🟢' if b['running'] else ('🔴' if b['critical'] else '🟡')} {b['name']}"
            + (f"\n   ↳ {b['errors'][-1]}" if b['errors'] else "")
            for b in snapshot["bots"]
        ])
        extra = "\n⚠ SearXNG DOWN" if searx_down else ""
        log.warning(f"Watchdog alert suppressed (WATCHDOG_SILENT=1): {bots_status}")
    else:
        log.info("Watchdog: all systems healthy")

    return snapshot

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "full"
    if mode == "light":
        run_lightweight()
    else:
        run_full(force_alert="--alert" in sys.argv)
