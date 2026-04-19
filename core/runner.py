#!/usr/bin/env python3
"""
Core runner — executes any bot with retry, timeout, graphify update, git push.
"""
import subprocess, os, sys, time
from datetime import datetime
sys.path.insert(0, "/home/work/fraqtoos")
from core.logger import get_logger
from core import state as st

log = get_logger("runner")

def run_bot(name: str, cmd: str, cwd: str,
            timeout: int = 600, retries: int = 1) -> dict:
    result = {
        "name": name, "cwd": cwd, "cmd": cmd,
        "start": datetime.now().strftime("%H:%M:%S"),
        "success": False, "output": "", "duration": 0
    }
    start = time.time()

    for attempt in range(retries + 1):
        if attempt > 0:
            log.info(f"  ↺ Retry {attempt}/{retries}: {name}")
            time.sleep(15)
        try:
            proc = subprocess.run(
                cmd, shell=True, cwd=cwd,
                capture_output=True, text=True,
                timeout=timeout,
                env={**os.environ, "DISPLAY": ":0"}
            )
            result["output"]  = (proc.stdout + proc.stderr).strip()[-3000:]
            result["success"] = proc.returncode == 0
            if result["success"]:
                log.info(f"✓ {name} (exit 0, {round(time.time()-start)}s)")
                break
            else:
                log.warning(f"✗ {name} exit {proc.returncode} attempt {attempt+1}")
        except subprocess.TimeoutExpired:
            result["output"] = f"TIMEOUT after {timeout}s"
            log.error(f"✗ {name} TIMEOUT")
            break
        except Exception as e:
            result["output"] = str(e)
            log.error(f"✗ {name} ERROR: {e}")

    result["duration"] = round(time.time() - start)
    st.record_run(name, result["success"], result["output"], result["duration"])

    # Graphify update
    try:
        subprocess.run("python3.10 -m graphify update .", shell=True, cwd=cwd,
                       capture_output=True, timeout=60)
    except Exception:
        pass

    # Git push
    try:
        subprocess.run(
            'git add -A && git diff --cached --quiet || '
            'git commit -m "auto: bot run\n\nCo-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>" '
            '&& git push origin main',
            shell=True, cwd=cwd, capture_output=True, timeout=60
        )
    except Exception:
        pass

    return result
