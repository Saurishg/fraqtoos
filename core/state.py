#!/usr/bin/env python3
"""
Shared state store — persists bot run history, counts, flags to JSON.
All bots read/write through here so orchestrator has full picture.
"""
import json, os
from datetime import datetime
from threading import Lock

STATE_FILE = "/home/work/fraqtoos/logs/state.json"
_lock = Lock()

def _load() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def _save(state: dict):
    # Atomic write: write to temp then rename. If orchestrator is SIGTERMed
    # mid-write, the original state.json stays intact. Without this, a partial
    # write produces invalid JSON, _load() returns {}, and the next _save()
    # silently wipes all run history.
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2, default=str)
    os.replace(tmp, STATE_FILE)

def get(key: str, default=None):
    with _lock:
        return _load().get(key, default)

def set(key: str, value):
    with _lock:
        state = _load()
        state[key] = value
        _save(state)

def record_run(bot_name: str, success: bool, output: str = "", duration: int = 0):
    with _lock:
        state = _load()
        if "runs" not in state:
            state["runs"] = {}
        now = datetime.now()
        prev = state["runs"].get(bot_name, {})
        # runs_today resets when the calendar day changes
        same_day = str(prev.get("last_run", "")).startswith(now.strftime("%Y-%m-%d"))
        state["runs"][bot_name] = {
            "last_run":    now.strftime("%Y-%m-%d %H:%M:%S"),
            "success":     success,
            "duration":    duration,
            "last_output": output[-300:] if output else "",
            "runs_today":  (prev.get("runs_today", 0) if same_day else 0) + 1,
        }
        _save(state)

def get_all_runs() -> dict:
    return _load().get("runs", {})
