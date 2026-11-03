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
   revision quizzes, and web-article condensation. Requests queue locally;
   results are cached on the campus server, so repeats cost no new model
   call. Lecturers publish results to a library students can open over the
   campus network with no internet. When no model endpoint is reachable, a
   clearly-labeled non-AI extractive fallback keeps the tools usable - it
   is never presented as model output.
4. **Runs on a campus server.** Flask + SQLite, local role-based accounts
   (student / lecturer / admin) - no external identity provider needed on
   an isolated network.

## AI integration

The AI module calls Meta's open-weight models through an
OpenAI-compatible chat-completions endpoint. One configuration switch
points the same code at:

- the **Meta Model API** (Muse Spark series),
- a hackathon inference partner hosting **Muse Spark Open** (e.g. Baseten),
- **Muse Glimmer** running locally on a campus PC (llama.cpp / LM Studio).

Configure with environment variables:

    AI_BASE_URL   # e.g. https://inference.baseten.co/v1
    AI_API_KEY    # endpoint key
    AI_MODEL      # e.g. muse-spark-open

With no endpoint configured or reachable, the labeled offline fallback
takes over automatically.

## Run it

    pip install -r requirements.txt
    python seed.py          # creates the demo database (synthetic people)
    python app.py           # http://localhost:5000

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
