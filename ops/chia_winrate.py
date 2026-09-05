#!/usr/bin/env python3
"""
Is the Chia farm winning what its size says it should?

Written 2026-09-05 to settle a specific question. Before the connectivity fix
the farm won 32 blocks in 30 days against 52.5 expected - 61%, z = -2.83 - and
42% of the blocks it farmed were orphaned, traced to having zero inbound peers.
A port forward on 2026-09-04 took it from 8 one-way connections to 16 with 8
inbound. Whether that recovered the blocks can only be answered by counting
them over a fortnight, and nobody should have to remember to do that by hand.

Counting method matters: reward transactions undercount, because the 0.875 pool
portion and the 0.125 farmer portion arrive separately and on different
schedules. `chia_total_farmed_xch` only ever moves by the farmer reward, so
delta / 0.125 is the block count.

Expected wins are integrated over the window from the farm's own effective size
and the network space at each sample, rather than assumed from today's snapshot
- netspace moved 3.09 -> 3.80 EiB during the last measurement alone.
"""
import json
import subprocess
import sys
import time
from datetime import datetime

PROM = "http://127.0.0.1:9090/api/v1/query_range"
FIX_EPOCH = 1788521520          # 2026-09-04 17:12 IST, when inbound started
FARMER_REWARD = 0.125
BLOCKS_PER_HOUR = 192
# The pre-fix baseline, computed by THIS script's own method over the 30 days
# ending at FIX_EPOCH: 34 blocks against 49.3 expected. An earlier hand
# measurement said 61%, using a flat 1.75 blocks/day rather than integrating
# netspace across the window - comparing a future integrated figure against
# that would flatter the result. Same method both sides, or the comparison
# means nothing.
BASELINE_PCT = 69


def q(expr, start, end, step=3600):
    r = subprocess.run(
        ["curl", "-s", "--max-time", "30",
         "--data-urlencode", f"query={expr}",
         "--data-urlencode", f"start={start}",
         "--data-urlencode", f"end={end}",
         "--data-urlencode", f"step={step}", PROM],
        capture_output=True, text=True, timeout=60)
    res = json.loads(r.stdout).get("data", {}).get("result", [])
    return [(int(float(t)), float(v)) for t, v in res[0]["values"]] if res else []


def main() -> int:
    end = int(time.time())
    start = FIX_EPOCH
    days = (end - start) / 86400
    if days < 1:
        print("less than a day of data since the fix — nothing to say yet")
        return 0

    farmed = q("chia_total_farmed_xch", start, end)
    if len(farmed) < 2:
        print("no chia_total_farmed_xch history — is the exporter running?")
        return 1

    blocks = (farmed[-1][1] - farmed[0][1]) / FARMER_REWARD

    # Expected: integrate share-of-netspace over the window.
    eff = dict(q("chia_plots_effective_pibe", start, end))
    net = dict(q("chia_network_space_eib", start, end))
    common = sorted(set(eff) & set(net))
    if not common:
        print("no farm-size/netspace history to compare against")
        return 1
    expected = sum(BLOCKS_PER_HOUR * (eff[t] / (net[t] * 1024)) for t in common)

    pct = blocks / expected * 100 if expected else 0
    lines = [
        f"⛏️ *CHIA WIN RATE* — {days:.1f} days since the peer fix",
        "",
        f"blocks won   : {blocks:.0f}",
        f"expected     : {expected:.1f}",
        f"ratio        : {pct:.0f}%   (was {BASELINE_PCT}% before)",
    ]

    # Say plainly how much weight the number carries. At ~1.75 expected blocks a
    # day, a week is still mostly noise; the honest read needs a fortnight.
    if days < 7:
        lines.append("\n_Too early to mean anything — noise dominates below a week._")
    elif days < 14:
        lines.append("\n_Suggestive, not conclusive. Wait for 14 days._")
    elif pct >= 90:
        lines.append("\n✅ *Recovered.* The connectivity fix worked.")
    elif pct >= BASELINE_PCT + 10:
        lines.append("\n🟡 *Improved but short.* Some orphaning may remain.")
    else:
        lines.append("\n🔴 *No better than before.* Peers were not the cause — reopen it.")

    msg = "\n".join(lines)
    print(msg)

    if "--stdout" in sys.argv or "--no-send" in sys.argv:
        return 0

    sys.path.insert(0, "/home/work/fraqtoos")
    from core.notifier import send_alert
    send_alert("Chia win rate", msg)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"fatal: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
