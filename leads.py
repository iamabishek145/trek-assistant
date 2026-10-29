"""
leads.py — store booking leads (Day 5) and human handoffs (Day 6) in SQLite.

SQLite is a full database that lives in a single file (leads.db) and ships
with Python, so there is nothing to install. When we deploy, this file is
the only thing that changes to move to Supabase (hosted Postgres).
"""

import sqlite3
from pathlib import Path

DB_FILE = Path(__file__).parent / "leads.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row  # lets us turn rows into dicts
    return conn


def init_db() -> None:
    """Create the leads table if it doesn't exist yet."""
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS leads (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at  TEXT DEFAULT CURRENT_TIMESTAMP,  -- UTC
                name        TEXT NOT NULL,
                trek        TEXT NOT NULL,
                start_date  TEXT NOT NULL,
                group_size  INTEGER NOT NULL,
                contact     TEXT NOT NULL,
                notes       TEXT DEFAULT '',
                status      TEXT DEFAULT 'new'  -- new / contacted / booked
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS handoffs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at  TEXT DEFAULT CURRENT_TIMESTAMP,  -- UTC
                reason      TEXT NOT NULL,
                priority    TEXT NOT NULL DEFAULT 'normal',  -- normal / urgent
                name        TEXT DEFAULT '',
                contact     TEXT DEFAULT '',
                transcript  TEXT DEFAULT '',  -- last messages, for context
                status      TEXT DEFAULT 'open'  -- open / done
            )
            """
        )


def save_lead(name: str, trek: str, start_date: str, group_size: int,
              contact: str, notes: str = "") -> int:
    """Save a lead and return its id (the booking reference).

    If the same contact already asked for the same trek and date, update
    that lead instead of creating a duplicate.
    """
    with _connect() as conn:
        existing = conn.execute(
            "SELECT id FROM leads WHERE contact = ? AND trek = ? AND start_date = ?",
            (contact, trek, start_date),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE leads SET name = ?, group_size = ?, notes = ? WHERE id = ?",
                (name, group_size, notes, existing["id"]),
            )
            return existing["id"]

        cursor = conn.execute(
            "INSERT INTO leads (name, trek, start_date, group_size, contact, notes) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (name, trek, start_date, group_size, contact, notes),
        )
        return cursor.lastrowid


def list_leads() -> list[dict]:
    """All leads, newest first."""
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM leads ORDER BY id DESC").fetchall()
    return [dict(row) for row in rows]


def save_handoff(reason: str, priority: str, name: str, contact: str,
                 transcript: str) -> int:
    """Save a handoff request and return its id."""
    with _connect() as conn:
        cursor = conn.execute(
            "INSERT INTO handoffs (reason, priority, name, contact, transcript) "
            "VALUES (?, ?, ?, ?, ?)",
            (reason, priority, name, contact, transcript),
        )
        return cursor.lastrowid


def list_handoffs() -> list[dict]:
    """All handoffs, newest first."""
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM handoffs ORDER BY id DESC").fetchall()
    return [dict(row) for row in rows]
