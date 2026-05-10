#!/usr/bin/env python3
"""
RuFlo Auto-Fixer — called by watchdog run_full() when errors are detected.

Flow per bot with errors:
  1. Classify the error (fixable code bug vs benign/environmental)
  2. Spawn a Claude Code agent with Ruflo MCP to read + fix the source
  3. Verify the fix compiles/imports cleanly
  4. git commit + push the changed files
  5. Return a summary for the WhatsApp digest

Only fixable errors trigger an agent. Environmental issues (credentials,
network, hardware) are logged and skipped — no agent waste.
"""
import json, os, re, subprocess, sys, tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, "/home/work/fraqtoos")
from core.logger import get_logger

log = get_logger("ruflo_fixer")

CLAUDE_BIN = "/home/work/.local/bin/claude"

# Map bot name → (source root, smoke-test command)
BOT_REGISTRY = {
    "Portfolio Bot": (
        "/home/work/portfolio_bot",
        "python3 -c \"import portfolio_bot; print('import OK')\" 2>&1 | head -5",
    ),
    "Utility Bill Bot": (
        "/home/work/utility-bill-bot",
        "node -e \"require('./check_bills_imap'); console.log('import OK')\" 2>&1 | head -5",
    ),
    "BTC Strategy Bot": (
        "/home/work/crypto-trading-bot",
        "python3 -c \"import btc_strategy; print('import OK')\" 2>&1 | head -5",
    ),
    "Chia AI Watcher": (
        "/home/work/fraqtoos",
        "python3 -c \"from bots.chia_ai_watcher import run; print('import OK')\" 2>&1 | head -5",
    ),
    "Chia Health Monitor": (
        "/home/work/fraqtoos",
        "python3 -c \"from bots.chia_health import run; print('import OK')\" 2>&1 | head -5",
    ),
    "Orchestrator": (
        "/home/work/fraqtoos",
        "python3 -c \"import orchestrator; print('import OK')\" 2>&1 | head -5",
    ),
    "Gemma Agent": (
        "/home/work/gemma-agent",
        "python3 -c \"import agent; print('import OK')\" 2>&1 | head -5",
    ),
}

# ── Error classification ───────────────────────────────────────────────────────

# Errors that are fixable code bugs
_FIXABLE = [
    r"ImportError", r"ModuleNotFoundError", r"SyntaxError",
    r"AttributeError", r"NameError", r"TypeError", r"KeyError",
    r"FileNotFoundError", r"IndentationError", r"JSONDecodeError",
    r"DeprecationWarning.*error", r"FutureWarning.*error",
    r"No module named",
]

# Errors to skip — hardware, credentials, transient network
_SKIP = [
    "gigahorse", "giga37", "prover error", "pool error",
    "block validation", "unsolicited transaction",
    "urllib3", "chardet", "requestsdependencywarning",
    "invalid_grant", "app password", "oauth",
    "timeout", "connection refused", "network",
    "nvidia", "ipc", "cuda",
    "whatsapp", "selenium", "webdriver",
    "geckodriver", "firefox",
]

def classify(error_text: str) -> str:
    """Return 'fix', 'skip', or 'benign'."""
    low = error_text.lower()
    if any(s in low for s in _SKIP):
        return "skip"
    if any(re.search(p, error_text, re.I) for p in _FIXABLE):
        return "fix"
    return "benign"


# ── Smoke test ────────────────────────────────────────────────────────────────

def smoke_test(cwd: str, cmd: str) -> bool:
    try:
        r = subprocess.run(
            cmd, shell=True, cwd=cwd,
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "PYTHONPATH": cwd}
        )
        out = r.stdout + r.stderr
        return "import OK" in out and r.returncode == 0
    except Exception as e:
        log.warning(f"smoke_test error: {e}")
        return False


# ── Claude Code agent invocation ──────────────────────────────────────────────

FIX_PROMPT_TMPL = """You are a bot-maintenance agent. Fix the error below in the {bot_name} source at {cwd}.

ERROR:
{error_context}

RULES:
- Read the relevant source file(s) first
- Make the MINIMAL change that fixes this specific error
- Do NOT refactor, add features, or touch unrelated code
- Do NOT commit — just edit the file(s)
- After editing, the module must import without errors

Fix the error now."""


def run_agent(bot_name: str, cwd: str, error_context: str) -> bool:
    """Invoke Claude Code CLI to fix one bot's error. Returns True if it exited 0."""
    prompt = FIX_PROMPT_TMPL.format(
        bot_name=bot_name, cwd=cwd,
        error_context=error_context[:1000],
    )

    # Write prompt to a temp file to avoid shell quoting issues
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write(prompt)
        prompt_file = f.name

    try:
        result = subprocess.run(
            [CLAUDE_BIN, "--dangerously-skip-permissions", "--print", prompt],
            cwd=cwd,
            capture_output=True, text=True,
            timeout=240,
            env={**os.environ, "DISPLAY": ":0"},
        )
        ok = result.returncode == 0
        if not ok:
            log.warning(f"[{bot_name}] agent stderr: {result.stderr[:300]}")
        else:
            log.info(f"[{bot_name}] agent completed")
        return ok
    except subprocess.TimeoutExpired:
        log.error(f"[{bot_name}] agent timed out after 240s")
        return False
    except FileNotFoundError:
        log.error(f"claude CLI not found at {CLAUDE_BIN}")
        return False
    finally:
        try:
            os.unlink(prompt_file)
        except Exception:
            pass


# ── Git commit + push ─────────────────────────────────────────────────────────

def commit_and_push(cwd: str, bot_name: str) -> bool:
    """Stage all changes, commit, and push to origin main. Returns True on success."""
    try:
        diff = subprocess.run(
            ["git", "diff", "--name-only"],
            cwd=cwd, capture_output=True, text=True, timeout=15
        )
        changed = diff.stdout.strip()
        if not changed:
            log.info(f"[{bot_name}] no file changes — nothing to commit")
            return False

        files = changed.replace("\n", ", ")
        now   = datetime.now().strftime("%Y-%m-%d %H:%M")
        msg   = (
            f"auto-fix: ruflo watchdog repaired {bot_name}\n\n"
            f"Changed: {files}\n"
            f"Fixed at: {now}\n\n"
            f"Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
        )

        subprocess.run(["git", "add", "-A"],              cwd=cwd, check=True, timeout=15)
        subprocess.run(["git", "commit", "-m", msg],      cwd=cwd, check=True, timeout=20)
        subprocess.run(["git", "push", "origin", "main"], cwd=cwd, check=True, timeout=30)

        log.info(f"[{bot_name}] ✓ committed + pushed: {files}")
        return True

    except subprocess.CalledProcessError as e:
        log.error(f"[{bot_name}] git error: {e}")
        return False
    except subprocess.TimeoutExpired:
        log.error(f"[{bot_name}] git operation timed out")
        return False


# ── Main entry ────────────────────────────────────────────────────────────────

def run_fixer(snapshot: dict) -> list[dict]:
    """
    Called by watchdog.run_full() with the bot health snapshot.
    Returns list of {bot, error, fixed, pushed} dicts for the digest.
    """
    results = []

    for bot_status in snapshot.get("bots", []):
        name   = bot_status["name"]
        errors = bot_status.get("errors", [])

        if not errors:
            continue

        error_text = "\n".join(errors)
        verdict    = classify(error_text)

        if verdict != "fix":
            log.info(f"[{name}] skipped ({verdict})")
            continue

        registry = BOT_REGISTRY.get(name)
        if not registry:
            log.warning(f"[{name}] not in BOT_REGISTRY — skipping")
            continue

        cwd, smoke_cmd = registry
        full_context   = f"Errors:\n{error_text}\n\nLast output:\n{bot_status.get('log_tail','')[:500]}"

        log.info(f"[{name}] 🔧 spawning Ruflo agent to fix: {error_text[:80]}")

        agent_ok = run_agent(name, cwd, full_context)
        record   = {"bot": name, "error": error_text[:120], "agent_ran": agent_ok,
                    "smoke_ok": False, "pushed": False}

        if agent_ok:
            # Verify the fix works before committing
            record["smoke_ok"] = smoke_test(cwd, smoke_cmd)
            if record["smoke_ok"]:
                record["pushed"] = commit_and_push(cwd, name)
            else:
                log.warning(f"[{name}] smoke test failed — NOT committing agent changes")
                # Roll back to avoid committing a broken fix
                subprocess.run(["git", "checkout", "--", "."], cwd=cwd,
                               capture_output=True, timeout=15)

        results.append(record)
        log.info(f"[{name}] result: {record}")

    return results


def format_wa_summary(results: list[dict]) -> str:
    """Build a WhatsApp message from fixer results."""
    if not results:
        return ""
    lines = ["🔧 *RuFlo Auto-Fix Report*\n"]
    for r in results:
        icon = "✅" if r["pushed"] else ("⚠️" if r["smoke_ok"] else "❌")
        status = "fixed + pushed" if r["pushed"] else (
            "smoke failed — rolled back" if r["agent_ran"] else "agent failed"
        )
        lines.append(f"{icon} *{r['bot']}*\n   {r['error'][:80]}\n   → {status}")
    return "\n".join(lines)


if __name__ == "__main__":
    # Standalone: run fixer against last watchdog snapshot
    report_path = "/home/work/fraqtoos/logs/watchdog_latest.json"
    try:
        with open(report_path) as f:
            data = json.load(f)
        results = run_fixer(data["snapshot"])
        print(json.dumps(results, indent=2))
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
