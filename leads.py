"""
leads.py — store booking leads (Day 5) and human handoffs (Day 6).

Two databases, same functions:
  - Local:      SQLite file leads.db (no setup needed)
  - Production: Postgres on Supabase (Day 9), used when DATABASE_URL is set.
    Free hosts like Render wipe local files on every restart, so leads.db
    would be lost there. Supabase keeps the data.
"""

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
USE_POSTGRES = bool(DATABASE_URL)
DB_FILE = Path(__file__).parent / "leads.db"

if USE_POSTGRES:
    import psycopg
    from psycopg.rows import dict_row

# The few places where SQLite and Postgres SQL differ
P = "%s" if USE_POSTGRES else "?"  # placeholder for values in queries
ID = ("BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY" if USE_POSTGRES
      else "INTEGER PRIMARY KEY AUTOINCREMENT")
NOW = "TIMESTAMPTZ DEFAULT now()" if USE_POSTGRES else "TEXT DEFAULT CURRENT_TIMESTAMP"


@contextmanager
def _db():
    """Open a connection; commit if everything worked; always close it."""
    if USE_POSTGRES:
        # prepare_threshold=None: needed for Supabase's connection pooler
        conn = psycopg.connect(DATABASE_URL, row_factory=dict_row, prepare_threshold=None)
    else:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row  # rows behave like dicts
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """Create the tables if they don't exist yet."""
    with _db() as conn:
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS leads (
                id          {ID},
                created_at  {NOW},
                name        TEXT NOT NULL,
                trek        TEXT NOT NULL,
                start_date  TEXT NOT NULL,
                group_size  INTEGER NOT NULL,
                contact     TEXT NOT NULL,
                notes       TEXT DEFAULT '',
                status      TEXT DEFAULT 'new'  -- new / contacted / booked
            )""")
        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS handoffs (
                id          {ID},
                created_at  {NOW},
                reason      TEXT NOT NULL,
                priority    TEXT NOT NULL DEFAULT 'normal',  -- normal / urgent
                name        TEXT DEFAULT '',
                contact     TEXT DEFAULT '',
                transcript  TEXT DEFAULT '',  -- last messages, for context
                status      TEXT DEFAULT 'open'  -- open / done
            )""")
        if USE_POSTGRES:
            # Supabase also exposes tables through a public web API. Turning on
            # Row Level Security with no policies blocks that API completely;
            # our server connects as the database owner, so it's unaffected.
            conn.execute("ALTER TABLE leads ENABLE ROW LEVEL SECURITY")
            conn.execute("ALTER TABLE handoffs ENABLE ROW LEVEL SECURITY")


def save_lead(name: str, trek: str, start_date: str, group_size: int,
              contact: str, notes: str = "") -> int:
    """Save a lead and return its id (the booking reference).

    If the same contact already asked for the same trek and date, update
    that lead instead of creating a duplicate.
    """
    with _db() as conn:
        existing = conn.execute(
            f"SELECT id FROM leads WHERE contact = {P} AND trek = {P} AND start_date = {P}",
            (contact, trek, start_date),
        ).fetchone()
        if existing:
            conn.execute(
                f"UPDATE leads SET name = {P}, group_size = {P}, notes = {P} WHERE id = {P}",
                (name, group_size, notes, existing["id"]),
            )
            return existing["id"]

        row = conn.execute(
            f"INSERT INTO leads (name, trek, start_date, group_size, contact, notes) "
            f"VALUES ({P}, {P}, {P}, {P}, {P}, {P}) RETURNING id",
            (name, trek, start_date, group_size, contact, notes),
        ).fetchone()
        return row["id"]


def list_leads() -> list[dict]:
    """All leads, newest first."""
    with _db() as conn:
        rows = conn.execute("SELECT * FROM leads ORDER BY id DESC").fetchall()
    return [dict(row) for row in rows]


def save_handoff(reason: str, priority: str, name: str, contact: str,
                 transcript: str) -> int:
    """Save a handoff request and return its id."""
    with _db() as conn:
        row = conn.execute(
            f"INSERT INTO handoffs (reason, priority, name, contact, transcript) "
            f"VALUES ({P}, {P}, {P}, {P}, {P}) RETURNING id",
            (reason, priority, name, contact, transcript),
        ).fetchone()
        return row["id"]


def list_handoffs() -> list[dict]:
    """All handoffs, newest first."""
    with _db() as conn:
        rows = conn.execute("SELECT * FROM handoffs ORDER BY id DESC").fetchall()
    return [dict(row) for row in rows]
