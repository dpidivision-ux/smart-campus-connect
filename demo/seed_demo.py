"""Seed a demo database: admin, lecturer, six students, a tight weekly pool."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import auth, db

STUDENTS = [
    ("adaeze",  "Adaeze Okafor",   9),
    ("chidi",   "Chidi Eze",       2),
    ("ngozi",   "Ngozi Nnamdi",    7),
    ("emeka",   "Emeka Obi",       0),
    ("fatima",  "Fatima Bello",    5),
    ("tunde",   "Tunde Adeyemi",   8),
]


def seed(path):
    db.init_db(path)
    db.set_pool(path, 3000)  # deliberately scarce: 6 students, 3000 min/week
    try:
        auth.create_user(path, "admin", "admin-demo-2026", "admin", "Portal Administrator")
        auth.create_user(path, "lecturer", "lecturer-demo-2026", "lecturer", "A. Razgour")
    except Exception:
        pass  # already seeded
    for uname, name, urgency in STUDENTS:
        try:
            auth.create_user(path, uname, f"{uname}-demo-2026", "student", name, urgency)
        except Exception:
            pass
    # documented extra need for one student; some logged usage for the demo
    with db.connect(path) as con:
        con.execute("UPDATE users SET need_bonus=1.0 WHERE username='fatima'")
    import datetime
    week = (datetime.date.today() - datetime.timedelta(days=datetime.date.today().weekday())).isoformat()
    with db.connect(path) as con:
        uid = con.execute("SELECT id FROM users WHERE username='adaeze'").fetchone()["id"]
    db.log_usage(path, uid, week, 45, "Downloading CSC 101 materials")
    print(f"Seeded demo database at {path}")


if __name__ == "__main__":
    seed(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "campus.db"))
