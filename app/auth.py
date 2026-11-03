"""Role-based authentication (student / lecturer / admin).

Passwords are salted PBKDF2-HMAC-SHA256 hashes; sessions are Flask
server-side signed cookies. No third-party auth dependency - the system
must run on an isolated campus network.
"""
import hashlib
import os
import secrets

from flask import session

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


def authenticate(db_path, username, password):
    with db.connect(db_path) as con:
        row = con.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if row and verify_password(password, row["password_hash"]):
        session["user_id"] = row["id"]
        session["role"] = row["role"]
        session["full_name"] = row["full_name"]
        session["exam_targets"] = row["exam_targets"] if "exam_targets" in row.keys() else ""
        return True
    return False


def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    return {"id": uid, "role": session.get("role"), "full_name": session.get("full_name"),
            "exam_targets": session.get("exam_targets", "")}


def logout():
    session.clear()
