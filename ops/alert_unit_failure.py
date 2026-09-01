#!/usr/bin/env python3
"""
OnFailure handler for generated fraqtoos timer units.

systemd calls this as fraqtoos-alert@<escaped-unit>.service whenever a job
unit fails. It reports over the Phase 1 notifier, so it inherits the WhatsApp
-> ntfy fallback: a job failing because wa-service is down still reaches you.

It distinguishes the two ways a job can not-succeed, because they need
different reactions:

  exit 4   the report was sent but a source was missing - act on the data
  other    the job did not complete - act on the job

Usage: alert_unit_failure.py <unit-name>
"""
import subprocess, sys

sys.path.insert(0, "/home/work/fraqtoos")
from core.notifier import send_alert


def show(unit: str, prop: str) -> str:
    r = subprocess.run(["systemctl", "show", "-p", prop, "--value", unit],
                       capture_output=True, text=True, timeout=10)
    return r.stdout.strip()


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: alert_unit_failure.py <unit>", file=sys.stderr)
        return 2
    # %n substitutes the failed unit's name literally, so it needs no
    # unescaping. Running it through `systemd-escape -u` turned
    # fraqtoos-ipo.service into fraqtoos/ipo.service - dashes are the path
    # separator in an INSTANCE name, which this is not. It appeared to work
    # only because systemctl silently re-escaped the mangled name back.
    unit = sys.argv[1]

    status = show(unit, "ExecMainStatus") or "?"
    result = show(unit, "Result") or "?"
    desc   = show(unit, "Description") or unit

    try:
        log = subprocess.run(["journalctl", "-u", unit, "-n", "12", "--no-pager",
                              "-o", "cat"], capture_output=True, text=True, timeout=15).stdout
    except Exception:
        log = ""
    tail = "\n".join(l for l in log.splitlines() if l.strip())[-500:]

    if status == "4":
        title = f"{desc} — incomplete"
        # Careful with the wording: exit 4 covers both "sent an incomplete
        # report" and "sent nothing because a source was missing". Claiming a
        # report was sent when none was is worse than saying less.
        head  = "A data source was missing — this run is incomplete."
    else:
        title = f"{desc} — failed"
        head  = f"Job did not complete (result={result}, exit={status})."

    send_alert(title, f"{head}\n\n{tail}" if tail else head)
    print(f"[alert_unit_failure] paged for {unit}: result={result} exit={status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
