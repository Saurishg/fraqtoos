#!/bin/bash
# Staggered SMART extended (long) self-test campaign across the whole fleet.
#
# Why: as of 2026-08-18 essentially NO drive in this box had ever been
# self-tested. A long test reads the entire surface and finds bad sectors
# before farming reads do. An extended test on a 14TB drive takes ~24h, so
# 57 drives cannot run at once - this walks the fleet a few drives at a time.
#
# Drives are tracked by SERIAL, never by /dev letter: letters reshuffle on
# every boot on this machine.
#
# Stop the campaign at any time:  systemctl disable --now drive-selftest.timer
# Abort a running test on a drive: smartctl -X /dev/sdX

set -uo pipefail

CONCURRENCY=${CONCURRENCY:-4}
STATE=/var/lib/drive-selftest
LOG=/home/work/logs/drive-selftest.log
WA_URL=http://localhost:3131/send
WA_PHONE="+919818187001"

# Drives to skip, by serial. sdaz is already in predictive failure - a 24h
# full-surface scan on a dying drive risks pushing it over, and we already
# know the answer there.
SKIP_SERIALS="ZL2KPE2F0000C149ANJ6"

mkdir -p "$STATE" "$(dirname "$LOG")"
log() { echo "[$(date '+%F %T')] $*" >> "$LOG"; }

# The campaign is a one-shot walk of the fleet, but the timer driving it is not:
# once the queue drained on 2026-09-01 this kept waking every 30 minutes and
# rebuilding the serial->device map, which issues an identify to all ~57 drives,
# including the one already in predictive failure. Nothing downstream could act
# on it, because "complete" is latched. Bail before that work and stop the timer.
if [ -f "$STATE/complete" ]; then
    systemctl disable --now drive-selftest.timer >/dev/null 2>&1 \
        && log "campaign already complete - timer disabled, nothing left to do"
    exit 0
fi

alert() {
    curl -s --max-time 20 -X POST "$WA_URL" -H 'Content-Type: application/json' \
         -d "$(python3 -c 'import json,sys; print(json.dumps({"phone":sys.argv[1],"message":sys.argv[2]}))' \
               "$WA_PHONE" "$1")" >/dev/null 2>&1
}

# serial -> current /dev node
declare -A DEV_OF
for d in /dev/sd[a-z] /dev/sd[a-z][a-z]; do
    [ -b "$d" ] || continue
    s=$(smartctl -i "$d" 2>/dev/null | awk -F': +' '/Serial [Nn]umber/{print $2; exit}')
    [ -n "${s:-}" ] && DEV_OF["$s"]="$d"
done

# Build the queue once, then work through it across runs.
QUEUE="$STATE/queue"
if [ ! -f "$QUEUE" ]; then
    for s in "${!DEV_OF[@]}"; do
        case " $SKIP_SERIALS " in *" $s "*) continue ;; esac
        echo "$s"
    done | sort > "$QUEUE"
    log "campaign started: $(wc -l < "$QUEUE") drives queued, concurrency=$CONCURRENCY"
    alert "SMART self-test campaign started
$(wc -l < "$QUEUE") drives queued, $CONCURRENCY at a time.
An extended test takes ~24h per drive, so this runs for roughly 2 weeks.
You will only be messaged again if a drive FAILS its test, or at the end."
fi

running=0
# --- 1. harvest finished tests, count still-running ones --------------------
for s in $(cat "$STATE"/running 2>/dev/null); do
    dev=${DEV_OF[$s]:-}
    if [ -z "$dev" ]; then
        log "WARN serial $s no longer present - dropping from running"
        sed -i "/^$s$/d" "$STATE/running" 2>/dev/null
        continue
    fi
    out=$(smartctl -a "$dev" 2>/dev/null)
    if echo "$out" | grep -qiE "in progress|% of test remaining|Self test in progress"; then
        running=$((running+1))
        continue
    fi
    # finished - read the most recent result line
    # Squeeze runs of spaces AT CAPTURE. The PASS patterns below were written
    # against the display form (which was squeezed with tr -s at log time) but
    # were being matched against the raw line, where a SAS result reads
    #   "# 1 Background long Completed - 40152 - [-   -    -]"
    # with multiple spaces inside the brackets. So "- \[- - -\]" never matched,
    # "Completed$" never matched either (the line continues past that word), and
    # every healthy SAS drive fell through to the FAIL branch: 19 of the 23
    # reported failures in the 2026-08/09 campaign were passes, each of which
    # sent a WhatsApp alarm and buried the one drive that really did fail.
    res=$(smartctl -l selftest "$dev" 2>/dev/null | grep -iE "^#\s*1|^# 1" | head -1 | tr -s ' ')
    if echo "$res" | grep -qiE "without error|Completed$|- \[- - -\]"; then
        log "PASS $s ($dev): $(echo "$res" | tr -s ' ')"
    elif echo "$res" | grep -qiE "Interrupted|Aborted by host|in progress"; then
        # NOT a defect. "Interrupted (host reset)" means something reset the
        # link mid-test - common on the onboard SATA controller, which has a
        # known CRC/reset fault. Requeue rather than cry wolf: a false FAIL
        # here would send the user chasing a healthy disk.
        log "RETRY $s ($dev): test interrupted, requeued — $(echo "$res" | tr -s ' ')"
        sed -i "/^$s$/d" "$STATE/running" 2>/dev/null
        continue
    elif [ -z "$res" ]; then
        log "DONE $s ($dev): no result line yet (may still be settling)"
    else
        log "FAIL $s ($dev): $(echo "$res" | tr -s ' ')"
        model=$(echo "$out" | awk -F': +' '/Device Model|Product:/{print $2; exit}')
        alert "SMART SELF-TEST FAILED
$dev (SN $s)
$model
$(echo "$res" | tr -s ' ')
The surface scan found a defect. Check this drive."
    fi
    echo "$s" >> "$STATE/done"
    sed -i "/^$s$/d" "$STATE/running" 2>/dev/null
    sed -i "/^$s$/d" "$QUEUE" 2>/dev/null
done

# --- 2. top up to CONCURRENCY ------------------------------------------------
started=0
while [ "$running" -lt "$CONCURRENCY" ]; do
    next=$(comm -23 "$QUEUE" <(sort -u "$STATE/done" 2>/dev/null || true) 2>/dev/null \
           | comm -23 - <(sort -u "$STATE/running" 2>/dev/null || true) | head -1)
    [ -z "$next" ] && break
    dev=${DEV_OF[$next]:-}
    if [ -z "$dev" ]; then
        log "WARN queued serial $next not present, skipping"
        echo "$next" >> "$STATE/done"
        continue
    fi
    if smartctl -t long "$dev" >/dev/null 2>&1; then
        echo "$next" >> "$STATE/running"
        log "STARTED $next ($dev) extended self-test"
        running=$((running+1)); started=$((started+1))
    else
        log "ERROR could not start test on $next ($dev)"
        echo "$next" >> "$STATE/done"
    fi
done

remaining=$(comm -23 "$QUEUE" <(sort -u "$STATE/done" 2>/dev/null || true) | wc -l)
log "running=$running started=$started remaining=$remaining"

if [ "$remaining" -eq 0 ] && [ "$running" -eq 0 ] && [ ! -f "$STATE/complete" ]; then
    touch "$STATE/complete"
    pass=$(grep -c "^\[.*\] PASS" "$LOG" 2>/dev/null || echo 0)
    fail=$(grep -c "^\[.*\] FAIL" "$LOG" 2>/dev/null || echo 0)
    log "CAMPAIGN COMPLETE: $pass passed, $fail failed"
    # Stop the timer here rather than leave it spinning on a drained queue.
    systemctl disable --now drive-selftest.timer >/dev/null 2>&1
    alert "SMART self-test campaign COMPLETE
$pass drives passed, $fail failed.
Full log: $LOG"
fi
