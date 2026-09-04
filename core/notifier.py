#!/usr/bin/env python3
"""
FraqtoOS Core Notifier — single WhatsApp sender for all bots.
Uses fcntl lock to prevent concurrent WhatsApp session conflicts.
"""
import os, sys, subprocess, fcntl, time, json, ipaddress, urllib.request

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
# Published to more than one target, because the two have different jobs:
#
#   local LAN ntfy  a durable record that survives an internet outage, and the
#                   only one that still works if the uplink is what broke
#   ntfy.sh         what actually reaches the iPhone, anywhere
#
# iOS cannot take background push from a self-hosted server: notifications must
# arrive via APNs and only the official ntfy.sh app is registered with Apple.
# A tunnel would not have fixed it either - these are Cloudflare QUICK tunnels,
# so the hostname rotates on every cloudflared restart and any subscription
# pinned to it breaks within the week.
#
# Targets live in .ntfy-targets (0600, gitignored) rather than here: the ntfy.sh
# topic name is the only thing protecting these alerts, so it is a credential
# and is kept out of the repo and out of terminal output.
NTFY_TARGETS_FILE = "/home/work/fraqtoos/.ntfy-targets"
NTFY_FALLBACK_URL = "http://192.168.0.117:8091/fraqtoos-alerts"
NTFY_TIMEOUT = 8


def ntfy_targets() -> list:
    """Every URL to publish to. FRAQTOOS_NTFY_URL (comma-separated) overrides."""
    env = os.getenv("FRAQTOOS_NTFY_URL", "")
    if env.strip():
        return [u.strip() for u in env.split(",") if u.strip()]
    try:
        with open(NTFY_TARGETS_FILE) as f:
            urls = [l.strip() for l in f
                    if l.strip() and not l.lstrip().startswith("#")]
        if urls:
            return urls
    except Exception:
        pass
    return [NTFY_FALLBACK_URL]


_NTFY_PRIORITY = {"urgent": 5, "high": 4, "default": 3, "low": 2}


def _is_private(url: str) -> bool:
    """True for a target inside this network (LAN address or localhost)."""
    host = url.split("//")[-1].split("/")[0].rsplit(":", 1)[0].strip("[]")
    if host in ("localhost", "127.0.0.1", "::1"):
        return True
    try:
        return ipaddress.ip_address(host).is_private
    except ValueError:
        return False          # a hostname such as ntfy.sh is external


def _headline(body: str) -> str:
    """The first meaningful line, and nothing else.

    Enough to know what broke and that it needs attention; the detail is on
    the LAN copy and in the journal. Deliberately not a truncation of the body
    - a sliced log tail would leak exactly what this is meant to withhold.
    """
    for line in body.splitlines():
        if line.strip():
            return line.strip()[:180]
    return "(see the local copy for detail)"


def send_ntfy(title: str, body: str, priority: str = "high", tags: str = "warning") -> bool:
    """Publish to ntfy. Never raises - a fallback that can throw is not a fallback.

    Published as a JSON body rather than ntfy's Title/Priority headers: HTTP
    headers are latin-1, so an emoji in the title raises UnicodeEncodeError and
    the fallback dies exactly when it is needed. Every title here carries one.

    Delivered to every configured target. Returns True if ANY accepted it - the
    local record and the phone are independent, and losing one must not be
    reported as losing both.
    """
    ok = False
    for url in ntfy_targets():
        base, _, topic = url.rstrip("/").rpartition("/")
        # A target outside this network gets the headline only. The full body
        # routinely carries journal tails, unit names and internal hostnames,
        # and there is no reason to hand that to a third party to learn that
        # something broke. The LAN copy keeps everything.
        message = body if _is_private(url) else _headline(body)
        payload = json.dumps({
            "topic":    topic,
            "title":    title[:200],
            "message":  message[:3800],
            "priority": _NTFY_PRIORITY.get(priority, 4),
            "tags":     [t.strip() for t in tags.split(",") if t.strip()],
        }).encode("utf-8")
        try:
            req = urllib.request.Request(
                base or url, data=payload,
                headers={"Content-Type": "application/json"}, method="POST",
            )
            with urllib.request.urlopen(req, timeout=NTFY_TIMEOUT) as r:
                ok = ok or 200 <= r.status < 300
        except Exception as e:
            # Never print the URL: it carries the ntfy.sh topic, which is the
            # only secret protecting these alerts.
            host = base.split("//")[-1].split("/")[0] if base else "?"
            print(f"[notifier] ntfy publish to {host} failed: {e}", file=sys.stderr)
    return ok

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
