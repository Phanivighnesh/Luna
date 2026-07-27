"""
Turns a natural-language planning request ("create a plan for learning
FastAPI") into actual rows in the schedule table — instead of the LLM just
talking about a plan without anything real being created.

This is the one place the LLM's output is treated as structured data rather
than display text. It's constrained hard (system prompt demands JSON only)
and parsed defensively, because small local models don't reliably follow
"JSON only" instructions — expect this to occasionally fail to parse, and
handle that failure visibly rather than silently.
"""

import json
import re
from datetime import datetime, timedelta

from ai import complete_chat
import schedule_store

PLAN_SYSTEM_PROMPT = (
    "You output ONLY a JSON array and absolutely nothing else — no prose, no "
    "explanation, no markdown code fences. Each array element must be an "
    "object with exactly two fields: \"title\" (short string) and "
    "\"offset_minutes\" (integer — minutes from right now when this item "
    "should be scheduled). Produce between 3 and 8 realistic, well-spaced "
    "items. Use larger offsets to represent later days, e.g. 1440 for +1 day, "
    "2880 for +2 days. Respond with the JSON array and nothing before or after it."
)

MAX_ITEMS = 8


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


async def generate_and_schedule_plan(topic: str) -> dict:
    if not topic or not topic.strip():
        return {"ok": False, "message": "I need a topic to build a plan for — try 'create a plan for X and add it to my schedule'."}

    messages = [{"role": "user", "content": f"Create a plan for: {topic.strip()}"}]
    raw = await complete_chat(messages, system_prompt=PLAN_SYSTEM_PROMPT)
    cleaned = _strip_code_fences(raw)

    try:
        items = json.loads(cleaned)
    except json.JSONDecodeError:
        return {
            "ok": False,
            "message": "The model didn't return a clean plan this time (small local models don't always "
                       "follow strict formatting instructions). Try again, or phrase the topic more simply."
        }

    if not isinstance(items, list) or not items:
        return {"ok": False, "message": "The model didn't return a usable plan structure — try again."}

    added = []
    for item in items[:MAX_ITEMS]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        offset = item.get("offset_minutes")
        if not title or not isinstance(offset, (int, float)):
            continue
        due_at = datetime.now() + timedelta(minutes=int(offset))
        schedule_store.add_schedule_item(title, due_at)
        added.append(f"{title} — {due_at.strftime('%Y-%m-%d %I:%M %p')}")

    if not added:
        return {"ok": False, "message": "The model's response didn't contain any usable plan items — try again."}

    listing = "\n".join(f"• {a}" for a in added)
    return {"ok": True, "message": f"Added {len(added)} item(s) to your schedule:\n{listing}\n\nCheck the Schedule tab to review or adjust them."}
