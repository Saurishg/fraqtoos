#!/usr/bin/env python3
"""
Multi-model pipeline — use models on local OR remote Ollama instance.

Usage:
    from core.remote_agent import Agent, Pipeline

    # Single model call
    result = Agent("qwen2.5:32b", host="192.168.1.50").ask("Summarize this...")

    # Multi-model pipeline (each model's output feeds the next)
    pipe = Pipeline([
        Agent("gemma3:27b",    host="192.168.1.50"),   # fast summarizer
        Agent("deepseek-r1:32b", host="192.168.1.50"), # reasoner
        Agent("qwen2.5:32b",   host="192.168.1.50"),   # writer
    ])
    final = pipe.run(initial_prompt, prompts=[
        "Summarize this raw data in 200 words: {input}",
        "Analyze this summary and find 3 key insights: {input}",
        "Write an Amazon listing based on these insights: {input}",
    ])
"""
import requests, sys
sys.path.insert(0, "/home/work/fraqtoos")
from core.logger import get_logger

log = get_logger("remote_agent")

LOCAL_HOST  = "http://localhost:11434"
REMOTE_HOST = "http://localhost:11434"  # change to remote IP e.g. "http://192.168.1.50:11434"


class Agent:
    def __init__(self, model: str, host: str = LOCAL_HOST, timeout: int = 300):
        self.model   = model
        self.host    = host.rstrip("/")
        self.timeout = timeout

    def ask(self, prompt: str, tokens: int = 1000, temperature: float = 0.1) -> str:
        log.info(f"Agent [{self.model}@{self.host}]: {prompt[:60]}...")
        try:
            r = requests.post(f"{self.host}/api/generate", json={
                "model":   self.model,
                "prompt":  prompt,
                "stream":  False,
                "options": {"temperature": temperature, "num_predict": tokens},
            }, timeout=self.timeout)
            r.raise_for_status()
            resp = r.json()["response"].strip()
            # Strip qwen3 thinking tags
            if "</think>" in resp:
                resp = resp.split("</think>")[-1].strip()
            log.info(f"Agent [{self.model}] done: {len(resp)} chars")
            return resp
        except Exception as e:
            log.error(f"Agent [{self.model}] failed: {e}")
            return ""

    def available(self) -> bool:
        try:
            r = requests.get(f"{self.host}/api/tags", timeout=5)
            models = [m["name"] for m in r.json().get("models", [])]
            return any(self.model in m for m in models)
        except:
            return False

    def list_models(self) -> list:
        try:
            r = requests.get(f"{self.host}/api/tags", timeout=5)
            return [m["name"] for m in r.json().get("models", [])]
        except:
            return []


class Pipeline:
    """Chain multiple agents — each output feeds into the next prompt."""
    def __init__(self, agents: list):
        self.agents = agents

    def run(self, initial_input: str, prompts: list, tokens: int = 1000) -> str:
        """
        prompts: list of prompt templates, use {input} as placeholder for previous output.
        Returns the final agent's output.
        """
        current = initial_input
        for i, (agent, prompt_template) in enumerate(zip(self.agents, prompts)):
            prompt = prompt_template.replace("{input}", current)
            log.info(f"Pipeline step {i+1}/{len(self.agents)}: {agent.model}")
            result = agent.ask(prompt, tokens=tokens)
            if not result:
                log.warning(f"Pipeline step {i+1} returned empty — stopping")
                break
            current = result
            print(f"\n--- Step {i+1} [{agent.model}] ---\n{result[:300]}...")
        return current


# ── Preset pipelines ────────────────────────────────────────────────────────

def amazon_listing_pipeline(raw_data: str, remote_host: str = REMOTE_HOST) -> str:
    """3-model pipeline: summarize → analyze → write listing."""
    pipe = Pipeline([
        Agent("gemma3:27b",      host=remote_host),
        Agent("deepseek-r1:32b", host=remote_host),
        Agent("qwen2.5:32b",     host=remote_host),
    ])
    return pipe.run(raw_data, prompts=[
        "Summarize this competitor data in 150 words, highlight price, GSM, keywords: {input}",
        "Based on this summary, identify 3 specific improvements for a new Amazon India microfiber cloth listing. Be direct: {input}",
        "Write an optimized Amazon India product listing (title + 5 bullets + keywords) using these improvements: {input}",
    ], tokens=800)


def research_pipeline(question: str, remote_host: str = REMOTE_HOST) -> str:
    """2-model pipeline: research → synthesize."""
    pipe = Pipeline([
        Agent("gemma3:27b",    host=remote_host),
        Agent("qwen2.5:32b",   host=remote_host),
    ])
    return pipe.run(question, prompts=[
        "Answer this question with facts and data: {input}",
        "Refine this answer, remove fluff, make it actionable for an Amazon India seller: {input}",
    ], tokens=600)


def vote(prompt: str, models: list, host: str = REMOTE_HOST) -> str:
    """Ask all models the same question, return the most common/best answer."""
    responses = []
    for model in models:
        resp = Agent(model, host=host).ask(prompt, tokens=400)
        if resp:
            responses.append((model, resp))
            print(f"\n[{model}]: {resp[:200]}")

    if not responses:
        return ""
    # Use the last (usually best) model's response as final
    # Or implement voting logic here
    return responses[-1][1]


if __name__ == "__main__":
    import sys
    remote = sys.argv[1] if len(sys.argv) > 1 else REMOTE_HOST

    print(f"Checking models on {remote}...")
    a = Agent("phi4", host=remote)
    print(f"Available models: {a.list_models()}")

    # Quick test
    resp = Agent("phi4", host=remote).ask("Say hello in one sentence.")
    print(f"Test response: {resp}")
