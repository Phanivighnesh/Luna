"""
Thin wrapper around Ollama's local HTTP API.

Not certain of exact tokens/sec on any given machine — that depends on the
CPU. Benchmark with `ollama run phi3:mini` directly before relying on timing
numbers.

Requires Ollama running locally: `ollama serve` (default port 11434), and the
model pulled: `ollama pull phi3:mini`.
"""

import httpx
import json

OLLAMA_BASE = "http://localhost:11434"
DEFAULT_MODEL = "phi3:mini"

SYSTEM_PROMPT = (
    "You are Luna, a helpful, privacy-first local AI assistant running entirely "
    "on the user's own computer. Be concise, friendly, and practical."
)


async def is_ollama_running() -> bool:
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{OLLAMA_BASE}/api/tags")
            return r.status_code == 200
    except Exception:
        return False


async def stream_chat(messages: list[dict], model: str = DEFAULT_MODEL, system_prompt: str = None):
    """
    Yields text tokens as they arrive from Ollama.
    `messages` should be a list of {"role": "user"/"assistant", "content": str}.
    Pass `system_prompt` to override the default Luna persona prompt — used by
    callers (like plan generation) that need the model to behave as a strict
    JSON-only function rather than a chatty assistant.
    """
    effective_system = system_prompt if system_prompt is not None else SYSTEM_PROMPT
    full_messages = [{"role": "system", "content": effective_system}] + messages
    payload = {"model": model, "messages": full_messages, "stream": True}

    try:
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", f"{OLLAMA_BASE}/api/chat", json=payload) as resp:
                if resp.status_code != 200:
                    yield f"[Error contacting local model: HTTP {resp.status_code}. Is 'ollama serve' running and is '{model}' pulled?]"
                    return
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    token = data.get("message", {}).get("content", "")
                    if token:
                        yield token
                    if data.get("done"):
                        break
    except httpx.ConnectError:
        yield ("[Could not reach Ollama at localhost:11434. Start it with 'ollama serve' "
               "and make sure the model is pulled with 'ollama pull phi3:mini'.]")


async def complete_chat(messages: list[dict], model: str = DEFAULT_MODEL, system_prompt: str = None) -> str:
    """Non-streaming variant — collects the full response before returning.
    Used when the caller needs complete text before proceeding (e.g. parsing
    JSON out of it), rather than displaying tokens live."""
    collected = ""
    async for token in stream_chat(messages, model, system_prompt=system_prompt):
        collected += token
    return collected
