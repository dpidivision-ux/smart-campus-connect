import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import ai_module, db

LECTURE = ("Photosynthesis converts light energy into chemical energy in plants. "
           "Chlorophyll in the chloroplasts absorbs sunlight, mainly blue and red wavelengths. "
           "The light-dependent reactions split water molecules, releasing oxygen as a byproduct. "
           "ATP and NADPH produced in these reactions power the Calvin cycle. "
           "The Calvin cycle fixes carbon dioxide into glucose through a series of enzyme steps. "
           "Stomata regulate gas exchange and water loss from the leaf surface. "
           "Without sufficient light, the rate of photosynthesis falls sharply. "
           "Farmers in Nsukka consider photosynthetic efficiency when choosing planting density.")


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db.init_db(path)
    return path


def test_offline_fallback_queues_and_labels(tmp_path=None):
    path = _fresh_db()
    # no endpoint configured in test env -> fallback path
    job_id, status, result = ai_module.submit_job(path, "summary", LECTURE)
    assert status == "queued"
    assert "OFFLINE PREVIEW - NOT AI OUTPUT" in result
    job = ai_module.get_job(path, job_id)
    assert job["model"] == "offline-fallback"
    # preview is never cached: a second identical request must not hit cache
    assert ai_module.ai_stats(path)["cache_hits"] == 0


def test_fallback_picks_content_sentences():
    out = ai_module._extractive_fallback(LECTURE)
    assert "photosynthesis" in out.lower() or "chlorophyll" in out.lower()


def test_quiz_prompt_shape():
    path = _fresh_db()
    job_id, status, result = ai_module.submit_job(path, "quiz", LECTURE)
    assert status == "queued" and result
    assert "NOT generated quiz questions" in result


def test_cache_is_scoped_to_model_and_endpoint(tmp_path, monkeypatch):
    path = str(tmp_path / "cache-model.db")
    db.init_db(path)
    calls = []
    monkeypatch.setattr(ai_module, "BASE_URL", "https://provider-a.invalid/v1")
    monkeypatch.setattr(ai_module, "DEFAULT_MODEL", "model-a")
    def fake_call(kind, text):
        calls.append((ai_module.BASE_URL, ai_module.DEFAULT_MODEL))
        return "result from " + ai_module.DEFAULT_MODEL
    monkeypatch.setattr(ai_module, "_call_model", fake_call)
    assert ai_module.submit_job(path, "summary", LECTURE)[2] == "result from model-a"
    assert ai_module.submit_job(path, "summary", LECTURE)[2] == "result from model-a"
    assert len(calls) == 1
    monkeypatch.setattr(ai_module, "DEFAULT_MODEL", "model-b")
    assert ai_module.submit_job(path, "summary", LECTURE)[2] == "result from model-b"
    assert len(calls) == 2
    monkeypatch.setattr(ai_module, "BASE_URL", "https://provider-b.invalid/v1")
    ai_module.submit_job(path, "summary", LECTURE)
    assert len(calls) == 3


def test_configured_endpoint_is_not_presented_as_verified_live(tmp_path, monkeypatch):
    from app import create_app, auth
    path = str(tmp_path / "labels.db")
    app = create_app(path)
    app.config["TESTING"] = True
    auth.create_user(path, "labeluser", "testpw", "student", "Synthetic Student")
    monkeypatch.setattr(ai_module, "BASE_URL", "https://unreachable.invalid/v1")
    monkeypatch.setattr(ai_module, "DEFAULT_MODEL", "untested-model")
    client = app.test_client()
    with client.session_transaction() as session:
        with db.connect(path) as con:
            session["user_id"] = con.execute("SELECT id FROM users WHERE username='labeluser'").fetchone()["id"]
    html = client.get("/dashboard").get_data(as_text=True)
    assert "configured: untested-model" in html
    assert "live: untested-model" not in html
