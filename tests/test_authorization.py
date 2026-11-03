"""Role enforcement, CSRF protection, login lockout, durable pending jobs."""
import os, re, sys
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


def _csrf(client):
    html = client.get("/login").get_data(as_text=True)
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


def _login(client, u, p):
    tok = _csrf(client)
    return client.post("/login", data={"username": u, "password": p, "csrf": tok})


def test_csrf_required_on_post(tmp_path):
    app, path = _app(tmp_path)
    c = app.test_client()
    r = c.post("/login", data={"username": "adm", "password": "pw-admin"})
    assert r.status_code == 400
    c2 = app.test_client()
    _login(c2, "lec", "pw-lect")
    r = c2.post("/admin", data={"action": "set_pool", "total_minutes": "1"})
    assert r.status_code == 400
    assert db.get_pool(path) == 6000


def test_login_lockout_after_failures(tmp_path):
    app, path = _app(tmp_path)
    c = app.test_client()
    for _ in range(auth.MAX_FAILURES):
        _login(c, "adm", "wrong-password")
    assert auth.is_locked(path, "adm")
    # correct password is also refused while locked
    r = _login(c, "adm", "pw-admin")
    assert b"locked" in r.data.lower()
    assert b"Too many failed attempts" in r.data


def test_failed_attempt_counter_resets_on_success(tmp_path):
    app, path = _app(tmp_path)
    c = app.test_client()
    _login(c, "adm", "wrong")
    assert auth._lock_row(path, "adm")["failures"] == 1
    r = _login(c, "adm", "pw-admin")
    assert r.status_code == 302
    assert auth._lock_row(path, "adm")["failures"] == 0


def test_lecturer_cannot_change_pool(tmp_path):
    app, path = _app(tmp_path)
    c = app.test_client()
    _login(c, "lec", "pw-lect")
    tok = _csrf(c)
    r = c.post("/admin", data={"action": "set_pool", "total_minutes": "1", "csrf": tok})
    assert r.status_code == 403
    assert db.get_pool(path) == 6000


def test_lecturer_cannot_add_student_or_run_allocation(tmp_path):
    app, path = _app(tmp_path)
    c = app.test_client()
    _login(c, "lec", "pw-lect")
    tok = _csrf(c)
    r = c.post("/admin", data={"action": "add_student", "username": "x",
                               "password": "y", "full_name": "X", "csrf": tok})
    assert r.status_code == 403
    r = c.post("/admin", data={"action": "run_allocation", "csrf": tok})
    assert r.status_code == 403
    with db.connect(path) as con:
        assert con.execute("SELECT COUNT(*) c FROM users WHERE username='x'").fetchone()["c"] == 0


def test_admin_can_change_pool(tmp_path):
    app, path = _app(tmp_path)
    c = app.test_client()
    _login(c, "adm", "pw-admin")
    tok = _csrf(c)
    r = c.post("/admin", data={"action": "set_pool", "total_minutes": "1234", "csrf": tok})
    assert r.status_code == 302
    assert db.get_pool(path) == 1234


def test_lecturer_admin_page_hides_admin_cards(tmp_path):
    app, path = _app(tmp_path)
    c = app.test_client()
    _login(c, "lec", "pw-lect")
    html = c.get("/admin").get_data(as_text=True)
    assert "Weekly pool" not in html
    assert "Add a student" not in html
    assert "Measured usage" in html


def test_pending_job_honest_page_and_retry_button(tmp_path):
    app, path = _app(tmp_path)
    c = app.test_client()
    _login(c, "lec", "pw-lect")
    job_id, status, _ = ai_module.submit_job(path, "summary", "Some text. " * 30)
    assert status == "queued"
    html = c.get(f"/ai/{job_id}").get_data(as_text=True)
    assert "local extractive preview, not AI output" in html
    assert "Retry model now" in html
    assert "stays queued in the database and will upgrade" not in html
    # retry with no endpoint configured stays pending and does not count attempts
    assert ai_module.retry_job(path, job_id) == "queued"


def test_retry_success_completes_and_caches(tmp_path, monkeypatch):
    app, path = _app(tmp_path)
    monkeypatch.setattr(ai_module, "BASE_URL", "https://endpoint.invalid/v1")
    monkeypatch.setattr(ai_module, "DEFAULT_MODEL", "test-model")
    calls = {"n": 0}
    def fake_call(kind, text):
        calls["n"] += 1
        return "MODEL RESULT: key points"
    monkeypatch.setattr(ai_module, "_call_model", fake_call)
    job_id, status, result = ai_module.submit_job(path, "summary", "Unique text. " * 20)
    assert status == "done" and result.startswith("MODEL RESULT")
    assert calls["n"] == 1
    # successful result is cached: identical text now hits cache, no new call
    job_id2, status2, result2 = ai_module.submit_job(path, "summary", "Unique text. " * 20)
    assert result2.startswith("MODEL RESULT")
    assert ai_module.get_job(path, job_id2)["model"] == "cache"
    assert calls["n"] == 1
    assert ai_module.ai_stats(path)["live_calls"] == 1


def test_retry_failure_stays_queued(tmp_path, monkeypatch):
    app, path = _app(tmp_path)
    job_id, status, _ = ai_module.submit_job(path, "summary", "More text. " * 20)
    assert status == "queued"
    monkeypatch.setattr(ai_module, "BASE_URL", "https://endpoint.invalid/v1")
    def boom(kind, text):
        raise RuntimeError("endpoint down")
    monkeypatch.setattr(ai_module, "_call_model", boom)
    assert ai_module.retry_job(path, job_id) == "queued"
    job = ai_module.get_job(path, job_id)
    assert job["status"] == "queued" and job["attempts"] == 1
