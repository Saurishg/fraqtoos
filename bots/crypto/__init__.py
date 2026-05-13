"""Crypto bot wrapper — delegates to /home/work/crypto-trading-bot/btc_strategy.py"""
import sys
sys.path.insert(0, "/home/work/fraqtoos")
from core.runner import run_bot

def run() -> dict:
    return run_bot(
        name="BTC Strategy Bot",
        cmd="python3 btc_strategy.py",
        cwd="/home/work/crypto-trading-bot",
        timeout=300, retries=0,
    )
