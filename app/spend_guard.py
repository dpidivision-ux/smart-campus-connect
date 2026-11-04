"""Opt-in local reservation guard for the direct Meta paid path.

Not a provider-enforced spending limit. Meta bills actual token usage;
this guard refuses to start a paid generation call unless a conservative
reservation for that exact request fits inside the reviewed ledger policy.

Reserve basis (source-backed, no assumed chars-to-tokens factor):
- Input: POST /v1/responses/input_tokens runs the provider's own tokenizer
  on the fully rendered request, including Meta-injected scaffolding
  (dev.meta.ai/docs/token-counting). Billing excludes injected tokens
  (dev.meta.ai/docs/pricing-rate-limits), so for a single-turn, no-tools
  request the count is an upper bound on billed input. The reserve counts
  that number TWICE: once for the generation call, once for the count call
  itself in case tokenization traffic is ever billed.
- Output: max_output_tokens is a hard server cap and reasoning tokens are
  billed as output (dev.meta.ai/docs/reasoning), so the full output ceiling
  is reserved on every attempt.
- Prices: muse-spark Standard input $1.25/1M, output $4.25/1M
  (dev.meta.ai/docs/pricing-rate-limits).

Failed and timeout attempts remain reserved; there is no automatic release.
The ledger lives outside disposable demo data (the recorder reseeds
campus.db) and initialization refuses to overwrite it. The cutoff blocks
starting new network sends; it cannot cancel in-flight provider work.
Other provider paths are not covered by this guard.
"""
import os
import sqlite3
import time

ENDPOINT = 'https://api.meta.ai/v1'
MODEL = 'muse-spark-1.2'
CONTEXT = 1048576
OUTPUT = 900
# Sanity ceiling on the provider-reported input count; legitimate prompts
# here are ~4k tokens. Anything larger indicates a prompt-assembly bug.
MAX_INPUT_TOKENS = 100000
# Asserted bound on the exact serialized prompt, checked before any network
# call. Structurally guaranteed: source text is truncated to 12000 chars and
# templates are fixed (<500 bytes), so the prompt can never exceed
# 12000*4 + 500 bytes even for 4-byte UTF-8 input. The check turns that
# structural bound into an enforced fail-closed assertion.
MAX_INPUT_BYTES = 48500
# $1.25 / 1M tokens = 1.25 microUSD per token; $4.25/1M = 4.25.
INPUT_MICRO_NUM, INPUT_MICRO_DEN = 125, 100
OUTPUT_MICRO_NUM, OUTPUT_MICRO_DEN = 425, 100


class GuardBlocked(RuntimeError):
    pass


def _ledger_path():
    path = os.environ.get('SCC_SPEND_LEDGER', '')
    if not os.path.isabs(path) or os.path.basename(path) == 'campus.db':
        raise GuardBlocked('Separate absolute ledger path required')
    if not os.path.exists(path):
        raise GuardBlocked('Ledger must be initialized by reviewed preparation')
    return path


def reserve_micro_for(input_tokens, max_output=OUTPUT):
    inp = (2 * input_tokens * INPUT_MICRO_NUM + INPUT_MICRO_DEN - 1) // INPUT_MICRO_DEN
    out = (max_output * OUTPUT_MICRO_NUM + OUTPUT_MICRO_DEN - 1) // OUTPUT_MICRO_DEN
    return inp + out


def check_static(endpoint, model, max_output, now=None):
    """Fail-closed static gate run BEFORE any network traffic, including the
    provider count call: explicit enable, endpoint/model/output allowlist,
    ledger existence, and usage cutoff."""
    if os.environ.get('SCC_PAID_GUARD') != 'enabled':
        raise GuardBlocked('Paid access is not enabled')
    if (endpoint.rstrip('/'), model, max_output) != (ENDPOINT, MODEL, OUTPUT):
        raise GuardBlocked('Endpoint, model or output ceiling not allowed')
    path = _ledger_path()
    now = time.time() if now is None else now
    con = sqlite3.connect(path, timeout=10)
    try:
        p = con.execute('SELECT cutoff FROM policy WHERE id=1').fetchone()
        if not p or now >= p[0]:
            raise GuardBlocked('Usage cutoff reached or policy missing')
    finally:
        con.close()


def reserve(endpoint, model, max_output, now=None):
    """Atomic pre-network reservation for one full attempt (count call plus
    possible generation) at the fixed attempt ceiling. Raises GuardBlocked
    when disabled, off-allowlist, past cutoff, or over budget/call cap."""
    check_static(endpoint, model, max_output, now)
    micro = reserve_micro_for(MAX_INPUT_TOKENS, max_output)
    path = _ledger_path()
    now = time.time() if now is None else now
    con = sqlite3.connect(path, timeout=10)
    try:
        con.execute('BEGIN IMMEDIATE')
        p = con.execute('SELECT cutoff,budget_micro,call_cap FROM policy WHERE id=1').fetchone()
        total, calls = con.execute(
            'SELECT COALESCE(SUM(reserve_micro),0),COUNT(*) FROM attempts').fetchone()
        if total + micro > p[1] or calls >= p[2]:
            raise GuardBlocked('Reservation budget or call cap exhausted')
        contradictions = con.execute(
            "SELECT COUNT(*) FROM attempts WHERE status='usage-contradicts-guard'").fetchone()[0]
        if contradictions:
            raise GuardBlocked('Halted: earlier usage contradicted the guard')
        cur = con.execute('INSERT INTO attempts(started,reserve_micro,status) VALUES(?,?,?)',
                          (now, micro, 'reserved-uncertain'))
        con.commit()
        return path, cur.lastrowid
    finally:
        con.close()


def initialize(path, cutoff, budget_micro, call_cap):
    """One-time setup only. Never resets or overwrites an existing ledger."""
    if not os.path.isabs(path) or os.path.basename(path) == 'campus.db':
        raise ValueError('Separate absolute ledger path required')
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    con = sqlite3.connect(path)
    try:
        con.executescript('CREATE TABLE policy(id INTEGER PRIMARY KEY,cutoff REAL,budget_micro INTEGER,call_cap INTEGER); CREATE TABLE attempts(id INTEGER PRIMARY KEY,started REAL,reserve_micro INTEGER,status TEXT,usage_json TEXT);')
        con.execute('INSERT INTO policy VALUES(1,?,?,?)', (cutoff, budget_micro, call_cap))
        con.commit()
    finally:
        con.close()


def record(reservation, status, usage=None):
    import json
    path, attempt = reservation
    con = sqlite3.connect(path)
    try:
        con.execute('UPDATE attempts SET status=?,usage_json=? WHERE id=?',
                    (status, json.dumps(usage), attempt))
        con.commit()
    finally:
        con.close()
