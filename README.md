# Smart Campus Connect

Offline-first internet-hours allocation and AI study tools for the
University of Nigeria, Nsukka (UNN), where student internet access is
scarce and expensive.

Built during the Meta Global AI Developer Hackathon (Oct 26 - Nov 4, 2026),
theme "Build for Your World", Indie Developer track.

## The problem

UNN students receive limited, rationed internet hours. Administrators
divide a small weekly pool by hand, students cannot see why they got
what they got, and lecture materials assume always-on connectivity that
does not exist on campus.

## What the system does

1. **Fair, transparent allocation of internet hours.** An administrator
   sets the weekly pool (total online minutes the campus can offer).
   The allocation engine splits it: every student gets a guaranteed
   floor, and the remainder is weighted by exam urgency and documented
   need. Each allocation carries a human-readable rationale.
2. **Offline-first AI study tools.** A student pastes lecture notes and
   gets a 5-bullet exam summary or a 5-question revision quiz, produced
   by Meta's open-weight models. A condense mode shrinks web articles to
   their key facts before download - direct bandwidth savings, metered
   on the admin console. Because connectivity is unreliable, every AI
   request is queued in the local database, results are cached, and
   repeated requests are served without a new model call. When no
   endpoint is reachable, a deterministic extractive fallback - clearly
   labeled as non-AI - keeps the feature usable.
3. **Usage tracking and a study library.** Students log the minutes
   they spend and see them against their allocation. Lecturers publish
   generated summaries and quizzes to a library that every student can
   open with zero connectivity.
4. **Role-based access.** Students, lecturers and administrators sign in
   locally; no external identity provider is needed on an isolated
   campus network.

## Use of Meta models

The AI module calls any OpenAI-compatible endpoint serving Meta's
open-weight models - Meta Model API (Muse Spark series), a hackathon
inference partner hosting `muse-spark-open`, or Muse Glimmer running on
a campus PC (llama.cpp / LM Studio). The endpoint is configuration, not
code:

```
export AI_BASE_URL=https://inference.baseten.co/v1   # or Meta Model API / local server
export AI_API_KEY=...
export AI_MODEL=meta-models/muse-spark-open-1026      # hackathon build on Baseten
```

With no endpoint configured the system runs fully offline (fallback +
cache), which is also the production mode for a campus that loses
connectivity for days.

## Architecture

- `app/allocation.py` - deterministic allocation engine (pure function, tested)
- `app/ai_module.py` - offline-first AI queue + cache + OpenAI-compatible client
- `app/auth.py` - salted PBKDF2 password hashing, role-based sessions
- `app/db.py` - SQLite schema; every write is local-first
- `app/routes.py` - student dashboard, admin console, study tools
- `tests/` - allocation and AI-module test suites

## Run it

```
pip install -r requirements.txt
python demo/seed_demo.py        # demo data: 6 students, scarce 3000-min pool
python run.py                   # http://127.0.0.1:5000
```

Demo logins: `admin` / `admin-demo-2026`, student `adaeze` / `adaeze-demo-2026`.
Run the test suite with `python -m pytest tests/ -q`.

## What was built during the hackathon

All code in this repository was written during the hackathon window
(Oct 26 - Nov 4, 2026). The concept grows out of a registration system
for UNN internet hours that was previously in early development (not
deployed, no AI features); none of that earlier code is reused here.
