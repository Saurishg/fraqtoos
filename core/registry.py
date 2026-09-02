#!/usr/bin/env python3
"""
Fleet registry — one list of everything that is supposed to be running, and one
way to ask each entry whether it is.

Before this, the watchdog kept its own hand-written BOTS list and covered 6 of
38 entries; every new bot had to be remembered twice and the IPO bot was
invisible from the day it shipped. The registry is now the thing you add a job
to, and monitoring follows.

Nothing here requires a job to be instrumented. Each `kind` is probed from a
source that already exists:

    service      systemctl is-active
    timer        LastTriggerUSec + the triggered unit's Result
    pm2          pm2 jlist status and restart count
    orchestrator logs/state.json, written by core.runner.record_run
    cron         mtime of the log the entry already writes
  http         a URL that must answer (containers, health routes)

Run it directly for a snapshot:  python3 -m core.registry
"""
import json, os, subprocess, sys
from datetime import datetime

sys.path.insert(0, "/home/work/fraqtoos")

REGISTRY_FILE = "/home/work/fraqtoos/registry.json"
STATE_FILE    = "/home/work/fraqtoos/logs/state.json"

# pm2 restarts a crashing app forever, so "online" alone is not health - an app
# in a crash loop is online most of the time it is observed.
PM2_RESTART_WARN = 20


def load() -> list:
    with open(REGISTRY_FILE) as f:
        return json.load(f)["jobs"]


# ── helpers ───────────────────────────────────────────────────────────────────
def _sh(cmd: list, timeout: int = 10) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except Exception:
        return ""


def _age_h(when: datetime) -> float:
    return (datetime.now() - when).total_seconds() / 3600.0


def _systemd_ts(value: str):
    """Parse 'Tue 2026-09-01 01:24:26 IST' as local time. None if never/unset."""
    if not value or value in ("n/a", "0"):
        return None
    parts = value.split()
    if len(parts) < 3:
        return None
    try:
        return datetime.strptime(f"{parts[1]} {parts[2]}", "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


_pm2_cache = None


def _pm2() -> dict:
    global _pm2_cache
    if _pm2_cache is None:
        try:
            _pm2_cache = {a["name"]: a for a in json.loads(_sh(["pm2", "jlist"], 20))}
        except Exception:
            _pm2_cache = {}
    return _pm2_cache


def _state_runs() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f).get("runs", {})
    except Exception:
        return {}


# ── probes ────────────────────────────────────────────────────────────────────
def _probe_service(job) -> tuple:
    state = _sh(["systemctl", "is-active", job["unit"]])
    return (state == "active", state or "unknown")


def _probe_timer(job) -> tuple:
    unit = job["unit"]
    if _sh(["systemctl", "is-active", unit]) != "active":
        return (False, "timer not active")
    last = _systemd_ts(_sh(["systemctl", "show", "-p", "LastTriggerUSec", "--value", unit]))
    if last is None:
        return (True, "not yet triggered")
    age = _age_h(last)
    svc = unit.rsplit(".", 1)[0] + ".service"
    result = _sh(["systemctl", "show", "-p", "Result", "--value", svc]) or "success"
    if result != "success":
        return (False, f"last run {result}, {age:.1f}h ago")
    if age > job.get("max_age_h", 24):
        return (False, f"stale — last ran {age:.1f}h ago (max {job['max_age_h']}h)")
    return (True, f"ran {age:.1f}h ago")


def _probe_pm2(job) -> tuple:
    app = _pm2().get(job["app"])
    if not app:
        return (False, "not in pm2 list")
    env = app.get("pm2_env", {})
    status   = env.get("status", "?")
    restarts = env.get("restart_time", 0)
    if status != "online":
        return (False, f"status {status}")
    if restarts >= PM2_RESTART_WARN:
        return (False, f"online but {restarts} restarts — crash loop?")
    return (True, f"online, {restarts} restarts")


def _probe_orchestrator(job) -> tuple:
    run = _state_runs().get(job.get("state_key", job["name"]))
    if not run:
        return (False, "no run ever recorded")
    try:
        last = datetime.strptime(str(run["last_run"]), "%Y-%m-%d %H:%M:%S")
    except Exception:
        return (False, "unparseable last_run")
    age = _age_h(last)
    if age > job.get("max_age_h", 30):
        return (False, f"stale — last ran {age:.1f}h ago (max {job['max_age_h']}h)")
    if not run.get("success"):
        return (False, f"last run failed or degraded, {age:.1f}h ago")
    return (True, f"ok {age:.1f}h ago")


def _probe_cron(job) -> tuple:
    path = job["log"]
    if not os.path.exists(path):
        return (False, "log missing — has it ever run?")
    age = _age_h(datetime.fromtimestamp(os.path.getmtime(path)))
    if age > job.get("max_age_h", 24):
        return (False, f"stale — log untouched {age:.1f}h (max {job['max_age_h']}h)")
    return (True, f"wrote {age:.1f}h ago")


def _probe_http(job) -> tuple:
    """A URL that must answer. For things systemd cannot see - a container's
    port, an app's health route - where 'the process exists' is not the
    question worth asking."""
    import urllib.request
    try:
        with urllib.request.urlopen(job["url"], timeout=job.get("timeout_s", 8)) as r:
            ok = 200 <= r.status < 400
            return (ok, f"http {r.status}")
    except Exception as e:
        return (False, f"unreachable: {type(e).__name__}")


_PROBES = {
    "service":      _probe_service,
    "timer":        _probe_timer,
    "pm2":          _probe_pm2,
    "orchestrator": _probe_orchestrator,
    "cron":         _probe_cron,
    "http":         _probe_http,
}


def check(job: dict) -> dict:
    probe = _PROBES.get(job["kind"])
    if probe is None:
        return {**job, "ok": True, "detail": f"unknown kind {job['kind']} — not probed"}
    try:
        ok, detail = probe(job)
    except Exception as e:
        # A probe that throws must not take the watchdog with it.
        ok, detail = False, f"probe error: {type(e).__name__}: {e}"
    return {"name": job["name"], "kind": job["kind"],
            "critical": bool(job.get("critical")), "ok": ok, "detail": detail}


def check_all() -> list:
    global _pm2_cache
    _pm2_cache = None          # one pm2 call per sweep, always fresh
    return [check(j) for j in load()]


if __name__ == "__main__":
    results = check_all()
    bad = [r for r in results if not r["ok"]]
    width = max(len(r["name"]) for r in results)
    for r in results:
        mark = "OK  " if r["ok"] else ("DOWN" if r["critical"] else "WARN")
        print(f"  [{mark}] {r['name']:<{width}}  {r['kind']:<12} {r['detail']}")
    print(f"\n  {len(results) - len(bad)}/{len(results)} healthy"
          + (f" · {len(bad)} needing attention" if bad else ""))
    sys.exit(1 if any(r["critical"] for r in bad) else 0)
