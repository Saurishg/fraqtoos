#!/usr/bin/env python3
"""
FraqtoOS Core Notifier — single WhatsApp sender owned by no individual bot.
All bots import from here. Never import from portfolio_bot directly.
"""
import os, sys, subprocess, fcntl, time

WA_SENDER  = "/home/work/portfolio_bot/send_whatsapp.py"
WA_NUMBER  = os.getenv("WHATSAPP_RECIPIENT", "919818187001")
LOCK_PATH  = "/tmp/fraqtoos_wa.lock"

def send(message: str, phone: str = WA_NUMBER, retries: int = 2) -> bool:
    for attempt in range(retries + 1):
        try:
            r = subprocess.run(
                ["python3", WA_SENDER, phone, message],
                env={**os.environ, "DISPLAY": ":0"},
                timeout=120, capture_output=True, text=True
            )
            if r.returncode == 0:
                return True
            if attempt < retries:
                time.sleep(10)
        except Exception as e:
            if attempt < retries:
                time.sleep(10)
            else:
                print(f"[notifier] FAILED after {retries+1} attempts: {e}", file=sys.stderr)
    return False

def send_alert(title: str, body: str, phone: str = WA_NUMBER) -> bool:
    return send(f"⚠️ *{title}*\n{body}", phone)

def send_success(title: str, body: str, phone: str = WA_NUMBER) -> bool:
    return send(f"✅ *{title}*\n{body}", phone)
