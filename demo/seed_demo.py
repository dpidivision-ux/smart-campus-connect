"""Seed a demo database: admin, lecturer, six students, a tight weekly pool.

Demo passwords are GENERATED randomly per run and written to
demo/DEMO_CREDENTIALS.txt (gitignored). Nothing secret lives in this repo;
all demo people are synthetic.
"""
import os, secrets, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import auth, db

STUDENTS = [
    ("adaeze",  "Adaeze Okafor",   9, "CSC101"),
    ("chidi",   "Chidi Eze",       2, "PHY102"),
    ("ngozi",   "Ngozi Nnamdi",    7, "CSC101,PHY102"),
    ("emeka",   "Emeka Obi",       0, ""),
    ("fatima",  "Fatima Bello",    5, "CSC101"),
    ("tunde",   "Tunde Adeyemi",   8, "CSC101"),
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
    mk("lecturer", "lecturer", "Demo Lecturer (synthetic)")
    for uname, name, urgency, targets in STUDENTS:
        mk(uname, "student", name, urgency)
        with db.connect(path) as con:
            con.execute("UPDATE users SET exam_targets=? WHERE username=?", (targets, uname))

    with db.connect(path) as con:
        con.execute("UPDATE users SET need_bonus=1.0 WHERE username='fatima'")
    import datetime
    week = (datetime.date.today() - datetime.timedelta(days=datetime.date.today().weekday())).isoformat()
    with db.connect(path) as con:
        row = con.execute("SELECT id FROM users WHERE username='adaeze'").fetchone()
    if row:
        db.log_usage(path, row["id"], week, 45, "Downloading CSC 101 materials")

    # Publish two synthetic CSC101-W3 study materials through the same AI
    # pipeline the UI uses (offline fallback until a model endpoint is
    # configured. Seeding never calls an external provider), then record a few
    # library reads so the measured-impact panel has real demo counts.
    from app import ai_module
    with db.connect(path) as con:
        lecturer = con.execute("SELECT id FROM users WHERE username='lecturer'").fetchone()["id"]
        student_ids = {r["username"]: r["id"] for r in con.execute(
            "SELECT id, username FROM users WHERE role='student'")}
    if not db.list_materials(path):
        lecture = open(os.path.join(os.path.dirname(__file__), "lecture_csc101.txt"),
                       encoding="utf-8").read()
        jid1, _, _ = ai_module.submit_job(path, "summary", lecture, allow_model=False)
        job1 = ai_module.get_job(path, jid1)
        mid1 = db.add_material(path, "CSC101-W3 lecture summary (synthetic)",
                               "summary", job1["result"], job1["model"], lecturer,
                               course_tag="CSC101-W3")
        jid2, _, _ = ai_module.submit_job(path, "quiz", lecture, allow_model=False)
        job2 = ai_module.get_job(path, jid2)
        mid2 = db.add_material(path, "CSC101-W3 revision quiz (synthetic)",
                               "quiz", job2["result"], job2["model"], lecturer,
                               course_tag="CSC101-W3")
        for uname, mids in (("adaeze", (mid1, mid2)), ("tunde", (mid1,)),
                            ("ngozi", (mid1, mid2)), ("fatima", (mid2,))):
            for mid in mids:
                db.log_material_read(path, mid, student_ids[uname])

    out = os.path.join(os.path.dirname(__file__), "DEMO_CREDENTIALS.txt")
    with open(out, "w") as fh:
        fh.write("Synthetic demo logins (generated per seed run; demo data only)\n")
        for uname, pw, role in creds:
            fh.write(f"{role:9s} {uname:10s} {pw}\n")
    print(f"Seeded demo database at {path}; credentials in {out}")


if __name__ == "__main__":
    seed(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "campus.db"))
