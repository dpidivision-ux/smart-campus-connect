"""Role-based authentication (student / lecturer / admin).

Passwords are salted PBKDF2-HMAC-SHA256 hashes; sessions are Flask
signed client-side cookies. No third-party auth dependency - the system
must run on an isolated campus network.
"""
import hashlib
import os
import secrets

from flask import request, session

from . import db

ITERATIONS = 120_000


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), ITERATIONS)
    return f"{salt}${digest.hex()}"


def verify_password(password, stored):
    try:
        salt, hexdigest = stored.split("$", 1)
    except ValueError:
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), ITERATIONS)
    return secrets.compare_digest(candidate.hex(), hexdigest)


def create_user(db_path, username, password, role, full_name, exam_urgency=0):
    with db.connect(db_path) as con:
        cur = con.execute(
            "INSERT INTO users (username, password_hash, role, full_name, exam_urgency, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (username, hash_password(password), role, full_name, exam_urgency, db.now()))
        return cur.lastrowid


MAX_FAILURES = 5
LOCK_SECONDS = 300


def _lock_row(db_path, username):
    with db.connect(db_path) as con:
        row = con.execute("SELECT failures, locked_until FROM login_attempts WHERE username=?",
                          (username,)).fetchone()
        return dict(row) if row else {"failures": 0, "locked_until": 0}


def is_locked(db_path, username):
    return _lock_row(db_path, username)["locked_until"] > db.now()


def _record_failure(db_path, username):
    with db.connect(db_path) as con:
        row = con.execute("SELECT failures FROM login_attempts WHERE username=?",
                          (username,)).fetchone()
        failures = (row["failures"] if row else 0) + 1
        locked = db.now() + LOCK_SECONDS if failures >= MAX_FAILURES else 0
        con.execute(
            "INSERT INTO login_attempts (username, failures, locked_until) VALUES (?,?,?)"
            " ON CONFLICT(username) DO UPDATE SET failures=excluded.failures,"
            " locked_until=excluded.locked_until", (username, failures, locked))


def _clear_failures(db_path, username):
    with db.connect(db_path) as con:
        con.execute("DELETE FROM login_attempts WHERE username=?", (username,))


def authenticate(db_path, username, password):
    if is_locked(db_path, username):
        return False
    with db.connect(db_path) as con:
        row = con.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if row and verify_password(password, row["password_hash"]):
        _clear_failures(db_path, username)
        session["user_id"] = row["id"]
        session["role"] = row["role"]
        session["full_name"] = row["full_name"]
        session["exam_targets"] = row["exam_targets"] if "exam_targets" in row.keys() else ""
        return True
    _record_failure(db_path, username)
    return False


def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    return {"id": uid, "role": session.get("role"), "full_name": session.get("full_name"),
            "exam_targets": session.get("exam_targets", "")}


def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(24)
    return session["_csrf"]


def csrf_valid():
    sent = request.form.get("csrf", "")
    tok = session.get("_csrf")
    return bool(sent) and bool(tok) and secrets.compare_digest(sent, tok)


def logout():
    session.clear()
