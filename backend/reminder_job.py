"""
Background job: every 60 seconds, check for schedule items due within the
next 5 minutes and email a reminder for each one (once).
"""

from apscheduler.schedulers.background import BackgroundScheduler
from schedule_store import get_due_for_reminder, mark_reminder_sent
from mailer import send_email
from memory import log_activity

REMINDER_WINDOW_MINUTES = 5

scheduler = BackgroundScheduler()


def check_reminders() -> dict:
    due_items = get_due_for_reminder(minutes_before=REMINDER_WINDOW_MINUTES)
    sent, failed = 0, 0
    for item in due_items:
        result = send_email(
            subject=f"Reminder: {item['title']}",
            body=f"Your task '{item['title']}' is due at {item['due_at']} "
                 f"(within the next {REMINDER_WINDOW_MINUTES} minutes).",
        )
        if result["ok"]:
            mark_reminder_sent(item["id"])
            log_activity("reminder_emailed", item["title"])
            sent += 1
        else:
            log_activity("reminder_email_failed", f"{item['title']}: {result['message']}")
            failed += 1
    return {"checked": len(due_items), "sent": sent, "failed": failed}


def start_scheduler():
    if not scheduler.running:
        scheduler.add_job(check_reminders, "interval", seconds=60, id="reminder_check", replace_existing=True)
        scheduler.start()


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
