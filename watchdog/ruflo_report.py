#!/usr/bin/env python3
"""
Push watchdog snapshot into ruflo memory after each full check.
Called by watchdog.py after run_full() completes.
"""
import json, subprocess, os, sys
from datetime import datetime

RUFLO_NODE = "/home/work/.local/share/fnm/node-versions/v20.20.2/installation/bin/node"
RUFLO_BIN  = "/home/work/.local/share/fnm/node-versions/v20.20.2/installation/bin/ruflo"
REPORT_FILE = "/home/work/fraqtoos/logs/watchdog_latest.json"


def push_to_ruflo(snapshot: dict, analysis: str):
    """Store watchdog snapshot in ruflo memory for agent context."""
    payload = {
        "timestamp": snapshot.get("timestamp"),
        "disk":      snapshot.get("system", {}).get("disk", "?"),
        "ram":       snapshot.get("system", {}).get("ram", "?"),
        "bots": [
            {
                "name":    b["name"],
                "ok":      b["running"] or b.get("scheduled", False),
                "errors":  b.get("errors", []),
            }
            for b in snapshot.get("bots", [])
        ],
        "analysis_summary": analysis[:300],
    }

    env = os.environ.copy()
    env["PATH"] = f"/home/work/.local/share/fnm:{env.get('PATH','')}"

    subprocess.run(
        [RUFLO_BIN, "memory", "store",
         "-k", "fraqtoos/watchdog/latest",
         "--value", json.dumps(payload)],
        cwd="/home/work/fraqtoos",
        env=env, capture_output=True, timeout=30
    )


def push_bot_health(bot_name: str, ok: bool, errors: list):
    """Store per-bot health entry for trend tracking."""
    key = f"fraqtoos/bots/{bot_name.lower().replace(' ','-')}/health"
    payload = {
        "ts":     datetime.now().strftime("%Y-%m-%d %H:%M"),
        "ok":     ok,
        "errors": errors[-2:],
    }
    env = os.environ.copy()
    env["PATH"] = f"/home/work/.local/share/fnm:{env.get('PATH','')}"
    subprocess.run(
        [RUFLO_BIN, "memory", "store",
         "-k", key, "--value", json.dumps(payload)],
        cwd="/home/work/fraqtoos",
        env=env, capture_output=True, timeout=30
    )


if __name__ == "__main__":
    # Standalone: push last watchdog report
    try:
        with open(REPORT_FILE) as f:
            data = json.load(f)
        push_to_ruflo(data["snapshot"], data.get("analysis", ""))
        print("Pushed to ruflo memory OK")
    except Exception as e:
        print(f"ruflo push failed: {e}", file=sys.stderr)
        sys.exit(1)
