# Smart Campus Connect

Offline-first campus connectivity and study platform, built for the
University of Nigeria, Nsukka (UNN) - where internet is scarce and
expensive and students get limited online hours.

**Meta Global AI Developer Hackathon 2026 - theme: Build for Your World**

## What it does

1. **Fair, transparent internet-hour allocation.** The administrator sets
   the weekly pool; every student gets a guaranteed minimum when the pool
   allows, and the remainder is weighted by exam urgency and documented
   need. Every allocation carries a human-readable rationale the student
   can see.
2. **Usage logging.** Students log sessions against their allocation and
   always see what remains.
3. **AI study tools built for unreliable connectivity.** Exam summaries,
   revision quizzes, and web-article condensation. Every request is
   recorded in the local job log; results are cached on the campus
   server, so repeats cost no new model call. Lecturers publish results to a library students can open over the
   campus network with no internet. When no model endpoint is reachable, a
   clearly-labeled non-AI extractive fallback keeps the tools usable - it
   is never presented as model output, and its quiz mode serves extracted
   key sentences for self-testing, never implied to be generated questions.
4. **Exam-targeted library.** Students carry explicit course/exam IDs
   (e.g. CSC101); published materials carry course tags (e.g. CSC101-W3),
   and the dashboard surfaces exactly the materials matching a student's
   registered exams.
5. **Measured usage panel.** The admin page counts what the demo database
   actually records: library reads, distinct readers, cache hits, live
   model calls, labeled fallback servings, and text bytes in and out. The
   single estimate (downloads avoided) is labeled with its comparison
   scenario. A same-source quality check scores fallback and model output
   against a fixed key-concept rubric - not by output length.
6. **Runs on a campus server.** Flask + SQLite, local role-based accounts
   (student / lecturer / admin) - no external identity provider needed on
   an isolated network.

## AI integration

The AI module uses an OpenAI-compatible chat-completions endpoint.
The prototype has been tested with Meta Llama 3.3 70B through Cloudflare
Workers AI. Qualifying Muse model access is still pending; no successful
Muse call or local Muse deployment is claimed.

Endpoint URL, model ID and API key are configurable. Each provider and
model must be tested before claiming compatibility. Cache entries are
scoped by endpoint and model, so changing either requires fresh generation.

Configure with environment variables:

    AI_BASE_URL   # e.g. https://inference.baseten.co/v1
    AI_API_KEY    # endpoint key
    AI_MODEL      # e.g. muse-spark-open

With no endpoint configured or reachable, the labeled offline fallback
takes over automatically.

## Run it

    pip install -r requirements.txt
    python demo/seed_demo.py  # creates the demo database (synthetic people)
    python run.py           # http://localhost:5000

Demo credentials are generated randomly per seed run and printed to
`demo/DEMO_CREDENTIALS.txt` (gitignored). All demo people and data are
synthetic.

## Tests

    python -m pytest tests/ -q

## Tech

Flask, SQLite, vanilla HTML/CSS/JS. No build step, no external services
required for the core system.

## License

MIT
