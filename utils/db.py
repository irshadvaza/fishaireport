"""
db.py
-----
Persists every submitted report (structured data, transcript, photos, the
generated Excel file, the generated PDF, and its narrative text) to a local
SQLite database file, so the Supervisor Dashboard page can list, browse, and
re-download them by date, and so the Master Log can be rebuilt on demand.

SQLite is used because it needs zero setup (it's a single file, built into
Python's standard library) — perfect for a self-hosted / single-server
deployment. If you deploy on a platform with an ephemeral filesystem (e.g.
Streamlit Community Cloud), this file gets wiped on every redeploy/restart —
see README.md section "Persistence caveat" for how to point this at a real
hosted database instead when that matters to you.
"""

import os
import json
import sqlite3
import datetime

DB_PATH = os.getenv("DB_PATH", os.path.join(os.path.dirname(__file__), "..", "reports.db"))


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_columns(conn, table: str, columns: dict):
    """Adds any missing columns to an already-existing table (simple migration
    helper so older reports.db files created before a feature was added still work)."""
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for col, coltype in columns.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}")


def init_db():
    """Creates the tables if they don't exist yet, and migrates older DB files
    to have any newly added columns. Safe to call on every page load."""
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_date TEXT NOT NULL,      -- YYYY-MM-DD, the calendar day it was submitted
                submitted_at TEXT NOT NULL,     -- full timestamp, for ordering same-day reports
                submitted_by TEXT,              -- staff username who submitted it
                supervisor_name TEXT,           -- name spoken in the transcript, e.g. "Mr. Marks"
                total_tables INTEGER,
                transcript TEXT,
                data_json TEXT NOT NULL,        -- full structured JSON from the extraction LLM call
                excel_blob BLOB,                -- the generated per-report .xlsx (tables only, no photos)
                pdf_blob BLOB,                  -- the generated visit-report .pdf (narrative + photos)
                narrative_json TEXT             -- the LLM-written narrative sections used in the PDF
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS report_images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_id INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
                image_blob BLOB NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS app_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,       -- e.g. stt_transcribe, llm_extract, report_saved, login_failed
                status TEXT NOT NULL,           -- ok | error
                username TEXT,
                role TEXT,
                duration_ms REAL,
                meta_json TEXT                  -- arbitrary extra structured detail
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS login_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                role TEXT NOT NULL,
                username TEXT NOT NULL,
                success INTEGER NOT NULL        -- 1 or 0
            )
        """)
        _ensure_columns(conn, "reports", {"pdf_blob": "BLOB", "narrative_json": "TEXT"})
        conn.commit()


def save_report(
    data: dict,
    transcript: str,
    images: list,
    excel_bytes: bytes,
    submitted_by: str,
    pdf_bytes: bytes = None,
    narrative: dict = None,
) -> int:
    """Saves one report (+ its photos) and returns the new report's id."""
    report_date = datetime.date.today().isoformat()  # the day it was actually submitted
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO reports
               (report_date, submitted_at, submitted_by, supervisor_name, total_tables,
                transcript, data_json, excel_blob, pdf_blob, narrative_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                report_date,
                datetime.datetime.now().isoformat(timespec="seconds"),
                submitted_by,
                data.get("supervisor_name"),
                data.get("total_tables_declared"),
                transcript,
                json.dumps(data),
                excel_bytes,
                pdf_bytes,
                json.dumps(narrative) if narrative else None,
            ),
        )
        report_id = cur.lastrowid
        for img_bytes in (images or []):
            conn.execute(
                "INSERT INTO report_images (report_id, image_blob) VALUES (?, ?)",
                (report_id, img_bytes),
            )
        conn.commit()
        return report_id


def list_reports(date_from: str = None, date_to: str = None) -> list:
    """Returns lightweight summary rows (no blobs) for the dashboard's list view."""
    query = "SELECT id, report_date, submitted_at, submitted_by, supervisor_name, total_tables FROM reports"
    clauses, params = [], []
    if date_from:
        clauses.append("report_date >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("report_date <= ?")
        params.append(date_to)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY submitted_at DESC"

    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def list_full_reports(date_from: str = None, date_to: str = None) -> list:
    """Like list_reports, but includes the parsed structured data (no blobs) —
    used to (re)build the Master Log across many reports without loading every
    photo/Excel/PDF into memory."""
    query = "SELECT id, report_date, submitted_at, submitted_by, supervisor_name, data_json FROM reports"
    clauses, params = [], []
    if date_from:
        clauses.append("report_date >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("report_date <= ?")
        params.append(date_to)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY submitted_at ASC"

    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
        records = []
        for r in rows:
            rec = dict(r)
            rec["data"] = json.loads(rec.pop("data_json"))
            records.append(rec)
        return records


def get_report(report_id: int) -> dict:
    """Returns the full record (parsed JSON data, narrative, and photo bytes) for one report."""
    with _connect() as conn:
        row = conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
        if not row:
            return None
        record = dict(row)
        record["data"] = json.loads(record["data_json"])
        record["narrative"] = json.loads(record["narrative_json"]) if record.get("narrative_json") else None
        image_rows = conn.execute(
            "SELECT image_blob FROM report_images WHERE report_id = ?", (report_id,)
        ).fetchall()
        record["images"] = [r["image_blob"] for r in image_rows]
        return record


def count_recent_reports_by_user(username: str, minutes: int) -> int:
    """Used for simple abuse/cost-control rate limiting — see security section of README."""
    since = (datetime.datetime.now() - datetime.timedelta(minutes=minutes)).isoformat(timespec="seconds")
    with _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM reports WHERE submitted_by = ? AND submitted_at >= ?",
            (username, since),
        ).fetchone()
        return row["n"] if row else 0


# ---------------------------------------------------------------------------
# Observability — every STT/LLM call, report submission, email send, and
# security-relevant event lands here so the Admin/Ops page can query it.
# ---------------------------------------------------------------------------

def log_event_db(event_type: str, status: str, username: str, role: str, duration_ms: float, meta: dict):
    with _connect() as conn:
        conn.execute(
            "INSERT INTO app_events (timestamp, event_type, status, username, role, duration_ms, meta_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                datetime.datetime.now().isoformat(timespec="seconds"),
                event_type, status, username, role, duration_ms,
                json.dumps(meta, default=str) if meta else None,
            ),
        )
        conn.commit()


def get_recent_events(limit: int = 100, event_type: str = None, status: str = None) -> list:
    query = "SELECT * FROM app_events"
    clauses, params = [], []
    if event_type:
        clauses.append("event_type = ?")
        params.append(event_type)
    if status:
        clauses.append("status = ?")
        params.append(status)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def get_event_stats(since_minutes: int = 1440) -> dict:
    """Simple rollup used by the Admin/Ops page: counts + average durations per event_type,
    over the last `since_minutes` (default 24h)."""
    since = (datetime.datetime.now() - datetime.timedelta(minutes=since_minutes)).isoformat(timespec="seconds")
    with _connect() as conn:
        rows = conn.execute(
            """SELECT event_type, status, COUNT(*) AS n, AVG(duration_ms) AS avg_ms
               FROM app_events WHERE timestamp >= ? GROUP BY event_type, status""",
            (since,),
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Login attempts — backs the account-lockout logic in utils/auth.py
# ---------------------------------------------------------------------------

def record_login_attempt(role: str, username: str, success: bool):
    with _connect() as conn:
        conn.execute(
            "INSERT INTO login_attempts (timestamp, role, username, success) VALUES (?, ?, ?, ?)",
            (datetime.datetime.now().isoformat(timespec="seconds"), role, username, int(success)),
        )
        conn.commit()


def count_recent_failed_logins(role: str, username: str, minutes: int) -> int:
    since = (datetime.datetime.now() - datetime.timedelta(minutes=minutes)).isoformat(timespec="seconds")
    with _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM login_attempts "
            "WHERE role = ? AND username = ? AND success = 0 AND timestamp >= ?",
            (role, username, since),
        ).fetchone()
        return row["n"] if row else 0
