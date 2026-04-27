#!/usr/bin/env python3
"""
Shared WhatsApp sender — calls the local wa-service (whatsapp-web.js).
Usage: python3 send_whatsapp.py <phone> <message>
Exit 0 = success, Exit 1 = failure.
"""

import sys
import json
import urllib.request
import urllib.error

WA_SERVICE = "http://127.0.0.1:3131"
TIMEOUT    = 130  # seconds — allows for queue drain on startup


def send(phone: str, message: str) -> bool:
    phone = phone.strip().replace(" ", "")
    if not phone or phone.lower() in ("none", "null", ""):
        print("[send_whatsapp] ERROR: empty phone", file=sys.stderr)
        return False

    payload = json.dumps({"phone": phone, "message": message}).encode()
    req = urllib.request.Request(
        f"{WA_SERVICE}/send",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = json.loads(resp.read())
            if body.get("ok"):
                print(f"[send_whatsapp] Sent to {phone}")
                return True
            print(f"[send_whatsapp] ERROR: {body.get('error')}", file=sys.stderr)
            return False
    except urllib.error.URLError as e:
        print(f"[send_whatsapp] ERROR: wa-service unreachable — {e}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"[send_whatsapp] ERROR: {e}", file=sys.stderr)
        return False


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: send_whatsapp.py <phone> <message>", file=sys.stderr)
        sys.exit(1)

    sys.exit(0 if send(sys.argv[1], sys.argv[2]) else 1)
