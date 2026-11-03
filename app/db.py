"""SQLite persistence for Smart Campus Connect.

Offline-first by design: every write goes to the local database first,
so the system keeps working on unreliable campus connectivity.
"""
import sqlite3
import time
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('student','lecturer','admin')),
    full_name TEXT NOT NULL,
    exam_urgency INTEGER NOT NULL DEFAULT 0,   -- 0..10, higher = exam sooner
    need_bonus REAL NOT NULL DEFAULT 0,        -- documented extra need (0..2 shares)
    exam_targets TEXT NOT NULL DEFAULT '',     -- explicit course/exam IDs, e.g. "CSC101,PHY102"
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS weekly_pool (
    id INTEGER PRIMARY KEY CHECK(id = 1),
    total_minutes INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS allocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    week_start TEXT NOT NULL,
    minutes INTEGER NOT NULL,
    rationale TEXT NOT NULL,
    UNIQUE(user_id, week_start)
);
CREATE TABLE IF NOT EXISTS ai_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL CHECK(kind IN ('summary','quiz','condense')),
    source_text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','done','failed')),
    result TEXT,
    model TEXT,
    created_at REAL NOT NULL,
    finished_at REAL
);
CREATE TABLE IF NOT EXISTS usage_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    week_start TEXT NOT NULL,
    minutes INTEGER NOT NULL,
    note TEXT,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS materials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('summary','quiz','condense')),
    content TEXT NOT NULL,
    model TEXT,
    course_tag TEXT NOT NULL DEFAULT '',       -- explicit course/week ID, e.g. CSC101-W3
    created_by INTEGER NOT NULL REFERENCES users(id),
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS login_attempts (
    username TEXT PRIMARY KEY,
    failures INTEGER NOT NULL DEFAULT 0,
    locked_until REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS material_reads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id INTEGER NOT NULL REFERENCES materials(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS ai_cache (
    cache_key TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    result TEXT NOT NULL,
    model TEXT NOT NULL,
    created_at REAL NOT NULL
);
"""


@contextmanager
def connect(path):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init_db(path):
    with connect(path) as con:
        con.executescript(SCHEMA)
        cols = [r["name"] for r in con.execute("PRAGMA table_info(users)")]
        if "need_bonus" not in cols:
            con.execute("ALTER TABLE users ADD COLUMN need_bonus REAL NOT NULL DEFAULT 0")
        if "exam_targets" not in cols:
            con.execute("ALTER TABLE users ADD COLUMN exam_targets TEXT NOT NULL DEFAULT ''")
        mcols = [r["name"] for r in con.execute("PRAGMA table_info(materials)")]
        if "course_tag" not in mcols:
            con.execute("ALTER TABLE materials ADD COLUMN course_tag TEXT NOT NULL DEFAULT ''")
        jcols = [r["name"] for r in con.execute("PRAGMA table_info(ai_jobs)")]
        if "attempts" not in jcols:
            con.execute("ALTER TABLE ai_jobs ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0")
        if con.execute("SELECT COUNT(*) c FROM weekly_pool").fetchone()["c"] == 0:
            con.execute("INSERT INTO weekly_pool (id, total_minutes) VALUES (1, ?)", (6000,))


def set_pool(path, total_minutes):
    with connect(path) as con:
        con.execute("UPDATE weekly_pool SET total_minutes = ? WHERE id = 1", (total_minutes,))


def get_pool(path):
    with connect(path) as con:
        return con.execute("SELECT total_minutes FROM weekly_pool WHERE id = 1").fetchone()["total_minutes"]


def now():
    return time.time()


def log_usage(path, user_id, week_start, minutes, note=""):
    with connect(path) as con:
        con.execute(
            "INSERT INTO usage_sessions (user_id, week_start, minutes, note, created_at)"
            " VALUES (?,?,?,?,?)", (user_id, week_start, minutes, note, now()))


def usage_this_week(path, user_id, week_start):
    with connect(path) as con:
        r = con.execute(
            "SELECT COALESCE(SUM(minutes),0) AS m FROM usage_sessions WHERE user_id=? AND week_start=?",
            (user_id, week_start)).fetchone()
        return r["m"]


def usage_overview(path, week_start):
    with connect(path) as con:
        return [dict(r) for r in con.execute(
            "SELECT u.full_name, u.id, COALESCE(SUM(s.minutes),0) AS used "
            "FROM users u LEFT JOIN usage_sessions s ON s.user_id=u.id AND s.week_start=? "
            "WHERE u.role='student' GROUP BY u.id ORDER BY u.full_name", (week_start,))]


def add_material(path, title, kind, content, model, created_by, course_tag=""):
    with connect(path) as con:
        cur = con.execute(
            "INSERT INTO materials (title, kind, content, model, course_tag, created_by, created_at)"
            " VALUES (?,?,?,?,?,?,?)", (title, kind, content, model, course_tag, created_by, now()))
        return cur.lastrowid


def log_material_read(path, material_id, user_id):
    with connect(path) as con:
        con.execute(
            "INSERT INTO material_reads (material_id, user_id, created_at) VALUES (?,?,?)",
            (material_id, user_id, now()))


def material_read_stats(path):
    """Measured library usage: total reads, distinct readers, and the text
    bytes of the materials actually read (each read counted per open)."""
    with connect(path) as con:
        r = con.execute(
            "SELECT COUNT(*) AS reads, COUNT(DISTINCT user_id) AS readers FROM material_reads"
        ).fetchone()
        b = con.execute(
            "SELECT COALESCE(SUM(LENGTH(m.content)),0) AS bytes FROM material_reads rd"
            " JOIN materials m ON m.id = rd.material_id").fetchone()
    return {"library_reads": r["reads"], "distinct_readers": r["readers"],
            "read_text_bytes": b["bytes"]}


def list_materials_for_targets(path, targets, limit=6):
    """Materials whose course_tag matches any of the user's registered
    course/exam IDs (prefix match: CSC101 matches CSC101-W3)."""
    tags = [t.strip().upper() for t in targets.split(",") if t.strip()]
    if not tags:
        return []
    out = []
    for m in list_materials(path, limit=200):
        tag = (m.get("course_tag") or "").upper()
        if tag and any(tag.startswith(t) for t in tags):
            out.append(m)
        if len(out) >= limit:
            break
    return out


def list_materials(path, limit=50):
    with connect(path) as con:
        return [dict(r) for r in con.execute(
            "SELECT m.*, u.full_name AS author FROM materials m JOIN users u ON u.id=m.created_by"
            " ORDER BY m.id DESC LIMIT ?", (limit,))]


def get_material(path, material_id):
    with connect(path) as con:
        r = con.execute(
            "SELECT m.*, u.full_name AS author FROM materials m JOIN users u ON u.id=m.created_by"
            " WHERE m.id=?", (material_id,)).fetchone()
        return dict(r) if r else None
