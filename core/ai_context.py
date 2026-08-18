#!/usr/bin/env python3
"""
Shared AI context layer — each bot writes a daily intelligence summary.
Orchestrator reads the full day at 23:00 for llama4 digest generation.
"""
import json, os, requests
from datetime import datetime
from threading import Lock

CONTEXT_FILE = "/home/work/fraqtoos/logs/ai_context.json"
OLLAMA_URL   = "http://localhost:11434/api/chat"

# 2026-08-18: AI calls go through the shared provider (Gemini first, local
# Ollama fallback). Import is defensive so this module still works if the
# provider is missing for any reason.
try:
    from core.ai_provider import ask as _ai_ask
except Exception:
    _ai_ask = None
_lock = Lock()

def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")

def _load() -> dict:
    if os.path.exists(CONTEXT_FILE):
        try:
            with open(CONTEXT_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def _save(data: dict):
    # Atomic write: temp file + rename. Prevents corruption if process is killed
    # mid-write (orchestrator can be SIGTERMed by systemd at any moment).
    tmp = CONTEXT_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, default=str)
    os.replace(tmp, CONTEXT_FILE)

def write_summary(bot: str, text: str):
    """Write a bot's daily summary. Called after each bot run."""
    with _lock:
        data = _load()
        today = _today()
        if today not in data:
            data[today] = {}
        data[today][bot] = text
        _save(data)

def read_today() -> dict:
    """Return today's summaries for all bots."""
    return _load().get(_today(), {})

def summarize_run(bot_name: str, output: str, success: bool, duration: int) -> str:
    """Use phi4 to write a 1-sentence summary of a bot run result."""
    if not output.strip():
        return f"{'Completed' if success else 'Failed'} with no output in {duration}s."

    prompt = (
        f"Bot '{bot_name}' {'succeeded' if success else 'FAILED'} in {duration}s.\n"
        f"Last output:\n{output[-600:]}\n\n"
        f"Write ONE sentence (max 120 chars) summarizing what happened. Be specific. No padding."
    )
    try:
        if _ai_ask:
            summary = _ai_ask(prompt, temperature=0.1, max_tokens=80,
                              local_models=["phi4"])
            if summary:
                return summary[:200]
        status = "OK" if success else "FAILED"
        return f"{bot_name} {status} in {duration}s."
    except Exception:
        status = "OK" if success else "FAILED"
        return f"{bot_name} {status} in {duration}s."

def generate_digest() -> str:
    """
    Use gemma4 to write a narrative daily digest from today's bot summaries.
    Called at 23:00 by orchestrator.
    """
    summaries = read_today()
    if not summaries:
        return "No bot activity recorded today."

    today = datetime.now().strftime("%d %b %Y")
    context = "\n".join([f"- {bot}: {summary}" for bot, summary in summaries.items()])

    prompt = (
        f"You are writing a daily WhatsApp report for a personal automation server. "
        f"Today is {today}. Here are the bot results:\n\n{context}\n\n"
        f"Write a clear, friendly daily summary. Use WhatsApp formatting (*bold*, line breaks). "
        f"Start with overall status (all OK / issues found). "
        f"Mention any failures or anomalies first. Keep it under 300 words. "
        f"End with one line: 'Next run: tomorrow 06:00'."
    )

    try:
        if _ai_ask:
            # Gemini first; local chain gemma4 -> phi4 preserved as fallback.
            out = _ai_ask(prompt, temperature=0.2, max_tokens=400,
                          local_models=["gemma4", "phi4"])
            if out:
                return out
        raise RuntimeError("no AI provider available")
    except Exception:
        if True:
            lines = [f"*FraqtoOS Daily — {today}*", "─" * 28]
            for bot, summary in summaries.items():
                lines.append(f"• *{bot}*: {summary}")
            lines.append("─" * 28)
            lines.append("Next run: tomorrow 06:00")
            return "\n".join(lines)
