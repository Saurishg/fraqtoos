#!/usr/bin/env python3
"""
FraqtoOS Core Notifier — single WhatsApp sender for all bots.
Uses fcntl lock to prevent concurrent WhatsApp session conflicts.
"""
import os, sys, subprocess, fcntl, time

WA_SENDER  = "/home/work/fraqtoos/shared/send_whatsapp.py"
WA_NUMBER  = os.getenv("WHATSAPP_RECIPIENT", "919818187001")
LOCK_PATH  = "/tmp/fraqtoos_wa.lock"

def send(message: str, phone: str = WA_NUMBER, retries: int = 2, max_wait: int = 60) -> bool:
    deadline = time.time() + max_wait
    for attempt in range(retries + 1):
        if time.time() > deadline:
            print(f"[notifier] TIMEOUT after {max_wait}s", file=sys.stderr)
            return False
        lock_fd = None
        try:
            lock_fd = open(LOCK_PATH, "w")
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            r = subprocess.run(
                ["python3", WA_SENDER, phone, message],
                env={**os.environ, "DISPLAY": ":0"},
                timeout=120, capture_output=True, text=True
            )
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()
            if r.returncode == 0:
                return True
        except BlockingIOError:
            if lock_fd: lock_fd.close()
            time.sleep(min(15, max(0, deadline - time.time())))
            continue
        except Exception as e:
            if lock_fd:
                try: fcntl.flock(lock_fd, fcntl.LOCK_UN); lock_fd.close()
                except Exception: pass
            if attempt < retries:
                time.sleep(10)
            else:
                print(f"[notifier] FAILED after {retries+1} attempts: {e}", file=sys.stderr)
    return False

def send_alert(title: str, body: str, phone: str = WA_NUMBER) -> bool:
    return send(f"⚠️ *{title}*\n{body}", phone)

def send_success(title: str, body: str, phone: str = WA_NUMBER) -> bool:
    return send(f"✅ *{title}*\n{body}", phone)
