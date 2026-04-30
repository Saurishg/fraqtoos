#!/usr/bin/env python3
"""
Grafana → WhatsApp bridge
Receives Grafana alertmanager webhook → formats → sends via wa-service (port 3131)
"""
import json
import os
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime

WA_SERVICE = "http://127.0.0.1:3131"
WA_NUMBER  = os.getenv("WHATSAPP_RECIPIENT", "919818187001")
PORT       = 9094


def send_whatsapp(phone: str, message: str) -> bool:
    payload = json.dumps({"phone": phone, "message": message}).encode()
    req = urllib.request.Request(
        f"{WA_SERVICE}/send",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read())
            return body.get("ok", False)
    except Exception as e:
        print(f"[grafana-wa] send error: {e}", flush=True)
        return False


def format_message(data: dict) -> str:
    status = data.get("status", "unknown").upper()
    alerts = data.get("alerts", [])

    icon = "🔴" if status == "FIRING" else "🟢"
    lines = [f"{icon} *Grafana — {status}*"]

    for alert in alerts:
        name     = alert.get("labels", {}).get("alertname", "Unknown Alert")
        severity = alert.get("labels", {}).get("severity", "")
        summary  = alert.get("annotations", {}).get("summary", "")
        desc     = alert.get("annotations", {}).get("description", "")
        value    = alert.get("valueString", "")

        header = f"\n*{name}*"
        if severity:
            header += f" [{severity}]"
        lines.append(header)

        if summary:
            lines.append(summary)
        if desc and desc != summary:
            lines.append(desc)
        if value:
            lines.append(f"Value: {value[:120]}")

    lines.append(f"\n_{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_")
    return "\n".join(lines)


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(length)
        try:
            data    = json.loads(body)
            message = format_message(data)
            ok      = send_whatsapp(WA_NUMBER, message)
            code    = 200 if ok else 500
            print(f"[grafana-wa] {data.get('status','?')} → WA {'ok' if ok else 'FAIL'}", flush=True)
        except Exception as e:
            print(f"[grafana-wa] parse error: {e}", flush=True)
            code = 400

        self.send_response(code)
        self.end_headers()

    def log_message(self, fmt, *args):
        pass  # suppress per-request access log


if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    print(f"[grafana-wa] Listening on http://127.0.0.1:{PORT}", flush=True)
    server.serve_forever()
