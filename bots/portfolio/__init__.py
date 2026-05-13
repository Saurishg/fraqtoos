"""Portfolio bot wrapper — delegates to /home/work/portfolio_bot/portfolio_bot.py"""
import sys
sys.path.insert(0, "/home/work/fraqtoos")
from core.runner import run_bot

def run() -> dict:
    return run_bot(
        name="Portfolio Bot",
        cmd="python3 portfolio_bot.py",
        cwd="/home/work/portfolio_bot",
        timeout=300, retries=1,
    )
