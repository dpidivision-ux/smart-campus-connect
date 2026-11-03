import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import ai_module, db


def _fresh_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db.init_db(path)
    return path


def test_usage_logging_and_overview():
    path = _fresh_db()
    from app import auth
    uid = auth.create_user(path, "stu1", "pw", "student", "Student One", 5)
    db.log_usage(path, uid, "2026-11-02", 30, "reading")
    db.log_usage(path, uid, "2026-11-02", 25, "quiz")
    assert db.usage_this_week(path, uid, "2026-11-02") == 55
    ov = db.usage_overview(path, "2026-11-02")
    assert ov[0]["used"] == 55 and ov[0]["full_name"] == "Student One"


def test_materials_publish_and_read():
    path = _fresh_db()
    from app import auth
    uid = auth.create_user(path, "lec1", "pw", "lecturer", "Lecturer One")
    mid = db.add_material(path, "CSC 101 summary", "summary", "- point A\n- point B", "cache", uid)
    m = db.get_material(path, mid)
    assert m["title"] == "CSC 101 summary" and m["author"] == "Lecturer One"
    assert db.list_materials(path)[0]["id"] == mid


def test_condense_kind_and_stats():
    path = _fresh_db()
    article = "The university senate met on Tuesday. " * 30
    job_id, status, result = ai_module.submit_job(path, "condense", article)
    assert status == "done"
    stats = ai_module.ai_stats(path)
    # offline in tests: counted as fallback, live_calls zero
    assert stats["live_calls"] == 0
    assert stats["fallback_served"] >= 1


def test_cache_hit_skips_model():
    path = _fresh_db()
    key_text = "Unique cache test sentence about Nsukka campus life and exams."
    # seed cache directly as a prior live result
    from app import ai_module as am
    k = am._cache_key("summary", key_text)
    with db.connect(path) as con:
        con.execute("INSERT INTO ai_cache (cache_key, kind, result, model, created_at) VALUES (?,?,?,?,?)",
                    (k, "summary", "- cached bullets", "muse-spark-open", db.now()))
    job_id, status, result = am.submit_job(path, "summary", key_text)
    assert result == "- cached bullets"
    assert am.get_job(path, job_id)["model"] == "cache"
    assert am.ai_stats(path)["cache_hits"] >= 1
