"""Seed a demo database: admin, lecturer, six students, a tight weekly pool.

Demo passwords are GENERATED randomly per run and written to
demo/DEMO_CREDENTIALS.txt (gitignored). Nothing secret lives in this repo;
all demo people are synthetic.
"""
import os, secrets, sys
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
    creds = []

    def mk(username, role, full_name, urgency=0):
        pw = secrets.token_urlsafe(9)
        try:
            auth.create_user(path, username, pw, role, full_name, urgency)
            creds.append((username, pw, role))
        except Exception:
            pass  # already seeded

    mk("admin", "admin", "Portal Administrator")
    mk("lecturer", "lecturer", "A. Razgour")
    for uname, name, urgency in STUDENTS:
        mk(uname, "student", name, urgency)

    with db.connect(path) as con:
        con.execute("UPDATE users SET need_bonus=1.0 WHERE username='fatima'")
    import datetime
    week = (datetime.date.today() - datetime.timedelta(days=datetime.date.today().weekday())).isoformat()
    with db.connect(path) as con:
        row = con.execute("SELECT id FROM users WHERE username='adaeze'").fetchone()
    if row:
        db.log_usage(path, row["id"], week, 45, "Downloading CSC 101 materials")

    out = os.path.join(os.path.dirname(__file__), "DEMO_CREDENTIALS.txt")
    with open(out, "w") as fh:
        fh.write("Synthetic demo logins (generated per seed run; demo data only)\n")
        for uname, pw, role in creds:
            fh.write(f"{role:9s} {uname:10s} {pw}\n")
    print(f"Seeded demo database at {path}; credentials in {out}")


if __name__ == "__main__":
    seed(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "campus.db"))
