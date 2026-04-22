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
_lock = Lock()

def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")

def _load() -> dict:
    if os.path.exists(CONTEXT_FILE):
        try:
            return json.load(open(CONTEXT_FILE))
        except Exception:
            pass
    return {}

def _save(data: dict):
    with open(CONTEXT_FILE, "w") as f:
        json.dump(data, f, indent=2, default=str)

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
        r = requests.post(OLLAMA_URL, json={
            "model": "phi4",
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 80}
        }, timeout=60)
        r.raise_for_status()
        summary = r.json()["message"]["content"].strip()
        return summary[:200]
    except Exception as e:
        status = "OK" if success else "FAILED"
        return f"{bot_name} {status} in {duration}s."

def generate_digest() -> str:
    """
    Use llama4 to write a narrative daily digest from today's bot summaries.
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
        r = requests.post(OLLAMA_URL, json={
            "model": "llama4",
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": 0.2, "num_predict": 400}
        }, timeout=300)
        r.raise_for_status()
        return r.json()["message"]["content"].strip()
    except Exception as e:
        # Fallback to phi4 if llama4 times out
        try:
            r = requests.post(OLLAMA_URL, json={
                "model": "phi4",
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {"temperature": 0.2, "num_predict": 400}
            }, timeout=120)
            r.raise_for_status()
            return r.json()["message"]["content"].strip()
        except Exception:
            lines = [f"*FraqtoOS Daily — {today}*", "─" * 28]
            for bot, summary in summaries.items():
                lines.append(f"• *{bot}*: {summary}")
            lines.append("─" * 28)
            lines.append("Next run: tomorrow 06:00")
            return "\n".join(lines)
