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
        # Offline or endpoint failure: deterministic fallback, clearly labeled.
        result = ("OFFLINE FALLBACK (no model call succeeded yet; this extractive "
                  "summary is generated locally without AI):\n" + _extractive_fallback(source_text))
        model = "offline-fallback"

    with db.connect(db_path) as con:
        con.execute("UPDATE ai_jobs SET status='done', result=?, model=?, finished_at=? WHERE id=?",
                    (result, model, db.now(), job_id))
        if model != "offline-fallback":
            con.execute("INSERT OR REPLACE INTO ai_cache (cache_key, kind, result, model, created_at)"
                        " VALUES (?,?,?,?,?)", (key, kind, result, model, db.now()))
    return job_id, "done", result


def ai_stats(db_path):
    """Evidence for the offline-first story: cache hits vs live model calls,
    and text bytes reduced by condensation."""
    with db.connect(db_path) as con:
        rows = [dict(r) for r in con.execute(
            "SELECT model, COUNT(*) AS n FROM ai_jobs WHERE status='done' GROUP BY model")]
        condense = con.execute(
            "SELECT source_text, result FROM ai_jobs WHERE kind='condense' AND status='done'"
            " AND model != 'offline-fallback'").fetchall()
    by_model = { (r["model"] or "unknown"): r["n"] for r in rows }
    saved_bytes = sum(max(0, len(r["source_text"]) - len(r["result"] or "")) for r in condense)
    return {"by_model": by_model,
            "cache_hits": by_model.get("cache", 0),
            "live_calls": sum(n for m, n in by_model.items()
                              if m not in ("cache", "offline-fallback", "unknown")),
            "fallback_served": by_model.get("offline-fallback", 0),
            "condense_saved_bytes": saved_bytes}


def list_jobs(db_path, limit=20):
    with db.connect(db_path) as con:
        return [dict(r) for r in con.execute(
            "SELECT id, kind, status, model, created_at, finished_at, substr(result,1,400) AS preview"
            " FROM ai_jobs ORDER BY id DESC LIMIT ?", (limit,))]


def get_job(db_path, job_id):
    with db.connect(db_path) as con:
        r = con.execute("SELECT * FROM ai_jobs WHERE id=?", (job_id,)).fetchone()
        return dict(r) if r else None
