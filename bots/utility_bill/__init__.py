"""Utility bill bot wrapper — delegates to /home/work/utility-bill-bot/bot.js"""
import sys
sys.path.insert(0, "/home/work/fraqtoos")
from core.runner import run_bot

def run() -> dict:
    return run_bot(
        name="Utility Bill Bot",
        cmd="node bot.js --once",
        cwd="/home/work/utility-bill-bot",
        timeout=300, retries=1,
    )
