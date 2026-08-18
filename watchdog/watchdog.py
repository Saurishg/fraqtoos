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
MODEL_CHAIN  = ["phi4", "deepseek-r1:14b", "gpt-oss:20b"]
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

# ── Gemini cloud fallback ─────────────────────────────────────────────────────
# Added 2026-08-18. Deliberately a FALLBACK ONLY: the local Ollama chain above
# handles every normal cycle, so this costs nothing until the local AI stack is
# itself the thing that failed - which is exactly when a diagnosis is most
# useful and least available. Hard daily cap protects the API quota; a broken
# or expired key must never stop the watchdog from alerting.
GEMINI_ENV       = os.path.expanduser("~/.gemini/.env")
# Measured 2026-08-18: gemini-flash-latest and 3.7 returned 503 on 2 of 3 calls
# (the alias resolves to the newest, busiest model); 3.6 and 3.5 were 3/3.
# So: reliable model first, alias last as insurance against 3.6 being retired
# the way 2.5-flash was.
GEMINI_MODELS    = ["gemini-3.6-flash", "gemini-3.5-flash", "gemini-flash-latest"]
GEMINI_DAILY_CAP = 20
GEMINI_STATE     = "/tmp/watchdog-gemini-usage.json"

def _gemini_key() -> str:
    k = os.getenv("GEMINI_API_KEY", "").strip()
    if k:
        return k
    try:
        for line in open(GEMINI_ENV):
            if line.startswith("GEMINI_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return ""

def _gemini_budget_ok() -> bool:
    """At most GEMINI_DAILY_CAP calls per day. A crash-looping bot must not be
    able to burn the quota."""
    today = time.strftime("%Y-%m-%d")
    try:
        st = json.load(open(GEMINI_STATE))
    except Exception:
        st = {}
    if st.get("date") != today:
        st = {"date": today, "count": 0}
    if st["count"] >= GEMINI_DAILY_CAP:
        return False
    st["count"] += 1
    try:
        json.dump(st, open(GEMINI_STATE, "w"))
    except Exception:
        pass
    return True

def gemini_diagnose(prompt: str) -> str:
    key = _gemini_key()
    if not key:
        return ""
    if not _gemini_budget_ok():
        log.warning("Gemini fallback skipped: daily cap reached")
        return ""
    for model in GEMINI_MODELS:
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{model}:generateContent?key={key}")
        try:
            r = requests.post(url, timeout=90, json={
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.1, "maxOutputTokens": 500},
            })
            if r.status_code != 200:
                log.warning(f"Gemini {model} HTTP {r.status_code}")
                continue
            txt = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            if txt:
                return f"[via Gemini {model} - local AI was down]\n{txt}"
        except Exception as e:
            log.warning(f"Gemini {model} failed: {str(e).replace(key, '***')}")
    return ""

def ai_diagnose(snapshot: dict) -> str:
    ollama_up = ensure_ollama_up()

    prompt = f"""DevOps watchdog. Analyze this bot health snapshot in under 200 words.
State: OK / WARNING / CRITICAL. List problems and one-line fixes.

RULES:
- Bots marked scheduled=true are one-shot scripts. "running: false" is NORMAL — do NOT flag it.
- Only flag scheduled bots if their logs show recent errors or they haven't run in >24h.
- For scheduled bots, trust their "errors" array. If errors is empty, the scheduled bot is OK.
- Do not infer stale status from last_run text; stale scheduled runs are already listed in errors.
- A running=true service with an empty log_tail is HEALTHY (no errors logged) — do NOT flag "no recent logs" as a problem.
- The errors array is the ONLY source of truth for failures. If a bot's errors array is empty, it is OK — do NOT invent problems from words like "exception" appearing in log_tail prose.
- Disk usage below 90% is NORMAL and acceptable — do NOT flag it. Only flag disk if use% >= 90.
- Disk threshold is 90%. Current usage around 70% is fine.

{json.dumps(snapshot, indent=2)[:2500]}"""

    if not ollama_up:
        g = gemini_diagnose(prompt)
        return g or "AI unavailable (ollama down — restart failed, alerted)"

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
    # every local model failed - try the cloud before giving up
    g = gemini_diagnose(prompt)
    return g or "AI unavailable"

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
                        and True
                        and "context:"    not in l.lower()]
        # For daemon logs: keep only timestamped operational lines.
        # Exclude watchdog/fixer meta-lines — phi4 reads log_tail and would
        # re-diagnose its own previous diagnosis in an infinite feedback loop.
        _skip_loggers = ("watchdog", "ai diagnosis")
        clean_tail = "\n".join(
            l for l in log_tail.splitlines()
            if _ts.match(l.strip())
            and not any(s in l.lower() for s in _skip_loggers)
            # Drop benign "✎ context:" runner notes. These are AI-prose annotations
            # on SUCCESSFUL runs (e.g. "...succeeded but encountered an exception while
            # fetching...") and contain scary words the diagnosis LLM misreads as real
            # failures — the structured errors[] extraction already excludes them (above).
            and "context:" not in l.lower()
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

    searx_down = snapshot.get("searxng_up") is False
    if searx_down:
        log.warning("SearXNG is DOWN — web context will be empty")

    # Alert only on hard signals — critical process down, disk, or a bot with a
    # real error. AI prose ("WARNING" in the diagnosis) is logged but never
    # paged: that noise is why alerts were once silenced entirely, which then
    # hid genuine failures (e.g. Crypto Portfolio timeout 2026-07-01).
    hard_errors = [b for b in snapshot["bots"] if b.get("errors")]
    if force_alert or critical_down or ai_bad or disk_full or searx_down or hard_errors:
        bots_status = "\n".join([
            f"{'🟢' if b['running'] else ('🔴' if b['critical'] else '🟡')} {b['name']}"
            + (f"\n   ↳ {b['errors'][-1]}" if b['errors'] else "")
            for b in snapshot["bots"]
        ])
        extra = "\n⚠ SearXNG DOWN" if searx_down else ""
        if force_alert or critical_down or disk_full or hard_errors:
            # Dedupe: don't re-page the same failure signature every 4h cycle
            sig = "|".join(sorted(
                [f"{b['name']}:{b['errors'][-1]}" for b in hard_errors]
                + (["critical_down"] if critical_down else [])
                + (["disk_full"] if disk_full else [])
            ))
            if force_alert or sig != st.get("last_watchdog_alert_sig"):
                st.set("last_watchdog_alert_sig", sig)
                send_alert("Watchdog", f"{bots_status}{extra}")
            else:
                log.info("Watchdog: issue unchanged since last alert — not re-paging")
        else:
            log.warning(f"Watchdog soft warning (not paged): {bots_status}{extra}")
    else:
        st.set("last_watchdog_alert_sig", "")
        log.info("Watchdog: all systems healthy")

    return snapshot

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "full"
    if mode == "light":
        run_lightweight()
    else:
        run_full(force_alert="--alert" in sys.argv)
