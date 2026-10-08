#!/usr/bin/env bash
# Tell Jellyfin to rescan when files land in the NAS media folders.
#
# /mnt/multimedia is a CIFS mount and inotify never fires over CIFS, so
# Jellyfin's real-time monitor misses anything copied in from another machine
# until its next scheduled scan - a new movie can sit invisible for hours.
#
# Runs every 10 min. A scan is triggered only when:
#   - the listing changed since the last scan, AND
#   - it was unchanged since the previous run (a copy still in progress keeps
#     changing size, and scanning a half-written file gives a bad probe), AND
#   - nothing is playing right now (a scan would not interrupt playback, but
#     there is no reason to add NAS load mid-movie; it just waits a cycle).
#
# Refuses to scan when the share is not mounted: Jellyfin would see an empty
# folder and could drop the whole library.
set -uo pipefail

DIR="/home/work/fraqtoos/ops/jellyfin"
STATE="$DIR/state"
API="http://127.0.0.1:8096"
MOUNT="/mnt/multimedia"
FOLDERS=("$MOUNT/Movies" "$MOUNT/TV Shows")

mkdir -p "$STATE"
KEY=$(cat "$DIR/apikey")
auth=(-H "Authorization: MediaBrowser Token=\"$KEY\"")

if ! mountpoint -q "$MOUNT"; then
  echo "$MOUNT not mounted — skipping (would look like an empty library)"
  exit 0
fi

listing=$(find "${FOLDERS[@]}" -type f \
  \( -iname '*.mkv' -o -iname '*.mp4' -o -iname '*.avi' -o -iname '*.mov' \
     -o -iname '*.m4v' -o -iname '*.ts' -o -iname '*.webm' -o -iname '*.srt' \) \
  -printf '%p|%s|%T@\n' 2>/dev/null | sort)
if [ -z "$listing" ]; then
  echo "no media files found — skipping (share empty or unreadable)"
  exit 0
fi
cur=$(printf '%s' "$listing" | md5sum | cut -d' ' -f1)

seen=$(cat "$STATE/seen" 2>/dev/null || true)
scanned=$(cat "$STATE/scanned" 2>/dev/null || true)
echo "$cur" > "$STATE/seen"

if [ "$cur" = "$scanned" ]; then
  exit 0                                  # nothing new
fi
if [ "$cur" != "$seen" ]; then
  echo "media folders changed — waiting one cycle for copies to finish"
  exit 0
fi

playing=$(curl -s --max-time 10 "${auth[@]}" "$API/Sessions?activeWithinSeconds=300" |
  python3 -c 'import json,sys; print(sum(1 for s in json.load(sys.stdin) if s.get("NowPlayingItem")))' 2>/dev/null)
if [ -z "$playing" ]; then
  echo "Jellyfin API not answering"
  exit 1
fi
if [ "$playing" -gt 0 ]; then
  echo "$playing stream(s) playing — deferring the scan"
  exit 0
fi

code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 -X POST "${auth[@]}" "$API/Library/Refresh")
if [ "$code" != "204" ]; then
  echo "library refresh FAILED: HTTP $code"
  exit 1
fi
echo "$cur" > "$STATE/scanned"
echo "new media detected — library scan started"
