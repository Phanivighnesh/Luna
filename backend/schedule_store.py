"""
Schedule storage — daily-schedule items with a due time.

Named schedule_store.py (not schedule.py) to avoid shadowing Python's
built-in `sched`-adjacent stdlib naming and to keep imports unambiguous.
"""

from datetime import datetime, timedelta
from memory import get_conn


def init_schedule_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schedule (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                due_at TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                reminder_sent INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)


def add_schedule_item(title: str, due_at: datetime) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO schedule (title, due_at) VALUES (?, ?)",
            (title, due_at.isoformat()),
        )
        return cur.lastrowid


def list_schedule(include_done: bool = False):
    with get_conn() as conn:
        q = "SELECT id, title, due_at, status, reminder_sent FROM schedule"
        if not include_done:
            q += " WHERE status != 'done'"
        q += " ORDER BY due_at ASC"
        rows = conn.execute(q).fetchall()
    return [
        {"id": r[0], "title": r[1], "due_at": r[2], "status": r[3], "reminder_sent": bool(r[4])}
        for r in rows
    ]


def mark_done(item_id: int = None, title_contains: str = None):
    """Mark a schedule item done, either by exact id or by fuzzy title match
    (used when the command comes from natural language, e.g. 'mark gym as done')."""
    with get_conn() as conn:
        if item_id is not None:
            conn.execute("UPDATE schedule SET status='done' WHERE id=?", (item_id,))
            return item_id
        if title_contains:
            row = conn.execute(
                "SELECT id FROM schedule WHERE status='pending' AND title LIKE ? "
                "ORDER BY due_at ASC LIMIT 1",
                (f"%{title_contains}%",),
            ).fetchone()
            if row:
                conn.execute("UPDATE schedule SET status='done' WHERE id=?", (row[0],))
                return row[0]
    return None


def get_due_for_reminder(minutes_before: int = 5):
    """Items whose due time falls within the next `minutes_before` minutes
    and haven't had a reminder sent yet."""
    now = datetime.now()
    window_end = now + timedelta(minutes=minutes_before)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, title, due_at FROM schedule "
            "WHERE status='pending' AND reminder_sent=0 "
            "AND due_at <= ? AND due_at >= ?",
            (window_end.isoformat(), now.isoformat()),
        ).fetchall()
    return [{"id": r[0], "title": r[1], "due_at": r[2]} for r in rows]


def mark_reminder_sent(item_id: int):
    with get_conn() as conn:
        conn.execute("UPDATE schedule SET reminder_sent=1 WHERE id=?", (item_id,))
