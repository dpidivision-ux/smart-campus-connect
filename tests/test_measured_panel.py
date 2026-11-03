"""Measured-impact panel: read tracking, precise stats, rubric quality check,
and explicit course/exam-ID targeting."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import ai_module, auth, db


def _fresh(tmp_path):
    path = str(tmp_path / "t.db")
    db.init_db(path)
    lec = auth.create_user(path, "lec", "x", "lecturer", "Demo Lecturer (synthetic)")
    s1 = auth.create_user(path, "st1", "x", "student", "Student One")
    s2 = auth.create_user(path, "st2", "x", "student", "Student Two")
    return path, lec, s1, s2


def test_read_tracking_and_stats(tmp_path):
    path, lec, s1, s2 = _fresh(tmp_path)
    mid = db.add_material(path, "M1", "summary", "abcd" * 100, "offline-fallback", lec,
                          course_tag="CSC101-W3")
    db.log_material_read(path, mid, s1)
    db.log_material_read(path, mid, s1)   # same reader twice: 2 reads, 1 distinct
    db.log_material_read(path, mid, s2)
    st = db.material_read_stats(path)
    assert st["library_reads"] == 3
    assert st["distinct_readers"] == 2
    assert st["read_text_bytes"] == 3 * 400


def test_stats_estimate_is_reads_bytes(tmp_path):
    path, lec, s1, _ = _fresh(tmp_path)
    mid = db.add_material(path, "M1", "summary", "x" * 1000, "offline-fallback", lec)
    db.log_material_read(path, mid, s1)
    stats = ai_module.ai_stats(path)
    assert stats["estimated_avoided_fetch_bytes"] == 1000
    assert stats["library_reads"] == 1
    assert stats["live_calls"] == 0  # nothing recorded unless a provider call happened


def test_concept_coverage_rubric():
    found, missing = ai_module.concept_coverage(
        "Binary search takes O(log n) time. A stack is last-in-first-out.")
    assert "binary search" in found and "stack" in found
    assert "merge sort" in missing
    assert len(found) + len(missing) == len(ai_module.CSC101_W3_KEY_CONCEPTS)


def test_quality_check_marks_model_pending_without_endpoint():
    q = ai_module.quality_check()
    assert q["model"] is None                      # never substituted by fallback
    assert len(q["fallback"]["found"]) >= 1        # fallback side is real output


def test_targeted_materials_prefix_match(tmp_path):
    path, lec, *_ = _fresh(tmp_path)
    db.add_material(path, "W3", "summary", "c", "offline-fallback", lec, course_tag="CSC101-W3")
    db.add_material(path, "W4", "summary", "c", "offline-fallback", lec, course_tag="CSC101-W4")
    db.add_material(path, "PHY", "summary", "c", "offline-fallback", lec, course_tag="PHY102-W1")
    db.add_material(path, "untagged", "summary", "c", "offline-fallback", lec)
    got = {m["title"] for m in db.list_materials_for_targets(path, "CSC101")}
    assert got == {"W3", "W4"}
    assert {m["title"] for m in db.list_materials_for_targets(path, "PHY102")} == {"PHY"}
    assert db.list_materials_for_targets(path, "") == []


def test_utf8_bytes_and_queued_fallback_are_counted(tmp_path, monkeypatch):
    path, lec, s1, _ = _fresh(tmp_path)
    text = "שלום עולם. This sentence has enough useful words for extraction."
    monkeypatch.setattr(ai_module, "BASE_URL", "")
    jid, status, preview = ai_module.submit_job(path, "summary", text)
    assert status == "queued"
    st = ai_module.ai_stats(path)
    assert st["fallback_served"] == 1
    assert st["source_text_bytes"] == len(text.encode("utf-8"))
    assert st["output_text_bytes"] == len(preview.encode("utf-8"))
    mid = db.add_material(path, "Unicode", "summary", text, "demo", lec)
    db.log_material_read(path, mid, s1)
    assert db.material_read_stats(path)["read_text_bytes"] == len(text.encode("utf-8"))


def test_quality_panel_never_calls_provider(tmp_path, monkeypatch):
    path, *_ = _fresh(tmp_path)
    monkeypatch.setattr(ai_module, "BASE_URL", "https://not-called.invalid")
    calls = []
    def forbidden(*args):
        calls.append(args)
        raise AssertionError("Admin quality panel must never call provider")
    monkeypatch.setattr(ai_module, "_call_model", forbidden)
    assert ai_module.quality_check(path)["model"] is None
    source = open(ai_module.DEMO_LECTURE_PATH, encoding="utf-8").read()
    with db.connect(path) as con:
        con.execute("INSERT INTO ai_cache (cache_key,kind,result,model,created_at) VALUES (?,?,?,?,?)",
                    (ai_module._cache_key("summary",source),"summary","Binary search uses O(log n).",ai_module.DEFAULT_MODEL,db.now()))
    assert "binary search" in ai_module.quality_check(path)["model"]["found"]
    assert calls == []


def test_seed_explicitly_avoids_model(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_module, "BASE_URL", "https://not-called.invalid")
    calls = []
    def forbidden(*args):
        calls.append(args)
        raise AssertionError("Seeding must not call provider")
    monkeypatch.setattr(ai_module, "_call_model", forbidden)
    # Test submit policy without writing the real demo credential file.
    path, *_ = _fresh(tmp_path)
    assert ai_module.submit_job(path, "summary", "Demo sample.", allow_model=False)[1] == "queued"
    assert calls == []


def test_admin_get_never_calls_provider(tmp_path, monkeypatch):
    from app import create_app
    import re
    path, *_ = _fresh(tmp_path)
    auth.create_user(path, "a", "p", "admin", "Admin")
    monkeypatch.setattr(ai_module, "BASE_URL", "https://not-called.invalid")
    calls = []
    def forbidden(*args):
        calls.append(args)
        raise AssertionError("Admin GET must not call provider")
    monkeypatch.setattr(ai_module, "_call_model", forbidden)
    app = create_app(path); app.config["TESTING"] = True
    c = app.test_client()
    token = re.search(r'name="csrf" value="([^"]+)"', c.get("/login").get_data(as_text=True)).group(1)
    c.post("/login", data={"username":"a","password":"p","csrf":token})
    assert c.get("/admin").status_code == 200
    assert ai_module.ai_stats(path)["live_calls"] == 0
    assert calls == []
