#!/usr/bin/env python3
"""
Shared WhatsApp file sender — calls the local wa-service (whatsapp-web.js).
Usage: python3 send_whatsapp_file.py <phone> <file_path> [caption]
Exit 0 = success, Exit 1 = failure.
"""

import sys
import json
import urllib.request
import urllib.error
import os

WA_SERVICE = "http://127.0.0.1:3131"
TIMEOUT    = 60


def send_file(phone: str, file_path: str, caption: str = "") -> bool:
    phone = phone.strip().replace(" ", "")
    if not phone or phone.lower() in ("none", "null", ""):
        print("[send_whatsapp_file] ERROR: empty phone", file=sys.stderr)
        return False

    if not os.path.isfile(file_path):
        print(f"[send_whatsapp_file] ERROR: file not found: {file_path}", file=sys.stderr)
        return False

    payload = json.dumps({"phone": phone, "file_path": file_path, "caption": caption}).encode()
    req = urllib.request.Request(
        f"{WA_SERVICE}/send-file",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = json.loads(resp.read())
            if body.get("ok"):
                print(f"[send_whatsapp_file] Sent {file_path} to {phone}")
                return True
            print(f"[send_whatsapp_file] ERROR: {body.get('error')}", file=sys.stderr)
            return False
    except urllib.error.URLError as e:
        print(f"[send_whatsapp_file] ERROR: wa-service unreachable — {e}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"[send_whatsapp_file] ERROR: {e}", file=sys.stderr)
        return False


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: send_whatsapp_file.py <phone> <file_path> [caption]", file=sys.stderr)
        sys.exit(1)

    caption = sys.argv[3] if len(sys.argv) > 3 else ""
    sys.exit(0 if send_file(sys.argv[1], sys.argv[2], caption) else 1)
