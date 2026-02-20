"""
Database layer -- SQLite, single-file source of truth.
Tables: prospects, messages, email_suggestions, outbox.
"""

import sqlite3
import os
import logging
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "app.db")
logger = logging.getLogger("b2b.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS prospects (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    firstname     TEXT NOT NULL,
    lastname      TEXT NOT NULL,
    company       TEXT NOT NULL,
    company_key   TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS messages (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    company       TEXT NOT NULL,
    company_key   TEXT NOT NULL,
    subject       TEXT NOT NULL,
    body_text     TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS email_suggestions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    prospect_id      INTEGER NOT NULL REFERENCES prospects(id),
    domain           TEXT,
    pattern          TEXT,
    suggested_email  TEXT,
    confidence_score REAL DEFAULT 0,
    status           TEXT DEFAULT 'PENDING',
    debug_notes      TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS outbox (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    company       TEXT,
    company_key   TEXT,
    email         TEXT,
    firstname     TEXT,
    lastname      TEXT,
    subject       TEXT,
    body_text     TEXT,
    status        TEXT DEFAULT 'READY',
    sent_at       TEXT,
    error_message TEXT,
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def get_connection() -> sqlite3.Connection:
    """Return a new connection with row_factory set."""
    db_path = os.path.abspath(DB_PATH)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db():
    """Create tables if they don't exist."""
    conn = get_connection()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
    logger.info("Database initialised at %s", os.path.abspath(DB_PATH))


def reset_db():
    """Drop all tables and re-create."""
    conn = get_connection()
    for tbl in ("outbox", "email_suggestions", "messages", "prospects"):
        conn.execute(f"DROP TABLE IF EXISTS {tbl}")
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
    logger.info("Database reset.")


# ---- Generic helpers ----

def insert_prospect(conn, firstname, lastname, company, company_key):
    conn.execute(
        "INSERT INTO prospects (firstname, lastname, company, company_key) VALUES (?,?,?,?)",
        (firstname, lastname, company, company_key),
    )


def insert_message(conn, company, company_key, subject, body_text):
    conn.execute(
        "INSERT INTO messages (company, company_key, subject, body_text) VALUES (?,?,?,?)",
        (company, company_key, subject, body_text),
    )


def get_all_prospects(conn):
    return conn.execute("SELECT * FROM prospects ORDER BY id").fetchall()


def get_all_messages(conn):
    return conn.execute("SELECT * FROM messages ORDER BY id").fetchall()


def get_prospects_without_suggestion(conn, limit=None):
    q = """
        SELECT p.* FROM prospects p
        LEFT JOIN email_suggestions es ON es.prospect_id = p.id
        WHERE es.id IS NULL
        ORDER BY p.id
    """
    if limit:
        q += f" LIMIT {int(limit)}"
    return conn.execute(q).fetchall()


def get_all_prospects_for_find(conn, limit=None):
    q = "SELECT * FROM prospects ORDER BY id"
    if limit:
        q += f" LIMIT {int(limit)}"
    return conn.execute(q).fetchall()


def upsert_email_suggestion(conn, prospect_id, domain, pattern,
                            suggested_email, confidence_score, status, debug_notes):
    existing = conn.execute(
        "SELECT id FROM email_suggestions WHERE prospect_id=?", (prospect_id,)
    ).fetchone()
    now = datetime.utcnow().isoformat()
    if existing:
        conn.execute(
            """UPDATE email_suggestions
               SET domain=?, pattern=?, suggested_email=?, confidence_score=?,
                   status=?, debug_notes=?, created_at=?
               WHERE prospect_id=?""",
            (domain, pattern, suggested_email, confidence_score, status, debug_notes, now, prospect_id),
        )
    else:
        conn.execute(
            """INSERT INTO email_suggestions
               (prospect_id, domain, pattern, suggested_email, confidence_score, status, debug_notes, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (prospect_id, domain, pattern, suggested_email, confidence_score, status, debug_notes, now),
        )


def get_email_suggestions(conn):
    return conn.execute("""
        SELECT es.*, p.firstname, p.lastname, p.company
        FROM email_suggestions es
        JOIN prospects p ON p.id = es.prospect_id
        ORDER BY es.id
    """).fetchall()


def clear_outbox(conn):
    conn.execute("DELETE FROM outbox")


def insert_outbox(conn, company, company_key, email, firstname, lastname,
                  subject, body_text, status, error_message=""):
    now = datetime.utcnow().isoformat()
    conn.execute(
        """INSERT INTO outbox
           (company, company_key, email, firstname, lastname, subject, body_text, status, error_message, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (company, company_key, email, firstname, lastname, subject, body_text, status, error_message, now),
    )


def get_outbox(conn, status_filter=None, search_text=None):
    q = "SELECT * FROM outbox WHERE 1=1"
    params = []
    if status_filter:
        q += " AND status=?"
        params.append(status_filter)
    if search_text:
        q += " AND (company LIKE ? OR email LIKE ? OR subject LIKE ?)"
        like = f"%{search_text}%"
        params.extend([like, like, like])
    q += " ORDER BY id"
    return conn.execute(q, params).fetchall()


def update_outbox_status(conn, outbox_id, status, error_message="", sent_at=None):
    now = datetime.utcnow().isoformat()
    conn.execute(
        """UPDATE outbox SET status=?, error_message=?, sent_at=?, updated_at=?
           WHERE id=?""",
        (status, error_message, sent_at or "", now, outbox_id),
    )


def update_outbox_status_by_email(conn, email, status, error_message=""):
    now = datetime.utcnow().isoformat()
    conn.execute(
        """UPDATE outbox SET status=?, error_message=?, updated_at=?
           WHERE email=? AND status IN ('SENT','READY')""",
        (status, error_message, now, email),
    )


def count_outbox_by_status(conn):
    rows = conn.execute(
        "SELECT status, COUNT(*) as cnt FROM outbox GROUP BY status"
    ).fetchall()
    return {r["status"]: r["cnt"] for r in rows}


# Auto-init on import
init_db()
