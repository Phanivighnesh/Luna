"""
Luna backend — FastAPI service.

Run with:
    uvicorn app:app --reload --port 8000

Endpoints:
    POST   /chat                  -> streams model tokens, or returns a pending action
    POST   /task/execute          -> executes a confirmed action
    GET    /memory                -> list stored preferences
    POST   /memory/{key}          -> set a preference
    DELETE /memory/{key}          -> delete one preference
    DELETE /memory                -> delete everything (privacy dashboard "delete all")
    GET    /conversations         -> list past conversations
    GET    /conversations/{id}    -> get one conversation's messages
    GET    /activity              -> activity log for the privacy dashboard
    GET    /schedule               -> list upcoming schedule items
    POST   /schedule/{id}/done     -> mark a schedule item done
    GET    /health                -> check backend + ollama status
"""

from typing import Optional
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import json

from ai import stream_chat, is_ollama_running
from memory import (
    init_db, set_memory, get_memory, list_memory, delete_memory, delete_all_memory,
    add_message, get_conversation, list_conversations, log_activity, get_activity_log,
)
from tasks import detect_intent, execute_action
from schedule_store import init_schedule_db, list_schedule, mark_done
from mailer import send_email
from web_search import search_web, format_results_for_chat
from plan_generator import generate_and_schedule_plan
from reminder_job import start_scheduler, stop_scheduler

app = FastAPI(title="Luna Backend")

# Electron renderer runs on a file:// or localhost origin depending on setup.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()
init_schedule_db()


@app.on_event("startup")
def on_startup():
    start_scheduler()


@app.on_event("shutdown")
def on_shutdown():
    stop_scheduler()


class ChatRequest(BaseModel):
    message: str
    conversation_id: str = "default"


class ExecuteRequest(BaseModel):
    action: str
    argument: str = ""
    extra: Optional[str] = None


class MemoryValue(BaseModel):
    value: str


@app.get("/health")
async def health():
    ollama_ok = await is_ollama_running()
    return {"backend": "ok", "ollama_running": ollama_ok}


@app.post("/chat")
async def chat(req: ChatRequest):
    intent = detect_intent(req.message)
    add_message(req.conversation_id, "user", req.message)

    if intent["action"] != "chat":
        log_activity("intent_detected", json.dumps(intent))

        if not intent["requires_confirmation"]:
            # Low-risk, read-only style actions (list schedule, mark done) run immediately.
            result = execute_action(intent["action"], intent["argument"], intent.get("extra"))
            add_message(req.conversation_id, "assistant", result["message"])
            return {"type": "action_result", "result": result}

        return {
            "type": "action_pending",
            "action": intent["action"],
            "argument": intent["argument"],
            "extra": intent.get("extra"),
            "description": intent["description"],
        }

    history = get_conversation(req.conversation_id)

    async def gen():
        collected = ""
        async for token in stream_chat(history):
            collected += token
            yield token
        add_message(req.conversation_id, "assistant", collected)

    return StreamingResponse(gen(), media_type="text/plain")


@app.post("/task/execute")
async def task_execute(req: ExecuteRequest):
    """Called only after the user has confirmed the action in the UI.
    Always returns {"ok": bool, "message": str, ...} — never lets an
    exception escape as a bare 500 with no "message" field, since the
    frontend renders result.message directly into the chat."""
    try:
        if req.action == "web_search":
            results = await search_web(req.argument)
            message = format_results_for_chat(results)
            log_activity("web_search", req.argument)
            return {"ok": True, "message": message, "results": results}

        if req.action == "generate_plan":
            result = await generate_and_schedule_plan(req.argument)
            log_activity("generate_plan", f"{req.argument} -> {result['message'][:100]}")
            return result

        result = execute_action(req.action, req.argument, req.extra)
        log_activity("action_executed", f"{req.action}: {req.argument} -> {result['message']}")
        return result
    except Exception as e:
        log_activity("task_execute_error", f"{req.action}: {e}")
        return {"ok": False, "message": f"Something went wrong running that action: {e}"}


@app.get("/memory")
def memory_list():
    return list_memory()


@app.post("/memory/{key}")
def memory_set(key: str, body: MemoryValue):
    set_memory(key, body.value)
    log_activity("memory_set", key)
    return {"ok": True}


@app.delete("/memory/{key}")
def memory_delete_one(key: str):
    delete_memory(key)
    log_activity("memory_deleted", key)
    return {"ok": True}


@app.delete("/memory")
def memory_delete_everything():
    delete_all_memory()
    log_activity("memory_deleted_all", "")
    return {"ok": True}


@app.get("/conversations")
def conversations_list():
    return list_conversations()


@app.get("/conversations/{conversation_id}")
def conversation_get(conversation_id: str):
    return get_conversation(conversation_id, limit=200)


@app.get("/activity")
def activity():
    return get_activity_log()


@app.post("/settings/test-email")
def test_email():
    """Sends a test email immediately using whatever's currently saved in
    Settings, so misconfiguration shows up right away instead of silently
    failing in the background reminder check."""
    result = send_email(
        subject="Luna test email",
        body="If you're reading this, Luna's email reminders are configured correctly.",
    )
    log_activity("test_email", result["message"])
    return result


@app.get("/schedule")
def schedule_list(include_done: bool = False):
    return list_schedule(include_done=include_done)


@app.post("/schedule/{item_id}/done")
def schedule_mark_done(item_id: int):
    mark_done(item_id=item_id)
    log_activity("schedule_marked_done", str(item_id))
    return {"ok": True}
