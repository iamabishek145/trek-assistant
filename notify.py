"""
notify.py — Day 6: alert the agency when a human needs to take over.

Channels (set in .env, use one or both):
  Telegram: TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID
  Gmail:    ALERT_EMAIL_FROM + ALERT_EMAIL_PASSWORD (a Gmail *app password*)
            + ALERT_EMAIL_TO
If nothing is set, the alert is printed in the server terminal instead,
so the app always works.

Setup helper:
    python notify.py   # finds your Telegram chat ID, or sends a test alert
"""

import os
import smtplib
from email.message import EmailMessage

import httpx
from dotenv import load_dotenv

load_dotenv()


def _telegram(subject: str, text: str) -> bool:
    token, chat_id = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not (token and chat_id):
        return False  # not configured
    r = httpx.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": f"{subject}\n\n{text}"[:4000]},
        timeout=10,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Telegram API {r.status_code}: {r.json().get('description')}")
    return True


def _email(subject: str, text: str) -> bool:
    sender = os.getenv("ALERT_EMAIL_FROM")
    password = os.getenv("ALERT_EMAIL_PASSWORD")
    to = os.getenv("ALERT_EMAIL_TO")
    if not (sender and password and to):
        return False  # not configured
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, sender, to
    msg.set_content(text)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as smtp:
        smtp.login(sender, password)
        smtp.send_message(msg)
    return True


def send_alert(subject: str, text: str) -> bool:
    """Send to every configured channel. Returns True if at least one worked.

    Never raises: a failed alert must not break the traveller's chat
    (the handoff is already saved in the database either way).
    """
    sent = False
    for name, channel in (("telegram", _telegram), ("email", _email)):
        try:
            if channel(subject, text):
                sent = True
                print(f"[alert] sent via {name}")
        except Exception as e:
            # Hide the bot token if it appears in an error message
            error = str(e).replace(os.getenv("TELEGRAM_BOT_TOKEN") or "<none>", "***")
            print(f"[alert] {name} failed: {type(e).__name__}: {error}")
    if not sent:
        print(f"[alert] not sent (no working channel). It was:\n{subject}\n{text}")
    return sent


if __name__ == "__main__":
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if token and not os.getenv("TELEGRAM_CHAT_ID"):
        # Step 2 of Telegram setup: find the chat ID of whoever messaged the bot
        try:
            updates = httpx.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=10).json()
        except httpx.HTTPError as e:
            raise SystemExit(f"Can't reach Telegram ({type(e).__name__}). Is it blocked on your network?")
        chats = {
            u["message"]["chat"]["id"]: u["message"]["chat"].get("first_name", "")
            for u in updates.get("result", []) if "message" in u
        }
        if chats:
            print("Put this in .env as TELEGRAM_CHAT_ID:")
            for chat_id, name in chats.items():
                print(f"  {chat_id}   ({name})")
        else:
            print("No messages yet. Open your bot in Telegram, send it 'hi', then run this again.")
    else:
        ok = send_alert("Test alert from Trek Assistant", "If you can read this, handoff alerts work.")
        print("Done." if ok else "Not sent. Check the settings in .env.")
