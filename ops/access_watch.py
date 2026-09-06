#!/usr/bin/env python3
"""Verify the published URLs still work with the published credentials.

Written 2026-09-06 after a run of access breakages that were each invisible
until someone tried to log in:

  - chat was handed the wrong credential entirely (it used a token gate, not
    the shared basic auth), and the failure looked like a broken service
  - the fix for that hardcodes the app's token into nginx. The app REGENERATES
    that token if .env ever loses it, so the two can silently drift and chat
    then 401s with a perfectly correct password
  - the wildcard certificate covers all five hosts; if renewal ever fails,
    every one of them breaks at once

None of that shows up in a systemd unit state, so nothing was watching it.
This checks the things a person would actually notice, and only those.

Exit codes follow the fleet contract: 0 complete, 4 degraded, 1 failed.
"""
import re
import sys
import datetime
import urllib.request
import urllib.error
import base64
import ssl
import socket

sys.path.insert(0, "/home/work/fraqtoos")
from core.notifier import send_alert  # noqa: E402

WEBAUTH = "/home/work/fraqtoos/ops/duckdns/webauth.txt"
BMCAUTH = "/home/work/fraqtoos/ops/duckdns/bmcauth.txt"
CHAT_ENV = "/home/work/fraqtoos-chat/.env"
NGINX_CONF = "/etc/nginx/sites-available/fraqtos.conf"

CERT_WARN_DAYS = 21  # renewal runs twice daily from 30 days out; 21 means it has failed


def creds(path):
    txt = open(path).read()
    u = re.search(r"^user:\s*(.+)$", txt, re.M)
    p = re.search(r"^pass:\s*(.+)$", txt, re.M)
    return (u.group(1).strip(), p.group(1).strip()) if u and p else (None, None)


def fetch(url, user=None, pw=None, timeout=25):
    """Return the HTTP status, following the redirects a browser would."""
    req = urllib.request.Request(url)
    if user:
        tok = base64.b64encode(f"{user}:{pw}".encode()).decode()
        req.add_header("Authorization", f"Basic {tok}")
    try:
        with urllib.request.urlopen(req, timeout=timeout,
                                    context=ssl.create_default_context()) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception as e:
        return f"unreachable ({type(e).__name__})"


def main():
    problems = []

    wu, wp = creds(WEBAUTH)
    bu, bp = creds(BMCAUTH)
    if not wu or not bu:
        print("could not read the credential files", file=sys.stderr)
        return 1

    # 1. Every published URL answers with its published credential.
    #    Grafana 302s to its own login, which is a pass - it means basic auth
    #    was satisfied and the app took over.
    checks = [
        ("grafana",  "https://grafana.fraqtos.duckdns.org/",  wu, wp, (200, 302)),
        ("dash",     "https://dash.fraqtos.duckdns.org/",     wu, wp, (200, 302)),
        ("obsidian", "https://obsidian.fraqtos.duckdns.org/", wu, wp, (200, 302)),
        ("chat",     "https://chat.fraqtos.duckdns.org/",     wu, wp, (200,)),
        ("bmc",      "https://bmc.fraqtos.duckdns.org/index.html", bu, bp, (200, 302)),
        ("ntfy",     "https://ntfy.fraqtos.duckdns.org/",     None, None, (200,)),
    ]
    for name, url, u, p, ok in checks:
        st = fetch(url, u, p)
        if st not in ok:
            problems.append(f"{name}: got {st}, expected {'/'.join(map(str, ok))}")
        print(f"{name:<10} {st}")

    # 2. The credentials must stay SEPARATE. If the shared login ever opens the
    #    BMC, the isolation that makes a shared-password leak survivable is gone.
    st = fetch("https://bmc.fraqtos.duckdns.org/index.html", wu, wp)
    print(f"bmc-isolation {st} (401 wanted)")
    if st != 401:
        problems.append(f"BMC accepts the SHARED site password (got {st}) - isolation lost")

    # 3. nginx's hardcoded chat token still matches what the app actually uses.
    try:
        env_tok = re.search(r"^FRAQTOOS_TOKEN=(.+)$",
                            open(CHAT_ENV).read(), re.M).group(1).strip()
        # The vhost file is world-readable, so no sudo: a check that needs
        # privileges it does not have fails as a false alarm, which is worse
        # than not checking at all.
        m = re.search(r"X-Auth-Token\s+(\S+);", open(NGINX_CONF).read())
        conf_tok = m.group(1) if m else ""
        if not conf_tok:
            problems.append("could not read X-Auth-Token from the nginx config")
        elif conf_tok != env_tok:
            problems.append(
                "chat token DRIFTED: nginx is sending a token the app no longer "
                "accepts, so chat 401s even with the right password")
        print(f"chat-token {'match' if conf_tok == env_tok else 'DRIFT'}")
    except Exception as e:
        problems.append(f"chat token check failed: {e}")

    # 4. The wildcard certificate covers all six hosts at once.
    # Read it off the live TLS connection rather than the file on disk: the
    # file needs root, and more importantly the served certificate is what
    # actually matters - nginx keeps serving the OLD one until it is reloaded,
    # so a renewal that did not reload looks fine on disk and broken in a
    # browser.
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection(("chat.fraqtos.duckdns.org", 443), timeout=20) as s:
            with ctx.wrap_socket(s, server_hostname="chat.fraqtos.duckdns.org") as ss:
                exp = datetime.datetime.strptime(
                    ss.getpeercert()["notAfter"], "%b %d %H:%M:%S %Y %Z"
                ).replace(tzinfo=datetime.timezone.utc)
        days = (exp - datetime.datetime.now(datetime.timezone.utc)).days
        print(f"cert {days}d")
        if days < CERT_WARN_DAYS:
            problems.append(
                f"certificate expires in {days}d and renewal has not run - "
                f"ALL six hosts break when it lapses")
    except Exception as e:
        problems.append(f"certificate check failed: {e}")

    if problems:
        body = "\n".join(f"- {p}" for p in problems)
        print(body, file=sys.stderr)
        send_alert("Remote access degraded", body)
        return 4
    print("all access checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
