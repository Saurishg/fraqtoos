#!/usr/bin/env python3
"""
FraqtoOS AI Agent bot wrapper.
Runs gemma-agent/agent.py via run_bot() so it gets state tracking, timeout, retry.
"""
import sys
sys.path.insert(0, "/home/work/fraqtoos")
from core.runner import run_bot
from core.logger import get_logger

log = get_logger("ai_agent")

def run(task: str, model: str = "phi4") -> dict:
    log.info(f"AI Agent task: {task[:80]}")
    return run_bot(
        name    = "AI Agent",
        cmd     = f'python3 agent.py --model {model} "{task}"',
        cwd     = "/home/work/gemma-agent",
        timeout = 300,
        retries = 0,
    )

if __name__ == "__main__":
    task = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Check system health and summarize"
    r = run(task)
    print(r["output"][-500:])
