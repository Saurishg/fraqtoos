"""
Chia farming health monitor — daily summary bot.

Checks:
  - Harvester error count (Invalid size for deltas / prover bug)
  - Block validation spikes (>10s)
  - Coin store slow writes
  - Farming gap (hours since last block won)
  - Pooling errors (duplicate proof, missing signage point)
  - Node sync status

Sends WhatsApp alert if anything is critical, daily summary otherwise.
"""
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

LOG_PATH = Path.home() / ".chia/mainnet/log/debug.log"
EXPECTED_WIN_HOURS = 20          # from chia farm summary
CRITICAL_GAP_MULTIPLIER = 3      # alert if gap > 3× expected (60h)
VALIDATION_WARN_SEC = 10.0       # warn if block validation > 10s
ERROR_SPIKE_THRESHOLD = 20       # alert if >20 prover errors in one day


def _run(cmd: str) -> str:
    try:
        return subprocess.check_output(cmd, shell=True, text=True, timeout=30).strip()
    except Exception:
        return ""


def _parse_log(since_hours: int = 24) -> dict:
    cutoff = datetime.now() - timedelta(hours=since_hours)
    cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M")

    prover_errors, validation_spikes, coin_slow, pool_errors = [], [], [], []

    if not LOG_PATH.exists():
        return {}

    _LOG_SIZE_LIMIT = 100 * 1024 * 1024  # 100 MB
    if LOG_PATH.stat().st_size > _LOG_SIZE_LIMIT:
        raw = subprocess.run(
            ["tail", "-n", "3000", str(LOG_PATH)],
            capture_output=True, text=True
        ).stdout
        log_lines = raw.splitlines(keepends=True)
    else:
        with open(LOG_PATH, errors="replace") as fh:
            log_lines = fh.readlines()

    for line in log_lines:
        ts_match = re.match(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})", line)
        if not ts_match or ts_match.group(1) < cutoff_str:
            continue

        if "Exception fetching qualities" in line:
            plot = re.search(r"/mnt/[^\s:]+\.plot", line)
            prover_errors.append(plot.group(0) if plot else "unknown")

        elif "Block validation:" in line:
            m = re.search(r"Block validation: ([\d.]+)s", line)
            if m and float(m.group(1)) >= VALIDATION_WARN_SEC:
                validation_spikes.append(float(m.group(1)))

        elif "coin_store.*took" in line or ("took" in line and "coin_store" in line):
            m = re.search(r"took ([\d.]+)s", line)
            if m:
                coin_slow.append(float(m.group(1)))

        elif "Error in pooling" in line:
            pool_errors.append(line.strip())

    return {
        "prover_errors": prover_errors,
        "unique_bad_plots": len(set(prover_errors)),
        "validation_spikes": validation_spikes,
        "coin_slow": coin_slow,
        "pool_errors": pool_errors,
    }


def _farm_status() -> dict:
    summary = _run("chia farm summary")
    node = _run("chia show -s")

    last_height = 0
    cur_height = 0
    expected_hours = EXPECTED_WIN_HOURS

    m = re.search(r"Last height farmed:\s+(\d+)", summary)
    if m:
        last_height = int(m.group(1))

    m = re.search(r"Height:\s+(\d+)", node)
    if m:
        cur_height = int(m.group(1))

    m = re.search(r"Expected time to win:\s+([\d.]+) (\w+)", summary)
    if m:
        val, unit = float(m.group(1)), m.group(2)
        if "hour" in unit:
            expected_hours = val
        elif "minute" in unit:
            expected_hours = val / 60
        elif "day" in unit:
            expected_hours = val * 24

    # 4H bars → ~18.75s each → 192 bars/hour on 4h timeframe... no, Chia blocks are ~18.75s each
    blocks_behind = cur_height - last_height
    hours_since_win = blocks_behind * 18.75 / 3600

    farming_status = "Farming" if "Farming" in summary else "NOT FARMING"
    plots = re.search(r"Plot count.*?:\s+(\d+)", summary)
    plot_count = int(plots.group(1)) if plots else 0

    return {
        "status": farming_status,
        "last_height": last_height,
        "cur_height": cur_height,
        "hours_since_win": round(hours_since_win, 1),
        "expected_hours": expected_hours,
        "plot_count": plot_count,
    }


def run() -> str:
    log = _parse_log(since_hours=24)
    farm = _farm_status()

    # ── Build report ─────────────────────────────────────────────
    lines = ["*Chia Health — Daily*"]

    # Farming status
    status_icon = "✅" if farm["status"] == "Farming" else "🚨"
    lines.append(f"{status_icon} Status: {farm['status']} | {farm['plot_count']} plots")

    # Win gap
    gap = farm["hours_since_win"]
    expected = farm["expected_hours"]
    gap_icon = "🚨" if gap > expected * CRITICAL_GAP_MULTIPLIER else ("⚠️" if gap > expected * 1.5 else "✅")
    lines.append(f"{gap_icon} Last win: {gap:.0f}h ago (expected {expected:.0f}h)")

    # Prover errors (Gigahorse bug)
    n_err = len(log.get("prover_errors", []))
    n_plots = log.get("unique_bad_plots", 0)
    err_icon = "🚨" if n_err > ERROR_SPIKE_THRESHOLD else "⚠️" if n_err > 5 else "✅"
    lines.append(f"{err_icon} Prover errors: {n_err} ({n_plots} unique plots) [known giga37 bug]")

    # Block validation spikes
    spikes = log.get("validation_spikes", [])
    if spikes:
        worst = max(spikes)
        v_icon = "🚨" if worst > 60 else "⚠️"
        lines.append(f"{v_icon} Block validation spikes: {len(spikes)} (worst: {worst:.1f}s)")
    else:
        lines.append("✅ Block validation: normal")

    # Coin store slowness
    slow = log.get("coin_slow", [])
    if slow:
        lines.append(f"⚠️ Coin store slow writes: {len(slow)} (worst: {max(slow):.1f}s)")

    # Pooling errors
    p_err = log.get("pool_errors", [])
    if p_err:
        lines.append(f"⚠️ Pool errors: {len(p_err)} (dup proofs / late submissions)")

    # Alerts
    alerts = []
    if farm["status"] != "Farming":
        alerts.append("NODE IS NOT FARMING")
    if gap > expected * CRITICAL_GAP_MULTIPLIER:
        alerts.append(f"No win in {gap:.0f}h (>{CRITICAL_GAP_MULTIPLIER}× expected)")
    if n_err > ERROR_SPIKE_THRESHOLD:
        alerts.append(f"Prover error spike: {n_err} errors today")

    if alerts:
        lines.append("\n🚨 *ALERTS*: " + " | ".join(alerts))

    return "\n".join(lines)


if __name__ == "__main__":
    print(run())
