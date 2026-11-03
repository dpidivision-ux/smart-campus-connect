"""Offline-first AI module: lecture summaries and quiz generation.

Built for Meta's open-weight models (Muse Spark Open / Muse Glimmer),
served through any OpenAI-compatible endpoint:

  * Meta Model API            (Muse Spark series)
  * a partner endpoint        (Baseten / Modal / Fireworks hosting muse-spark-open)
  * a local server            (Muse Glimmer on a campus PC via llama.cpp / LM Studio)

The endpoint is configuration, not code: set AI_BASE_URL, AI_API_KEY,
AI_MODEL. No endpoint configured or unreachable -> jobs stay QUEUED in
the local database and results are served from cache; a deterministic
extractive fallback (no model) keeps the feature usable until the
model call succeeds. That fallback never claims to be model output.
"""
import hashlib
import json
import os
import re
import time

import requests

from . import db

DEFAULT_MODEL = os.environ.get("AI_MODEL", "meta-models/muse-spark-open-1026")
DEMO_LECTURE_PATH = os.environ.get(
    "DEMO_LECTURE_PATH",
    os.path.join(os.path.dirname(__file__), "..", "demo", "lecture_csc101.txt"))
BASE_URL = os.environ.get("AI_BASE_URL", "")          # e.g. https://api.baseten.co/v1
API_KEY = os.environ.get("AI_API_KEY", "")
TIMEOUT = float(os.environ.get("AI_TIMEOUT", "60"))

SUMMARY_PROMPT = (
    "You are helping Nigerian university students with very limited internet. "
    "Summarize the lecture notes below in at most 150 words, plain language, "
    "as 5 bullet points a student can study offline. Lecture notes:\n\n%s"
)
CONDENSE_PROMPT = (
    "A student in Nigeria pays for scarce internet bandwidth. Condense the web "
    "article below to the shortest version that keeps every key fact, in plain "
    "language, at most 120 words. Article:\n\n%s"
)
QUIZ_PROMPT = (
    "Create exactly 5 multiple-choice revision questions from the lecture notes "
    "below. Format each as: Q: ... A) ... B) ... C) ... D) ... Answer: X. "
    "Keep language simple. Lecture notes:\n\n%s"
)


def _cache_key(kind, text):
    return hashlib.sha256(f"{kind}:{text}".encode()).hexdigest()


def endpoint_configured():
    return bool(BASE_URL)


def _call_model(kind, text):
    prompts = {"summary": SUMMARY_PROMPT, "quiz": QUIZ_PROMPT, "condense": CONDENSE_PROMPT}
    prompt = prompts[kind] % text[:12000]
    resp = requests.post(
        BASE_URL.rstrip("/") + "/chat/completions",
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
        json={"model": DEFAULT_MODEL,
              "messages": [{"role": "user", "content": prompt}],
              "temperature": 0.3,
              "max_tokens": 900},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _extractive_fallback(text, max_sentences=5):
    """Deterministic no-model fallback: pick the most informative sentences.

    Frequency-based extraction - deliberately simple, clearly labeled in the
    UI as the offline fallback, never presented as model output.
    """
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    words = re.findall(r"[a-z]{4,}", text.lower())
    freq = {}
    for w in words:
        freq[w] = freq.get(w, 0) + 1
    scored = sorted(
        ((sum(freq.get(w, 0) for w in re.findall(r"[a-z]{4,}", s.lower())), i, s)
         for i, s in enumerate(sentences) if len(s.split()) >= 6),
        reverse=True,
    )
    picked = sorted(scored[:max_sentences], key=lambda t: t[1])
    return "\n".join("- " + s.strip() for _, _, s in picked) or "- (no content)"


def submit_job(db_path, kind, source_text):
    """Queue a summary/quiz job; returns (job_id, status, result_or_none)."""
    key = _cache_key(kind, source_text)
    with db.connect(db_path) as con:
        hit = con.execute("SELECT result FROM ai_cache WHERE cache_key = ?", (key,)).fetchone()
        if hit:
            cur = con.execute(
                "INSERT INTO ai_jobs (kind, source_text, status, result, model, created_at, finished_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (kind, source_text, "done", hit["result"], "cache", db.now(), db.now()))
            return cur.lastrowid, "done", hit["result"]
        cur = con.execute(
            "INSERT INTO ai_jobs (kind, source_text, status, created_at) VALUES (?,?,?,?)",
            (kind, source_text, "queued", db.now()))
        job_id = cur.lastrowid

    result, model = None, None
    if endpoint_configured():
        try:
            result = _call_model(kind, source_text)
            model = DEFAULT_MODEL
        except Exception:
            result = None
    if result is None:
        # Offline or endpoint failure: deterministic fallback, clearly labeled
        # per task type - the quiz fallback is an excerpt for self-testing,
        # never implied to be generated questions.
        headers = {
            "summary": ("OFFLINE FALLBACK (no model call succeeded yet; this extractive "
                        "summary is generated locally without AI):"),
            "condense": ("OFFLINE FALLBACK (no model call succeeded yet; this extractive "
                         "condensation is generated locally without AI):"),
            "quiz": ("OFFLINE FALLBACK (no model call succeeded yet; these key sentences are "
                     "extracted locally without AI for self-testing - they are NOT generated "
                     "quiz questions):"),
        }
        result = headers[kind] + "\n" + _extractive_fallback(source_text)
        model = "offline-fallback"

    with db.connect(db_path) as con:
        con.execute("UPDATE ai_jobs SET status='done', result=?, model=?, finished_at=? WHERE id=?",
                    (result, model, db.now(), job_id))
        if model != "offline-fallback":
            con.execute("INSERT OR REPLACE INTO ai_cache (cache_key, kind, result, model, created_at)"
                        " VALUES (?,?,?,?,?)", (key, kind, result, model, db.now()))
    return job_id, "done", result


# Explicit key-concept rubric for the synthetic CSC101 Week 3 demo lecture
# (demo/lecture_csc101.txt). Quality is scored as rubric coverage, not by
# output length: a good study summary must keep these concepts.
CSC101_W3_KEY_CONCEPTS = [
    "algorithm",
    "time complexity",
    "big-o",
    "binary search",
    "o(log n)",
    "bubble sort",
    "merge sort",
    "data structures",
    "stack",
    "queue",
]


def concept_coverage(text):
    """Which rubric concepts appear in a text (case-insensitive). Returns
    (found, missing) lists. Simple substring match - transparent and
    reproducible, at the cost of ignoring paraphrase."""
    low = text.lower()
    found = [c for c in CSC101_W3_KEY_CONCEPTS if c in low]
    missing = [c for c in CSC101_W3_KEY_CONCEPTS if c not in low]
    return found, missing


def quality_check():
    """Same-source comparison with an explicit rubric: the deterministic
    offline fallback vs the configured model (when reachable). Returns None
    on the model side when no live call has succeeded - never substituted
    by a second fallback pass."""
    source = open(DEMO_LECTURE_PATH, encoding="utf-8").read()
    fb_found, fb_missing = concept_coverage(_extractive_fallback(source, max_sentences=8))
    result = {"source": "CSC101-W3 synthetic lecture notes",
              "rubric": CSC101_W3_KEY_CONCEPTS,
              "fallback": {"found": fb_found, "missing": fb_missing},
              "model": None}
    if endpoint_configured():
        try:
            out = _call_model("summary", source)
            m_found, m_missing = concept_coverage(out)
            result["model"] = {"name": DEFAULT_MODEL, "found": m_found,
                               "missing": m_missing, "output": out}
        except Exception:
            result["model"] = None
    return result


def ai_stats(db_path):
    """Measured evidence for the offline-first story. Everything here is
    counted from this demo database; the one estimate is labeled with its
    comparison scenario."""
    with db.connect(db_path) as con:
        rows = [dict(r) for r in con.execute(
            "SELECT model, COUNT(*) AS n FROM ai_jobs WHERE status='done' GROUP BY model")]
        condense = con.execute(
            "SELECT source_text, result FROM ai_jobs WHERE kind='condense' AND status='done'"
            " AND model != 'offline-fallback'").fetchall()
        totals = con.execute(
            "SELECT COALESCE(SUM(LENGTH(source_text)),0) AS src,"
            " COALESCE(SUM(LENGTH(result)),0) AS out_ FROM ai_jobs WHERE status='done'"
        ).fetchone()
    by_model = { (r["model"] or "unknown"): r["n"] for r in rows }
    saved_bytes = sum(max(0, len(r["source_text"]) - len(r["result"] or "")) for r in condense)
    reads = db.material_read_stats(db_path)
    # Comparison scenario (explicit): without the on-campus library, every
    # library read would have downloaded the full material text once over
    # the campus internet. The estimate counts text bytes only - a real
    # web download would transfer more (page markup, images).
    estimated_avoided = reads["read_text_bytes"]
    return {"by_model": by_model,
            "cache_hits": by_model.get("cache", 0),
            "live_calls": sum(n for m, n in by_model.items()
                              if m not in ("cache", "offline-fallback", "unknown")),
            "fallback_served": by_model.get("offline-fallback", 0),
            "condense_saved_bytes": saved_bytes,
            "source_text_bytes": totals["src"],
            "output_text_bytes": totals["out_"],
            "library_reads": reads["library_reads"],
            "distinct_readers": reads["distinct_readers"],
            "read_text_bytes": reads["read_text_bytes"],
            "estimated_avoided_fetch_bytes": estimated_avoided}


def list_jobs(db_path, limit=20):
    with db.connect(db_path) as con:
        return [dict(r) for r in con.execute(
            "SELECT id, kind, status, model, created_at, finished_at, substr(result,1,400) AS preview"
            " FROM ai_jobs ORDER BY id DESC LIMIT ?", (limit,))]


def get_job(db_path, job_id):
    with db.connect(db_path) as con:
        r = con.execute("SELECT * FROM ai_jobs WHERE id=?", (job_id,)).fetchone()
        return dict(r) if r else None
