"""
ratelimit.py — Day 8: protect /chat (and your API credits) from abuse.

Every /chat message costs money, and once the server is public anyone can
call it. Two limits, kept in memory (fine for a single server process):
  - per visitor:  RATE_LIMIT_PER_IP messages per 10 minutes (default 20)
  - whole server: DAILY_MESSAGE_CAP messages per day (default 500),
                  a budget safety net if many visitors arrive at once
"""

import os
import time
from collections import defaultdict, deque

from dotenv import load_dotenv

load_dotenv()

WINDOW_SECONDS = 600  # 10 minutes
PER_IP = int(os.getenv("RATE_LIMIT_PER_IP") or 20)
DAILY_CAP = int(os.getenv("DAILY_MESSAGE_CAP") or 500)

_hits: dict[str, deque] = defaultdict(deque)  # ip -> times of recent messages
_today = {"date": "", "count": 0}


def check(ip: str) -> str | None:
    """Return None if this message is allowed, otherwise a polite reason."""
    now = time.time()
    date = time.strftime("%Y-%m-%d", time.gmtime(now))
    if _today["date"] != date:  # new day (UTC): reset the daily counter
        _today.update(date=date, count=0)
        _hits.clear()
    if _today["count"] >= DAILY_CAP:
        return "Our assistant is very busy today. Please message the team on WhatsApp."

    hits = _hits[ip]
    while hits and hits[0] < now - WINDOW_SECONDS:  # forget old messages
        hits.popleft()
    if len(hits) >= PER_IP:
        minutes = int((hits[0] + WINDOW_SECONDS - now) // 60) + 1
        return f"You're sending messages very fast. Please try again in about {minutes} min."

    hits.append(now)
    _today["count"] += 1
    return None
