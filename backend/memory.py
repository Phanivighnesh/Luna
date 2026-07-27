"""
Memory layer for Luna.
Stores user preferences (key/value) and conversation history in SQLite.
Deliberately stores conversation TURNS, not raw logs of everything the OS does,
to keep the footprint small and keep the user in control of what's remembered.
"""

import sqlite3
import json
import os
from contextlib import contextmanager

DB_DIR = os.path.join(os.path.dirname(__file__), "db")
DB_PATH = os.path.join(DB_DIR, "luna.db")

os.makedirs(DB_DIR, exist_ok=True)


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memory (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                ts DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                detail TEXT,
                ts DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)


# ---------- Key/value preference memory ----------

def set_memory(key: str, value):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO memory (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP",
            (key, json.dumps(value)),
        )


def get_memory(key: str):
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM memory WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else None


def list_memory():
    with get_conn() as conn:
        rows = conn.execute("SELECT key, value, updated_at FROM memory ORDER BY updated_at DESC").fetchall()
    return [{"key": k, "value": json.loads(v), "updated_at": ts} for k, v, ts in rows]


def delete_memory(key: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM memory WHERE key=?", (key,))


def delete_all_memory():
    with get_conn() as conn:
        conn.execute("DELETE FROM memory")
        conn.execute("DELETE FROM conversations")
        conn.execute("DELETE FROM activity_log")


# ---------- Conversation history ----------

def add_message(conversation_id: str, role: str, content: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO conversations (conversation_id, role, content) VALUES (?, ?, ?)",
            (conversation_id, role, content),
        )


def get_conversation(conversation_id: str, limit: int = 30):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT role, content FROM conversations WHERE conversation_id=? ORDER BY id ASC LIMIT ?",
            (conversation_id, limit),
        ).fetchall()
    return [{"role": r, "content": c} for r, c in rows]


def list_conversations():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT conversation_id, MIN(ts) as started, COUNT(*) as msgs "
            "FROM conversations GROUP BY conversation_id ORDER BY started DESC"
        ).fetchall()
    return [{"conversation_id": cid, "started": s, "messages": m} for cid, s, m in rows]


# ---------- Activity / permission log (for the Privacy Dashboard) ----------

def log_activity(action: str, detail: str = ""):
    with get_conn() as conn:
        conn.execute("INSERT INTO activity_log (action, detail) VALUES (?, ?)", (action, detail))


def get_activity_log(limit: int = 100):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT action, detail, ts FROM activity_log ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
    return [{"action": a, "detail": d, "ts": ts} for a, d, ts in rows]
