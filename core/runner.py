#!/usr/bin/env python3
"""
Core runner — executes any bot with retry and timeout.
Graphify runs in the background (non-blocking).
"""
import subprocess, os, sys, time, threading
from datetime import datetime
sys.path.insert(0, "/home/work/fraqtoos")
from core.logger import get_logger
from core import state as st

log = get_logger("runner")

EXIT_DEGRADED = 4

def _bg(cmd: str, cwd: str):
    """Fire-and-forget background subprocess; daemon thread reaps the child."""
    def _reap():
        try:
            proc = subprocess.Popen(cmd, shell=True, cwd=cwd,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            proc.wait(timeout=120)
        except Exception:
            pass
    threading.Thread(target=_reap, daemon=True).start()

def run_bot(name: str, cmd: str, cwd: str,
            timeout: int = 600, retries: int = 1) -> dict:
    # rc is carried so callers can tell the difference between a bot that
    # failed and a bot that delivered a report it knows is incomplete.
    # Contract: 0 complete · 4 degraded (sent, a source is missing) · other failed.
    result = {
        "name": name, "cwd": cwd, "cmd": cmd,
        "start": datetime.now().strftime("%H:%M:%S"),
        "success": False, "degraded": False, "rc": None, "output": "", "duration": 0
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
            result["output"]   = (proc.stdout + proc.stderr).strip()[-3000:]
            result["rc"]       = proc.returncode
            result["degraded"] = proc.returncode == EXIT_DEGRADED
            result["success"]  = proc.returncode == 0
            if result["degraded"]:
                # Not a retry case: the bot ran, sent, and told us what was
                # missing. Retrying re-sends the same incomplete report.
                log.warning(f"⚠ {name} DEGRADED ({round(time.time()-start)}s)")
                break
            if result["success"]:
                log.info(f"✓ {name} ({round(time.time()-start)}s)")
                break
            else:
                log.warning(f"✗ {name} exit {proc.returncode} attempt {attempt+1}")
        except subprocess.TimeoutExpired:
            result["output"] = f"TIMEOUT after {timeout}s"
            log.error(f"✗ {name} TIMEOUT after {timeout}s")
            break
        except Exception as e:
            result["output"] = str(e)
            log.error(f"✗ {name} ERROR: {e}")

    result["duration"] = round(time.time() - start)
    st.record_run(name, result["success"], result["output"], result["duration"])

    # Write AI summary to shared context for the 23:00 digest (non-blocking).
    #
    # Deliberately NOT logged. This summary is model prose and is not reliable
    # as a status signal - observed claiming a bot "sent via WhatsApp and
    # email" when no email path exists, and that another "failed to value ETH"
    # in a run where ETH was valued correctly. While it was logged, the
    # watchdog had to filter "context:" lines back out before diagnosis to stop
    # the model re-diagnosing its own prose. The authoritative record of a run
    # is its exit code in state.json; this is colour for the digest, nothing
    # more.
    try:
        from core.ai_context import summarize_run, write_summary
        summary = summarize_run(name, result["output"], result["success"], result["duration"])
        write_summary(name, summary)
    except Exception:
        pass

    # Background: keep the code graph current (never block the orchestrator).
    #
    # There used to be a `git add -u && commit && push origin main || true`
    # here as well, firing in the bot's own working directory after EVERY run.
    # Removed 2026-09-01. It auto-published logs/fraqtoos.log to a public repo
    # on every run, it raced hand-written commits, and `|| true` made a
    # rejected push indistinguishable from a successful one - which is how the
    # links page served stale content for 21 hours. Bots do not author code;
    # commits are made deliberately.
    _bg("graphify update . 2>/dev/null", cwd)

    return result
