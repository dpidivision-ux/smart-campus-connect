"""Role enforcement on administrator actions (server-side, not just hidden UI)
and kind-aware fallback labeling."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import ai_module, auth, create_app, db


def _app(tmp_path):
    path = str(tmp_path / "t.db")
    db.init_db(path)
    auth.create_user(path, "adm", "pw-admin", "admin", "Admin")
    auth.create_user(path, "lec", "pw-lect", "lecturer", "Lecturer")
    app = create_app(path)
    app.config["TESTING"] = True
    return app, path


def _login(client, u, p):
    return client.post("/login", data={"username": u, "password": p},
                       follow_redirects=False)


def test_lecturer_cannot_change_pool(tmp_path):
    app, path = _app(tmp_path)
    c = app.test_client()
    _login(c, "lec", "pw-lect")
    r = c.post("/admin", data={"action": "set_pool", "total_minutes": "1"})
    assert r.status_code == 403
    assert db.get_pool(path) == 6000  # unchanged


def test_lecturer_cannot_add_student_or_run_allocation(tmp_path):
    app, path = _app(tmp_path)
    c = app.test_client()
    _login(c, "lec", "pw-lect")
    r = c.post("/admin", data={"action": "add_student", "username": "x",
                               "password": "y", "full_name": "X"})
    assert r.status_code == 403
    r = c.post("/admin", data={"action": "run_allocation"})
    assert r.status_code == 403
    with db.connect(path) as con:
        assert con.execute("SELECT COUNT(*) c FROM users WHERE username='x'").fetchone()["c"] == 0


def test_admin_can_change_pool(tmp_path):
    app, path = _app(tmp_path)
    c = app.test_client()
    _login(c, "adm", "pw-admin")
    r = c.post("/admin", data={"action": "set_pool", "total_minutes": "1234"})
    assert r.status_code == 302
    assert db.get_pool(path) == 1234


def test_lecturer_admin_page_hides_admin_cards(tmp_path):
    app, path = _app(tmp_path)
    c = app.test_client()
    _login(c, "lec", "pw-lect")
    html = c.get("/admin").get_data(as_text=True)
    assert "Weekly pool" not in html
    assert "Add a student" not in html
    assert "Measured usage" in html  # lecturer still sees AI status/panels


def test_fallback_label_is_kind_aware(tmp_path):
    path = str(tmp_path / "t.db")
    db.init_db(path)
    _, _, quiz = ai_module.submit_job(path, "quiz", "Some lecture text. " * 40)
    assert "NOT generated quiz questions" in quiz
    assert "extractive summary" not in quiz
    _, _, summary = ai_module.submit_job(path, "summary", "Some lecture text. " * 40)
    assert "extractive summary" in summary


def test_fallback_job_completes_and_copy_is_honest(tmp_path):
    # Regression: fallback jobs finish immediately - UI must not claim they
    # "stay queued" or "upgrade" automatically.
    app, path = _app(tmp_path)
    c = app.test_client()
    _login(c, "lec", "pw-lect")
    job_id, status, _ = ai_module.submit_job(path, "summary", "Some text. " * 30)
    assert status == "done"
    html = c.get(f"/ai/{job_id}").get_data(as_text=True)
    assert "not AI output" in html
    assert "stays queued" not in html and "will upgrade" not in html
