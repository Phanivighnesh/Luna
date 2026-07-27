"""
Simple SMTP mailer for sending reminder emails.

Configuration is read from the memory store (set via the Settings tab):
  smtp_email          - the sending account's address
  smtp_app_password   - an app password (NOT the account's real password —
                         for Gmail this means enabling 2FA and generating an
                         "App Password" at https://myaccount.google.com/apppasswords)
  smtp_host           - defaults to smtp.gmail.com
  smtp_port           - defaults to 465 (SSL)
  notify_email        - where reminders get sent (defaults to smtp_email itself)

KNOWN LIMITATION: the app password is stored in plaintext in the local SQLite
file. Fine for a hackathon demo on a personal machine, not something to ship
as-is — flag this openly if asked about security.
"""

import smtplib
from email.mime.text import MIMEText
from memory import get_memory


def send_email(subject: str, body: str, to_addr: str = None) -> dict:
    smtp_email = get_memory("smtp_email")
    smtp_password = get_memory("smtp_app_password")
    smtp_host = get_memory("smtp_host") or "smtp.gmail.com"
    smtp_port = int(get_memory("smtp_port") or 465)
    recipient = to_addr or get_memory("notify_email") or smtp_email

    if not smtp_email or not smtp_password:
        return {"ok": False, "message": "Email isn't configured yet. Add your email + app password in Settings."}
    if not recipient:
        return {"ok": False, "message": "No recipient email configured."}

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = smtp_email
    msg["To"] = recipient

    try:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=10) as server:
            server.login(smtp_email, smtp_password)
            server.sendmail(smtp_email, [recipient], msg.as_string())
        return {"ok": True, "message": f"Email sent to {recipient}"}
    except Exception as e:
        return {"ok": False, "message": f"Failed to send email: {e}"}
