#!/usr/bin/env bash
# Fail on any scheduled command that invokes an interpreter by name rather than
# by absolute path.
#
# This is the root cause of the failure that started the fleet review. The
# system python moved 3.10 -> 3.12; wa-service's `stocks` command still said
# `python3 portfolio_bot.py`, so it died at `import pyotp` - and because the
# command ends in `2>/dev/null`, the traceback went nowhere and the reply was a
# blank message. Nothing in any log said why. fraqtoos.service had the same bug
# and was only working because of a drop-in.
#
# `python3` resolves differently for you, for cron, and for systemd. An absolute
# venv path resolves the same everywhere.
#
# Usage: ops/lint_interpreters.sh   (exit 1 = a bare interpreter was found)
set -uo pipefail

fail=0
BARE='(^|[^/[:alnum:]_.-])(python3?|node|npm|npx)([[:space:]]|$)'

report() { printf '  %-46s %s\n' "$1" "$2"; fail=1; }

echo "Scanning for bare interpreters in scheduled commands..."
echo

# 1. orchestrator bot definitions
while IFS= read -r line; do
  cmd=$(sed -E 's/.*"cmd":[[:space:]]*"([^"]*)".*/\1/' <<<"$line")
  [[ "$cmd" =~ $BARE ]] && report "orchestrator.py" "$cmd"
done < <(grep -E '"cmd":' /home/work/fraqtoos/orchestrator.py 2>/dev/null)

# 2. wa-service inbound commands
if [ -f /home/work/fraqtoos/shared/wa-service/commands.json ]; then
  while IFS= read -r cmd; do
    [[ "$cmd" =~ $BARE ]] && report "wa-service/commands.json" "$cmd"
  done < <(python3 -c '
import json,sys
d=json.load(open("/home/work/fraqtoos/shared/wa-service/commands.json"))
for k,v in d.get("commands",{}).items(): print(v.get("cmd",""))' 2>/dev/null)
fi

# 3. systemd units we own (ExecStart, drop-ins included)
while IFS= read -r unit; do
  exec_line=$(systemctl cat "$unit" 2>/dev/null | grep -E '^ExecStart=' | tail -1)
  [[ "$exec_line" =~ $BARE ]] && report "$unit" "${exec_line#ExecStart=}"
done < <(python3 -c '
import json
for j in json.load(open("/home/work/fraqtoos/registry.json"))["jobs"]:
    if j.get("unit"): print(j["unit"])' 2>/dev/null)

# 4. crontab
while IFS= read -r line; do
  [[ "$line" =~ ^[[:space:]]*# ]] && continue
  [[ -z "$line" ]] && continue
  [[ "$line" =~ $BARE ]] && report "crontab" "$line"
done < <(crontab -l 2>/dev/null)

echo
if [ "$fail" -eq 0 ]; then
  echo "PASS — every scheduled command names its interpreter by absolute path."
else
  echo "FAIL — the commands above will break the next time a system interpreter moves."
  echo "       Use an absolute path (e.g. /home/work/.venvs/<env>/bin/python)."
fi
exit "$fail"
