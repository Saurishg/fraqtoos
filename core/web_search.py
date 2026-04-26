"""
Web search helper backed by local SearXNG (http://127.0.0.1:8888).

Usage from any bot:
    from core.web_search import search
    hits = search("bitcoin price trends 2026", n=5)
    for h in hits:
        print(h["title"], h["url"], h["content"])
"""
import requests

SEARXNG_URL = "http://127.0.0.1:8888"


def search(query: str, n: int = 10, engines: str | None = None,
           timeout: int = 15) -> list[dict]:
    """Return top-n results as [{title, url, content, engine}, ...].

    `engines` is a comma-separated subset (e.g. "google,bing") — None = all enabled.
    Returns [] on any failure (network, container down, malformed JSON).
    """
    params = {"q": query, "format": "json"}
    if engines:
        params["engines"] = engines
    try:
        r = requests.get(f"{SEARXNG_URL}/search", params=params, timeout=timeout)
        r.raise_for_status()
        data = r.json()
    except Exception:
        return []
    out = []
    for item in data.get("results", [])[:n]:
        out.append({
            "title":   item.get("title", "")[:200],
            "url":     item.get("url", ""),
            "content": item.get("content", "")[:500],
            "engine":  item.get("engine", ""),
        })
    return out


def search_summary(query: str, n: int = 5) -> str:
    """Compact text block for feeding into an LLM prompt."""
    hits = search(query, n=n)
    if not hits:
        return f"(no web results for: {query})"
    return "\n".join(
        f"- {h['title']}\n  {h['url']}\n  {h['content']}"
        for h in hits
    )


def is_up() -> bool:
    """Quick health check — used by watchdog."""
    try:
        r = requests.get(f"{SEARXNG_URL}/healthz", timeout=3)
        return r.status_code == 200
    except Exception:
        return False
