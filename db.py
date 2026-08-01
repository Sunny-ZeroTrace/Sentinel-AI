"""
Sentinel AI — SQLite storage layer.
Single file DB. Tables: cases, settings, api_keys, email_threads,
face_index, correlation_edges, chat_history.
All access goes through this module — nothing else should open the
sqlite file directly, so schema changes stay in one place.
"""
import sqlite3
import json
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from config import get_data_root, DB_FILENAME, ensure_dirs


def db_path() -> Path:
    root = get_data_root()
    ensure_dirs(root)
    return root / DB_FILENAME


@contextmanager
def get_conn():
    conn = sqlite3.connect(str(db_path()), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS api_keys (
                id TEXT PRIMARY KEY,
                provider TEXT NOT NULL,      -- 'gemini' or 'groq'
                label TEXT,
                key_value TEXT NOT NULL,
                priority INTEGER DEFAULT 100, -- lower = tried first
                is_active INTEGER DEFAULT 1,
                last_error TEXT,
                last_error_at REAL,
                created_at REAL
            );

            CREATE TABLE IF NOT EXISTS cases (
                id TEXT PRIMARY KEY,
                title TEXT,
                status TEXT DEFAULT 'active',   -- active/pending/closed
                victim_name TEXT,
                location TEXT,
                incident_datetime TEXT,
                description TEXT,
                assigned_officer TEXT,
                priority TEXT DEFAULT 'unassessed',
                risk_score REAL,
                risk_breakdown TEXT,            -- JSON
                custom_root TEXT,               -- user-chosen folder location, or NULL for default
                created_at REAL,
                updated_at REAL
            );

            CREATE TABLE IF NOT EXISTS email_threads (
                id TEXT PRIMARY KEY,
                case_id TEXT NOT NULL,
                department_label TEXT,
                department_email TEXT,
                gmail_thread_id TEXT,
                subject TEXT,
                status TEXT DEFAULT 'awaiting_reply', -- awaiting_reply/replied
                last_sent_at REAL,
                created_at REAL,
                FOREIGN KEY (case_id) REFERENCES cases(id)
            );

            CREATE TABLE IF NOT EXISTS department_directory (
                id TEXT PRIMARY KEY,
                label TEXT NOT NULL,           -- e.g. 'Police Station - Jamshedpur'
                email TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS face_index (
                id TEXT PRIMARY KEY,
                encoding TEXT NOT NULL,        -- JSON list of 128 floats
                name_tag TEXT,                 -- filled in once identified
                first_seen_case_id TEXT,
                source_image_path TEXT,
                created_at REAL
            );

            CREATE TABLE IF NOT EXISTS face_sightings (
                id TEXT PRIMARY KEY,
                face_id TEXT NOT NULL,
                case_id TEXT NOT NULL,
                image_path TEXT,
                created_at REAL,
                FOREIGN KEY (face_id) REFERENCES face_index(id)
            );

            CREATE TABLE IF NOT EXISTS correlation_edges (
                id TEXT PRIMARY KEY,
                case_id_a TEXT NOT NULL,
                case_id_b TEXT NOT NULL,
                entity_type TEXT,   -- 'face' | 'email' | 'phone' | 'device'
                entity_value TEXT,
                created_at REAL
            );

            CREATE TABLE IF NOT EXISTS chat_history (
                id TEXT PRIMARY KEY,
                case_id TEXT,       -- NULL means global search, not case chat
                role TEXT,          -- 'user' | 'assistant'
                content TEXT,
                created_at REAL
            );

            CREATE TABLE IF NOT EXISTS update_log (
                id TEXT PRIMARY KEY,
                case_id TEXT NOT NULL,
                entry TEXT NOT NULL,
                created_at REAL
            );
            """
        )
        # Migration: older databases created before custom_root existed
        # won't have this column yet — add it if missing, ignore if present.
        try:
            conn.execute("ALTER TABLE cases ADD COLUMN custom_root TEXT")
        except sqlite3.OperationalError:
            pass  # column already exists


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def now() -> float:
    return time.time()


# ---------- settings ----------

def get_setting(key: str, default=None):
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except (json.JSONDecodeError, TypeError):
            return row["value"]


def set_setting(key: str, value) -> None:
    v = json.dumps(value) if not isinstance(value, str) else value
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, v),
        )


# ---------- api keys ----------

def add_api_key(provider: str, key_value: str, label: str = "", priority: int = 100) -> str:
    key_id = new_id()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO api_keys (id, provider, label, key_value, priority, is_active, created_at) "
            "VALUES (?, ?, ?, ?, ?, 1, ?)",
            (key_id, provider, label, key_value, priority, now()),
        )
    return key_id


def list_api_keys(provider: str = None, active_only: bool = True):
    with get_conn() as conn:
        q = "SELECT * FROM api_keys WHERE 1=1"
        params = []
        if provider:
            q += " AND provider=?"
            params.append(provider)
        if active_only:
            q += " AND is_active=1"
        q += " ORDER BY priority ASC, created_at ASC"
        return [dict(r) for r in conn.execute(q, params).fetchall()]


def mark_key_error(key_id: str, error_msg: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE api_keys SET last_error=?, last_error_at=? WHERE id=?",
            (error_msg, now(), key_id),
        )


def deactivate_key(key_id: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE api_keys SET is_active=0 WHERE id=?", (key_id,))


# ---------- cases ----------

def create_case(title, victim_name="", location="", incident_datetime="",
                 description="", assigned_officer="", priority="unassessed",
                 case_id: str = None, custom_root: str = None) -> str:
    cid = case_id or new_id()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO cases (id, title, status, victim_name, location, "
            "incident_datetime, description, assigned_officer, priority, "
            "custom_root, created_at, updated_at) "
            "VALUES (?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (cid, title, victim_name, location, incident_datetime, description,
             assigned_officer, priority, custom_root, now(), now()),
        )
    return cid


def update_case(case_id: str, **fields) -> None:
    if not fields:
        return
    fields["updated_at"] = now()
    cols = ", ".join(f"{k}=?" for k in fields)
    with get_conn() as conn:
        conn.execute(f"UPDATE cases SET {cols} WHERE id=?", (*fields.values(), case_id))


def get_case(case_id: str):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
        return dict(row) if row else None


def list_cases(status: str = None):
    with get_conn() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM cases WHERE status=? ORDER BY updated_at DESC", (status,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM cases ORDER BY updated_at DESC").fetchall()
        return [dict(r) for r in rows]


def delete_case_db_rows(case_id: str) -> None:
    """Removes every database row referencing this case: sightings,
    correlation edges, email threads, chat history, update log, and the
    case row itself. Orphaned face_index rows (faces with zero remaining
    sightings anywhere after this) are also cleaned up. Does NOT touch
    the filesystem — see server.py's delete endpoint for that half."""
    with get_conn() as conn:
        sighting_face_ids = [
            r["face_id"] for r in conn.execute(
                "SELECT DISTINCT face_id FROM face_sightings WHERE case_id=?", (case_id,)
            ).fetchall()
        ]
        conn.execute("DELETE FROM face_sightings WHERE case_id=?", (case_id,))
        conn.execute(
            "DELETE FROM correlation_edges WHERE case_id_a=? OR case_id_b=?",
            (case_id, case_id),
        )
        conn.execute("DELETE FROM email_threads WHERE case_id=?", (case_id,))
        conn.execute("DELETE FROM chat_history WHERE case_id=?", (case_id,))
        conn.execute("DELETE FROM update_log WHERE case_id=?", (case_id,))
        conn.execute("DELETE FROM cases WHERE id=?", (case_id,))

        for face_id in sighting_face_ids:
            remaining = conn.execute(
                "SELECT COUNT(*) as c FROM face_sightings WHERE face_id=?", (face_id,)
            ).fetchone()["c"]
            if remaining == 0:
                conn.execute("DELETE FROM face_index WHERE id=?", (face_id,))


# ---------- department directory ----------

def add_department(label: str, email: str) -> str:
    did = new_id()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO department_directory (id, label, email) VALUES (?, ?, ?)",
            (did, label, email),
        )
    return did


def list_departments():
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM department_directory ORDER BY label ASC"
        ).fetchall()]


# ---------- email threads ----------

def create_email_thread(case_id, department_label, department_email,
                         gmail_thread_id, subject) -> str:
    tid = new_id()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO email_threads (id, case_id, department_label, "
            "department_email, gmail_thread_id, subject, status, last_sent_at, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'awaiting_reply', ?, ?)",
            (tid, case_id, department_label, department_email, gmail_thread_id,
             subject, now(), now()),
        )
    return tid


def list_awaiting_threads():
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM email_threads WHERE status='awaiting_reply'"
        ).fetchall()]


def mark_thread_replied(thread_id: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE email_threads SET status='replied' WHERE id=?", (thread_id,))


def touch_thread_sent(thread_id: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE email_threads SET last_sent_at=? WHERE id=?", (now(), thread_id))


def list_threads_for_case(case_id: str):
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM email_threads WHERE case_id=? ORDER BY created_at DESC", (case_id,)
        ).fetchall()]


# ---------- faces ----------

def add_face(encoding_list, first_seen_case_id, source_image_path) -> str:
    fid = new_id()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO face_index (id, encoding, first_seen_case_id, "
            "source_image_path, created_at) VALUES (?, ?, ?, ?, ?)",
            (fid, json.dumps(encoding_list), first_seen_case_id, source_image_path, now()),
        )
    return fid


def all_faces():
    with get_conn() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM face_index").fetchall()]


def add_face_sighting(face_id, case_id, image_path) -> str:
    sid = new_id()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO face_sightings (id, face_id, case_id, image_path, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (sid, face_id, case_id, image_path, now()),
        )
    return sid


def tag_face(face_id: str, name_tag: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE face_index SET name_tag=? WHERE id=?", (name_tag, face_id))


def sightings_for_face(face_id: str):
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM face_sightings WHERE face_id=?", (face_id,)
        ).fetchall()]


# ---------- correlation ----------

def add_correlation_edge(case_id_a, case_id_b, entity_type, entity_value) -> str:
    eid = new_id()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO correlation_edges (id, case_id_a, case_id_b, entity_type, "
            "entity_value, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (eid, case_id_a, case_id_b, entity_type, entity_value, now()),
        )
    return eid


def all_correlation_edges():
    with get_conn() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM correlation_edges").fetchall()]


# ---------- chat ----------

def add_chat_message(case_id, role, content) -> str:
    mid = new_id()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO chat_history (id, case_id, role, content, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (mid, case_id, role, content, now()),
        )
    return mid


def chat_history_for_case(case_id):
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM chat_history WHERE case_id=? ORDER BY created_at ASC", (case_id,)
        ).fetchall()]


# ---------- update log ----------

def append_update_log(case_id: str, entry: str) -> str:
    uid = new_id()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO update_log (id, case_id, entry, created_at) VALUES (?, ?, ?, ?)",
            (uid, case_id, entry, now()),
        )
    return uid


def update_log_for_case(case_id: str):
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM update_log WHERE case_id=? ORDER BY created_at ASC", (case_id,)
        ).fetchall()]
