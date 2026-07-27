"""
Intent detection + task execution engine.

Design: rule-based pattern matching first (fast, free, deterministic).
More specific patterns (schedule/mark done/web search) are checked before
generic ones so they don't get swallowed by broader matches.
If nothing matches, the message is treated as normal chat and goes to the LLM.

IMPORTANT SAFETY NOTE:
This module only DETECTS and DESCRIBES an action. It does not execute
anything until the frontend has shown the user a confirmation dialog and the
user has approved it (see /task/execute endpoint in app.py, called only after
the renderer's confirm() step) — EXCEPT for read-only / low-risk actions
(list_schedule, mark_done) which are explicit, non-destructive, user-issued
commands and don't need a modal.
"""

import re
import os
import subprocess
import platform
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from dateutil import parser as dateparser

import schedule_store

# Common location names -> IANA timezone. Not exhaustive — unmapped locations
# get an honest "I don't have that one" instead of a guess.
TIMEZONE_MAP = {
    "uae": "Asia/Dubai", "dubai": "Asia/Dubai", "abu dhabi": "Asia/Dubai",
    "india": "Asia/Kolkata", "delhi": "Asia/Kolkata", "mumbai": "Asia/Kolkata",
    "hyderabad": "Asia/Kolkata", "bangalore": "Asia/Kolkata", "chennai": "Asia/Kolkata",
    "usa": "America/New_York", "us": "America/New_York", "america": "America/New_York",
    "new york": "America/New_York", "california": "America/Los_Angeles",
    "los angeles": "America/Los_Angeles", "west coast": "America/Los_Angeles",
    "uk": "Europe/London", "london": "Europe/London", "england": "Europe/London",
    "japan": "Asia/Tokyo", "tokyo": "Asia/Tokyo",
    "china": "Asia/Shanghai", "beijing": "Asia/Shanghai",
    "singapore": "Asia/Singapore",
    "australia": "Australia/Sydney", "sydney": "Australia/Sydney",
    "germany": "Europe/Berlin", "berlin": "Europe/Berlin",
    "france": "Europe/Paris", "paris": "Europe/Paris",
    "canada": "America/Toronto", "toronto": "America/Toronto",
    "russia": "Europe/Moscow", "moscow": "Europe/Moscow",
    "brazil": "America/Sao_Paulo",
    "south africa": "Africa/Johannesburg",
    "saudi arabia": "Asia/Riyadh", "riyadh": "Asia/Riyadh",
    "pakistan": "Asia/Karachi",
    "bangladesh": "Asia/Dhaka",
}

# Actions that must go through the Allow/Deny modal before executing.
CONFIRMATION_REQUIRED = {"open_app", "search_file", "create_note", "schedule_task", "schedule_relative", "generate_plan", "web_search"}

PATTERNS = [
    # --- Time (deterministic, never goes to the LLM — no room to hallucinate) ---
    (re.compile(r"^what(?:'s| is)?\s+(?:the\s+)?time(?:\s+is\s+it)?(?:\s+in\s+(.+))?\??$", re.I), "get_time"),

    # --- Scheduling: absolute time ("at 5:00 PM") ---
    (re.compile(r"^(?:schedule|remind me to)\s+(.+?)\s+at\s+(.+)$", re.I), "schedule_task"),
    # --- Scheduling: relative time ("in 5 minutes", "remind me to X in 10 min") ---
    (re.compile(r"^(?:set (?:a )?reminder|remind me|reminder)(?:\s+(?:to|about)\s+(.+?))?\s+in\s+(\d+\s*(?:minutes?|mins?|hours?|hrs?))$", re.I), "schedule_relative"),
    (re.compile(r"^(?:mark|set)\s+(.+?)\s+(?:as\s+)?done$", re.I), "mark_done"),
    (re.compile(r"^(?:what'?s on my|show my|view my)\s+schedule.*$", re.I), "list_schedule"),

    # --- Plan generation: LLM proposes items, backend actually schedules them ---
    (re.compile(
        r"^(?:can you\s+)?(?:give me|create|make|build|generate)\s+(?:the\s+|a\s+)?"
        r"(?:best\s+(?:possible\s+)?)?(?:study\s+|learning\s+)?(?:plan|schedule)\s+for\s+"
        r"(.+?)\s+and\s+add\s+(?:it|them|those)\s+to\s+(?:the\s+|my\s+)?schedule$",
        re.I,
    ), "generate_plan"),

    # --- Web search (needs live internet, everything else stays local) ---
    (re.compile(r"^(?:search(?: the)? web for|look ?up|google|find out (?:about\s+)?)\s*(.+)$", re.I), "web_search"),

    # --- Existing desktop tasks ---
    (re.compile(r"^open\s+(.+?)(?:\s+and\s+.+)?$", re.I), "open_app"),
    (re.compile(r"^launch\s+(.+?)(?:\s+and\s+.+)?$", re.I), "open_app"),
    (re.compile(r"^find\s+(?:my\s+)?(.+)$", re.I), "search_file"),
    (re.compile(r"^search\s+(?:for\s+)?(.+)$", re.I), "search_file"),
    (re.compile(r"^remind me to\s+(.+)$", re.I), "create_reminder"),
    (re.compile(r"^remind me\s+(.+)$", re.I), "create_reminder"),
    (re.compile(r"^(?:create|make|add)\s+(?:a\s+)?(?:note|to-?do)\s*[:\-]?\s*(.*)$", re.I), "create_note"),
]


def detect_intent(text: str) -> dict:
    stripped = text.strip()
    for pattern, action in PATTERNS:
        m = pattern.match(stripped)
        if m:
            groups = m.groups()
            argument = groups[0].strip() if groups and groups[0] else ""
            extra = groups[1].strip() if len(groups) > 1 and groups[1] else None
            return {
                "action": action,
                "raw_text": text,
                "argument": argument,
                "extra": extra,  # e.g. time string for schedule_task
                "requires_confirmation": action in CONFIRMATION_REQUIRED,
                "description": describe_action(action, argument, extra),
            }
    if _is_completed_schedule_query(stripped):
        return {
            "action": "list_done_schedule",
            "raw_text": text,
            "argument": "",
            "extra": None,
            "requires_confirmation": False,
            "description": "Show completed schedule items.",
        }
    return {"action": "chat", "raw_text": text, "requires_confirmation": False}


DONE_KEYWORDS = ("done", "completed", "finished")
SCHEDULE_KEYWORDS = ("schedule", "task", "reminder", "to-do", "todo")


def _is_completed_schedule_query(text: str) -> bool:
    lower = text.lower()
    return any(k in lower for k in DONE_KEYWORDS) and any(k in lower for k in SCHEDULE_KEYWORDS)


def describe_action(action: str, argument: str, extra: str = None) -> str:
    descriptions = {
        "get_time": f"Check the current time{f' in {argument}' if argument else ''}.",
        "open_app": f"Open the application '{argument}' on this computer. (Note: I can only launch apps — I can't yet type or send anything inside them.)",
        "search_file": f"Search your local files for '{argument}'.",
        "create_reminder": f"Create a reminder: '{argument}'.",
        "create_note": f"Create a note: '{argument}'.",
        "schedule_task": f"Add '{argument}' to your schedule at {extra}, and email you a reminder 5 minutes before.",
        "schedule_relative": f"Set a reminder for '{argument or 'reminder'}' in {extra}, and email you 5 minutes before it's due.",
        "generate_plan": f"Ask the local model to draft a plan for '{argument}' and add each item directly to your schedule.",
        "mark_done": f"Mark '{argument}' as done.",
        "list_schedule": "Show your upcoming schedule.",
        "web_search": f"Search the web for '{argument}' (this is the one action that goes outside your computer).",
    }
    return descriptions.get(action, f"Perform action '{action}'.")


def execute_action(action: str, argument: str, extra: str = None) -> dict:
    """
    For anything in CONFIRMATION_REQUIRED, only call this AFTER the user has
    explicitly confirmed in the UI. Returns {"ok": bool, "message": str}.
    Web search additionally returns "results" (list) for the UI to render.
    """
    try:
        if action == "get_time":
            return _get_time(argument)
        if action == "open_app":
            return _open_app(argument)
        if action == "search_file":
            return _search_file(argument)
        if action == "create_reminder":
            return {"ok": True, "message": f"Reminder saved: {argument}"}
        if action == "create_note":
            return _create_note(argument)
        if action == "schedule_task":
            return _schedule_task(argument, extra)
        if action == "schedule_relative":
            return _schedule_relative(argument, extra)
        if action == "mark_done":
            return _mark_done(argument)
        if action == "list_schedule":
            return _list_schedule()
        if action == "list_done_schedule":
            return _list_done_schedule()
        return {"ok": False, "message": f"Unknown action: {action}"}
    except Exception as e:
        return {"ok": False, "message": f"Action failed: {e}"}


DISPLAY_NAME_OVERRIDES = {"uae": "UAE", "uk": "UK", "usa": "USA", "us": "US"}


def _get_time(location: str = "") -> dict:
    location = (location or "").strip()
    if not location:
        now = datetime.now()
        return {"ok": True, "message": f"It's currently {now.strftime('%I:%M %p on %A, %B %d, %Y')} (your computer's local time)."}

    key = location.lower()
    tz_name = TIMEZONE_MAP.get(key)
    if not tz_name:
        for k, v in TIMEZONE_MAP.items():
            if k in key or key in k:
                tz_name = v
                break
    if not tz_name:
        return {
            "ok": False,
            "message": f"I don't have a timezone mapping for '{location}' yet — I only cover a set list of "
                       f"common countries/cities. Try naming a major city, or ask without a location for your "
                       f"computer's local time."
        }
    display_name = DISPLAY_NAME_OVERRIDES.get(key, location.title())
    now = datetime.now(ZoneInfo(tz_name))
    return {"ok": True, "message": f"It's currently {now.strftime('%I:%M %p on %A, %B %d')} in {display_name} ({tz_name})."}


def _open_app(app_name: str) -> dict:
    system = platform.system()
    try:
        if system == "Windows":
            subprocess.Popen(f'start "" "{app_name}"', shell=True)
        elif system == "Darwin":
            subprocess.Popen(["open", "-a", app_name])
        else:
            subprocess.Popen([app_name])
        return {"ok": True, "message": f"Opening {app_name}..."}
    except Exception as e:
        return {"ok": False, "message": f"Could not open '{app_name}': {e}. Check the exact app name/path."}


def _search_file(query: str, search_root: str = None) -> dict:
    search_root = search_root or os.path.expanduser("~")
    matches = []
    query_lower = query.lower()
    max_results = 20
    for root, dirs, files in os.walk(search_root):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "AppData", "__pycache__")]
        for f in files:
            if query_lower in f.lower():
                matches.append(os.path.join(root, f))
                if len(matches) >= max_results:
                    break
        if len(matches) >= max_results:
            break
    if not matches:
        return {"ok": True, "message": f"No files matching '{query}' found under {search_root}."}
    listing = "\n".join(matches)
    return {"ok": True, "message": f"Found {len(matches)} file(s):\n{listing}"}


def _create_note(content: str) -> dict:
    notes_dir = os.path.join(os.path.dirname(__file__), "db", "notes")
    os.makedirs(notes_dir, exist_ok=True)
    filename = f"note_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    path = os.path.join(notes_dir, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content if content else "(empty note)")
    return {"ok": True, "message": f"Note saved to {path}"}


def _parse_time(time_str: str):
    """
    Parses natural-language-ish time strings like '5pm', 'tomorrow 9am',
    '2026-07-10 14:00'. Not certain this handles every phrasing correctly —
    dateutil's fuzzy parsing is good but not perfect; if a schedule item
    lands on the wrong time, have the user rephrase more explicitly
    (e.g. 'at 5:00 PM' instead of 'at evening').
    """
    try:
        return dateparser.parse(time_str, fuzzy=True, default=datetime.now())
    except Exception:
        return None


def _parse_relative_duration(duration_str: str):
    """Parses strings like '5 minutes', '10 mins', '1 hour', '2 hrs'."""
    m = re.match(r"(\d+)\s*(minutes?|mins?|hours?|hrs?)", duration_str.strip(), re.I)
    if not m:
        return None
    amount = int(m.group(1))
    unit = m.group(2).lower()
    if unit.startswith("h"):
        return timedelta(hours=amount)
    return timedelta(minutes=amount)


def _schedule_relative(title: str, duration_str: str) -> dict:
    delta = _parse_relative_duration(duration_str)
    if delta is None:
        return {"ok": False, "message": f"Couldn't understand the duration '{duration_str}'. Try 'in 5 minutes' or 'in 1 hour'."}
    title = title.strip() if title else "Reminder"
    due_at = datetime.now() + delta
    schedule_store.add_schedule_item(title, due_at)
    return {
        "ok": True,
        "message": f"Got it — reminding you about '{title}' at {due_at.strftime('%I:%M %p')} "
                   f"({duration_str} from now). I'll email a reminder 5 minutes before, if email is configured in Settings."
    }


def _schedule_task(title: str, time_str: str) -> dict:
    due_at = _parse_time(time_str)
    if not due_at:
        return {"ok": False, "message": f"Couldn't understand the time '{time_str}'. Try something like 'at 5:00 PM'."}
    if due_at < datetime.now():
        due_at = due_at + timedelta(days=1)  # assume next occurrence if time already passed today
    item_id = schedule_store.add_schedule_item(title, due_at)
    return {
        "ok": True,
        "message": f"Scheduled '{title}' for {due_at.strftime('%Y-%m-%d %H:%M')}. "
                   f"I'll email a reminder 5 minutes before (if email is configured in Settings)."
    }


FILLER_WORDS = {"the", "a", "an", "my", "that", "this"}


def _clean_title_fragment(text: str) -> str:
    """Strips filler words so 'mark the reminder as done' matches a title
    stored as just 'Reminder'. Keeps the original if stripping would empty it."""
    words = [w for w in text.split() if w.lower() not in FILLER_WORDS]
    cleaned = " ".join(words).strip()
    return cleaned if cleaned else text.strip()


def _mark_done(title_fragment: str) -> dict:
    cleaned = _clean_title_fragment(title_fragment)
    item_id = schedule_store.mark_done(title_contains=cleaned)
    if item_id:
        return {"ok": True, "message": f"Marked as done (item #{item_id})."}
    return {"ok": False, "message": f"Couldn't find a pending schedule item matching '{title_fragment}'."}


def _list_schedule() -> dict:
    items = schedule_store.list_schedule()
    if not items:
        return {"ok": True, "message": "Your schedule is empty."}
    lines = [f"#{i['id']} — {i['title']} at {i['due_at']} ({i['status']})" for i in items]
    return {"ok": True, "message": "Upcoming schedule:\n" + "\n".join(lines)}


def _list_done_schedule() -> dict:
    all_items = schedule_store.list_schedule(include_done=True)
    done_items = [i for i in all_items if i["status"] == "done"]
    if not done_items:
        return {"ok": True, "message": "Nothing has been marked done yet."}
    lines = [f"#{i['id']} — {i['title']} (was due {i['due_at']})" for i in done_items]
    return {"ok": True, "message": "Completed items:\n" + "\n".join(lines)}
