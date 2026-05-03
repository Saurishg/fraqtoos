"""
Chia AI log watcher — phi4 classifies new Chia debug.log entries every 2h,
then the gemma-agent attempts to fix any identified issues automatically.

Flow:
  1. Read last_check timestamp from state file
  2. Extract log lines since that timestamp (or last 600 lines as fallback)
  3. phi4 classifies: severity + issues + fix_cmd (a safe bash command to run)
  4. If fix_cmd != "none" → gemma-agent executes it with bash access
  5. Alert via WhatsApp on critical (max once per 4h), include fix result
  6. Write full analysis + fix result to logs/chia_ai_latest.json
"""
import json
import re
import requests
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, "/home/work/fraqtoos")
sys.path.insert(0, "/home/work/gemma-agent")

LOG_PATH    = Path.home() / ".chia/mainnet/log/debug.log"
STATE_FILE  = Path("/home/work/fraqtoos/logs/chia_watcher_state.json")
OUTPUT_FILE = Path("/home/work/fraqtoos/logs/chia_ai_latest.json")
FIX_LOG     = Path("/home/work/fraqtoos/logs/chia_ai_fixes.log")
OLLAMA_URL  = "http://localhost:11434/api/chat"
PHI4_MODEL  = "phi4"
ALERT_COOLDOWN_HOURS = 4
MAX_LOG_LINES        = 600

# Safe fix commands phi4 is allowed to suggest.
# The agent is constrained to this allowlist — no arbitrary shell injection.
SAFE_FIX_ALLOWLIST = [
    "chia",           # all chia CLI commands
    "systemctl",      # service management
    "sqlite3",        # DB maintenance
    "python3",        # scripts
    "journalctl",     # log inspection
    "df ",            # disk check
    "du ",            # disk usage
    "sync",           # flush buffers
    "none",           # no-op sentinel
]

CLASSIFY_PROMPT = """\
You are a Chia blockchain node health analyst. Output ONLY valid JSON — no prose, \
no markdown fences.

Known benign (severity=ok, fix_cmd="none"):
- "Exception fetching qualities" / "Invalid size for deltas": Gigahorse giga37 bug, \
harmless unless count >20 in batch
- "Block validation: Ns" where N<60s: normal post-fork load
- "coin_store took Ns" where N<30s: normal post-fork load
- Routine signage point messages, peer connections, plot file opens

Alert-worthy (set severity=warning or critical, set fix_cmd):
- Node not farming / "Not running" → fix_cmd: "sudo systemctl restart chia-full-node"
- Harvester not responding → fix_cmd: "sudo systemctl restart chia-harvester"
- Block validation >60s repeatedly → fix_cmd: \
"sqlite3 ~/.chia/mainnet/db/blockchain_v2_mainnet.sqlite 'PRAGMA wal_checkpoint(TRUNCATE);'"
- coin_store >60s repeatedly → same DB checkpoint command
- Pool missed signage points >5 in batch → fix_cmd: "sudo systemctl restart chia-farmer"
- Prover errors >20 → fix_cmd: "none" (known GPU bug, no fix available)
- OOM → fix_cmd: "sudo sync && echo 3 | sudo tee /proc/sys/vm/drop_caches"
- DB corruption hints → fix_cmd: \
"sqlite3 ~/.chia/mainnet/db/blockchain_v2_mainnet.sqlite 'PRAGMA integrity_check;'"

fix_cmd MUST be a single safe shell command or "none". \
Never suggest rm, mv, or destructive operations.

Required JSON (output nothing else):
{
  "severity": "ok",
  "summary": "one sentence",
  "new_issues": [],
  "prover_errors_in_batch": 0,
  "fix_cmd": "none",
  "fix_reason": "why this fix helps, or empty string"
}

severity: ok | warning | critical"""

_FALLBACK_PROMPT = """\
Convert this Chia log analysis to the JSON template. Output ONLY the JSON.
Template: {"severity":"ok","summary":"...","new_issues":[],"prover_errors_in_batch":0,"fix_cmd":"none","fix_reason":""}
Analysis to convert: """

# System prompt given to the gemma-agent when it executes a fix
FIX_AGENT_SYSTEM = """\
You are a Chia node maintenance agent running on an Ubuntu server.
You have been handed a SINGLE fix command to run for a detected Chia issue.
Steps:
1. Run the provided command using the bash tool.
2. Check the output — did it succeed?
3. If it succeeded, run "chia farm summary" to confirm the node is healthy.
4. Report the result in 2-3 sentences: what you ran, what happened, whether Chia is OK.
Do NOT run any other commands beyond these. Do NOT modify files. Be concise."""


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"last_check": None, "last_alerted": None}


def _save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def _extract_new_lines(since_iso: str | None) -> str:
    if not LOG_PATH.exists():
        return ""

    if since_iso:
        cutoff = since_iso[:16]
        lines = []
        with open(LOG_PATH, errors="replace") as fh:
            for line in fh:
                m = re.match(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})", line)
                if m and m.group(1) >= cutoff:
                    lines.append(line.rstrip())
        if lines:
            return "\n".join(lines[-MAX_LOG_LINES:])

    try:
        out = subprocess.check_output(
            ["tail", "-n", str(MAX_LOG_LINES), str(LOG_PATH)],
            text=True, timeout=10,
        )
        return out.strip()
    except Exception:
        return ""


def _call_phi4(log_excerpt: str) -> dict:
    user_msg = "Classify these Chia log lines. Reply with ONLY the JSON:\n\n" + log_excerpt[:12_000]
    payload = {
        "model": PHI4_MODEL,
        "messages": [
            {"role": "system", "content": CLASSIFY_PROMPT},
            {"role": "user",   "content": user_msg},
        ],
        "stream": False,
        "options": {"temperature": 0.0},
    }
    resp = requests.post(OLLAMA_URL, json=payload, timeout=120)
    resp.raise_for_status()
    content = resp.json()["message"]["content"].strip()

    for attempt in [content]:
        try:
            return json.loads(attempt)
        except json.JSONDecodeError:
            pass
        m = re.search(r"\{[^{}]*\"severity\"[^{}]*\}", attempt, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass

    # Fallback: ask phi4 to reformat its own prose
    r2 = requests.post(OLLAMA_URL, json={
        "model": PHI4_MODEL,
        "messages": [{"role": "user", "content": _FALLBACK_PROMPT + content[:600]}],
        "stream": False,
        "options": {"temperature": 0.0},
    }, timeout=60)
    r2.raise_for_status()
    c2 = r2.json()["message"]["content"].strip()
    m2 = re.search(r"\{.*\}", c2, re.DOTALL)
    if m2:
        return json.loads(m2.group(0))

    raise ValueError(f"phi4 non-JSON after fallback: {content[:300]}")


def _is_safe_cmd(cmd: str) -> bool:
    if not cmd or cmd.strip().lower() == "none":
        return False
    first_token = cmd.strip().split()[0].lower()
    # sudo wraps — check second token
    if first_token == "sudo":
        parts = cmd.strip().split()
        first_token = parts[1].lower() if len(parts) > 1 else ""
    return any(first_token.startswith(safe) for safe in SAFE_FIX_ALLOWLIST)


def _run_fix(fix_cmd: str, fix_reason: str, issues: list[str]) -> str:
    """Invoke the gemma-agent to execute fix_cmd and return its report."""
    try:
        from agent import run_agent
    except ImportError:
        return f"agent import failed — fix not applied"

    task = (
        f"Issue detected in Chia node: {'; '.join(issues[:2])}\n"
        f"Fix reason: {fix_reason}\n"
        f"Run this exact command to fix it: {fix_cmd}\n"
        "Then verify the node is healthy. Report what happened in 2-3 sentences."
    )
    try:
        result = run_agent(task, model=PHI4_MODEL, verbose=False)
        _append_fix_log(fix_cmd, fix_reason, result or "no output")
        return result or "agent returned no output"
    except Exception as e:
        return f"agent error: {e}"


def _append_fix_log(cmd: str, reason: str, result: str):
    FIX_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(FIX_LOG, "a") as fh:
        fh.write(json.dumps({
            "ts": datetime.now().isoformat(timespec="seconds"),
            "cmd": cmd,
            "reason": reason,
            "result": result[:500],
        }) + "\n")


def run() -> str:
    now_iso = datetime.now().isoformat(timespec="seconds")
    state   = _load_state()

    log_text = _extract_new_lines(state.get("last_check"))
    if not log_text:
        return "Chia AI Watcher: no new log lines since last check."

    line_count = log_text.count("\n") + 1

    try:
        verdict = _call_phi4(log_text)
    except Exception as e:
        return f"Chia AI Watcher: phi4 classification failed — {e}"

    severity   = verdict.get("severity", "ok")
    summary    = verdict.get("summary", "")
    fix_cmd    = verdict.get("fix_cmd", "none").strip()
    fix_reason = verdict.get("fix_reason", "")
    raw_issues = verdict.get("new_issues", [])
    issues = [
        i if isinstance(i, str) else i.get("description", str(i))
        for i in raw_issues
    ]

    fix_result = None

    # ── Auto-fix if phi4 recommended one and it passes the allowlist ─────────
    if severity in ("warning", "critical") and _is_safe_cmd(fix_cmd):
        fix_result = _run_fix(fix_cmd, fix_reason, issues)

    # Persist full result
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps({
        "checked_at":     now_iso,
        "lines_analyzed": line_count,
        **verdict,
        "fix_applied":    fix_cmd if fix_result else None,
        "fix_result":     fix_result,
    }, indent=2))

    state["last_check"] = now_iso
    _save_state(state)

    # ── WhatsApp alert on critical ───────────────────────────────────────────
    if severity == "critical":
        last_alerted = state.get("last_alerted")
        too_soon = False
        if last_alerted:
            elapsed = (datetime.now() - datetime.fromisoformat(last_alerted)).total_seconds()
            too_soon = elapsed < ALERT_COOLDOWN_HOURS * 3600

        if not too_soon:
            from core.notifier import send_alert
            msg = f"🚨 *Chia AI Alert*\n{summary}\n" + "\n".join(f"• {i}" for i in issues[:4])
            if fix_result:
                msg += f"\n\n🔧 *Auto-fix applied:*\n`{fix_cmd}`\n{fix_result[:300]}"
            send_alert("Chia AI Watcher", msg)
            state["last_alerted"] = now_iso
            _save_state(state)

    # ── Console / orchestrator output ────────────────────────────────────────
    icon = {"ok": "✅", "warning": "⚠️", "critical": "🚨"}.get(severity, "❓")
    lines = [f"{icon} Chia AI ({severity}): {summary}"]
    if issues:
        lines += [f"  • {i}" for i in issues[:3]]
    if fix_result:
        lines.append(f"  🔧 Fix ({fix_cmd[:60]}): {fix_result[:120]}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(run())
