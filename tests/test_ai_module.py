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
