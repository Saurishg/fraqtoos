"""Shared AI provider — local Ollama only.

2026-08-19: Gemini was removed from this system entirely at the user's request.
This module keeps the single-entry-point design so the bots that already import
it (ai_context, chia_ai_watcher, crypto_portfolio) need no changes; it simply
has one backend now.

ask() never raises. Callers get a string, or "" if every local model failed, so
a bot can always fall back to its own non-AI behaviour.
"""
from __future__ import annotations
import os, requests

OLLAMA       = os.getenv("OLLAMA_URL", "http://localhost:11434")
LOCAL_MODELS = ["phi4", "gemma4", "gpt-oss:20b"]

_last_provider = "none"


def last_provider() -> str:
    """Which backend answered the most recent ask() - 'ollama:<model>' or 'none'."""
    return _last_provider


def _ollama(prompt, system, temperature, max_tokens, models=None, timeout=120):
    msgs = ([{"role": "system", "content": system}] if system else []) + \
           [{"role": "user", "content": prompt}]
    for model in (models or LOCAL_MODELS):
        try:
            r = requests.post(f"{OLLAMA}/api/chat", timeout=timeout, json={
                "model": model, "messages": msgs, "stream": False,
                "options": {"temperature": temperature, "num_predict": max_tokens},
            })
            r.raise_for_status()
            txt = (r.json().get("message", {}).get("content") or "").strip()
            if txt:
                globals()["_last_provider"] = f"ollama:{model}"
                return txt
        except Exception:
            continue
    return ""


def ask(prompt: str, system: str = "", temperature: float = 0.1,
        max_tokens: int = 800, local_models=None, prefer_local: bool = True,
        timeout: int = 120) -> str:
    """Run a prompt against the local Ollama chain. Returns "" if all failed.

    prefer_local is accepted and ignored - kept so existing callers that pass it
    do not break now that local is the only backend.
    timeout is per model. Ollama runs on CPU since 2026-11-20 (~40 prompt tok/s
    for phi4), so a long prompt needs more than the 120 s default.
    """
    globals()["_last_provider"] = "none"
    return _ollama(prompt, system, temperature, max_tokens, local_models, timeout)
