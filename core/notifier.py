#!/usr/bin/env python3
"""
FraqtoOS Core Notifier — single WhatsApp sender for all bots.
Uses fcntl lock to prevent concurrent WhatsApp session conflicts.
"""
import os, sys, subprocess, fcntl, time, json, urllib.request

WA_SENDER  = "/home/work/fraqtoos/shared/send_whatsapp.py"
WA_NUMBER  = os.getenv("WHATSAPP_RECIPIENT", "919818187001")
LOCK_PATH  = "/tmp/fraqtoos_wa.lock"

# ── Second channel ────────────────────────────────────────────────────────────
# Every alert on this server used to leave through wa-service, which is also
# the component that fails most often - an init deadlock cost 5h51m of total
# alerting silence on 2026-08-16, and the alert saying so could not be sent.
# ntfy is a separate process with no shared failure mode: no browser, no
# WhatsApp session, no Chrome profile lock.
#
# NOTE: the default target is bound to 127.0.0.1, so it is a durable local
# record, not yet a push to your phone. Point FRAQTOOS_NTFY_URL at a reachable
# ntfy instance/topic to make it page.
NTFY_URL     = os.getenv("FRAQTOOS_NTFY_URL", "http://127.0.0.1:8091/fraqtoos-alerts")
NTFY_TIMEOUT = 8


_NTFY_PRIORITY = {"urgent": 5, "high": 4, "default": 3, "low": 2}


def send_ntfy(title: str, body: str, priority: str = "high", tags: str = "warning") -> bool:
    """Publish to ntfy. Never raises - a fallback that can throw is not a fallback.

    Published as a JSON body rather than ntfy's Title/Priority headers: HTTP
    headers are latin-1, so an emoji in the title raises UnicodeEncodeError and
    the fallback dies exactly when it is needed. Every title here carries one.
    """
    base, _, topic = NTFY_URL.rstrip("/").rpartition("/")
    payload = json.dumps({
        "topic":    topic,
        "title":    title[:200],
        "message":  body[:3800],
        "priority": _NTFY_PRIORITY.get(priority, 4),
        "tags":     [t.strip() for t in tags.split(",") if t.strip()],
    }).encode("utf-8")
    try:
        req = urllib.request.Request(
            base or NTFY_URL, data=payload,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=NTFY_TIMEOUT) as r:
            return 200 <= r.status < 300
    except Exception as e:
        print(f"[notifier] ntfy failed: {e}", file=sys.stderr)
        return False

def send(message: str, phone: str = WA_NUMBER, retries: int = 2, max_wait: int = 60) -> bool:
    """Send a WhatsApp message. Lock contention and send errors share the same attempt budget."""
    deadline = time.time() + max_wait
    attempt = 0
    while attempt <= retries:
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
            attempt += 1
            if attempt <= retries:
                time.sleep(10)
        except BlockingIOError:
            if lock_fd:
                lock_fd.close()
            attempt += 1
            wait = min(15, max(0, deadline - time.time()))
            if wait > 0:
                time.sleep(wait)
        except Exception as e:
            if lock_fd:
                try: fcntl.flock(lock_fd, fcntl.LOCK_UN); lock_fd.close()
                except Exception: pass
            attempt += 1
            if attempt <= retries:
                time.sleep(10)
            else:
                print(f"[notifier] FAILED after {attempt} attempts: {e}", file=sys.stderr)
    return False

def send_alert(title: str, body: str, phone: str = WA_NUMBER) -> bool:
    """Alert over WhatsApp, falling back to ntfy if WhatsApp will not carry it.

    Returns True if the alert left by ANY channel. A silent alert is the
    failure mode this exists to prevent, so the fallback is not conditional on
    why WhatsApp failed.
    """
    if send(f"⚠️ *{title}*\n{body}", phone):
        return True
    print(f"[notifier] WhatsApp failed for '{title}' — falling back to ntfy", file=sys.stderr)
    return send_ntfy(f"⚠️ {title}", body)


def send_critical(title: str, body: str, phone: str = WA_NUMBER) -> bool:
    """Both channels, always, in parallel paths.

    For failures that implicate the alerting path itself - wa-service down, the
    orchestrator dead. Do not wait to discover WhatsApp is unavailable when the
    thing being reported is that WhatsApp is unavailable.
    """
    ntfy_ok = send_ntfy(f"🔴 {title}", body, priority="urgent", tags="rotating_light")
    wa_ok   = send(f"🔴 *{title}*\n{body}", phone)
    return wa_ok or ntfy_ok


def send_success(title: str, body: str, phone: str = WA_NUMBER) -> bool:
    return send(f"✅ *{title}*\n{body}", phone)
