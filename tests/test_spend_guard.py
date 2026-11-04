import concurrent.futures
import sqlite3
import pytest
from app import spend_guard as g

# Fixed per-attempt reservation: 2*MAX_INPUT_TOKENS input + 900 output.
MICRO = g.reserve_micro_for(g.MAX_INPUT_TOKENS, g.OUTPUT)  # 253825

def setup(tmp_path, monkeypatch, budget=MICRO, cap=20):
    p = str(tmp_path / 'persistent-spend.sqlite')
    g.initialize(p, 200, budget, cap)
    monkeypatch.setenv('SCC_PAID_GUARD', 'enabled')
    monkeypatch.setenv('SCC_SPEND_LEDGER', p)
    return p

def call(now=100):
    return g.reserve(g.ENDPOINT, g.MODEL, 900, now)

def test_reserve_math():
    assert MICRO == 253825
    assert g.reserve_micro_for(0) == 3825

def test_disabled(monkeypatch):
    monkeypatch.delenv('SCC_PAID_GUARD', raising=False)
    with pytest.raises(g.GuardBlocked):
        call()
    with pytest.raises(g.GuardBlocked):
        g.check_static(g.ENDPOINT, g.MODEL, 900)

def test_budget_persists_uncertain_failure(tmp_path, monkeypatch):
    p = setup(tmp_path, monkeypatch)
    r = call()
    g.record(r, 'failed-or-timeout')
    with pytest.raises(g.GuardBlocked):
        call()
    assert sqlite3.connect(p).execute(
        'SELECT SUM(reserve_micro) FROM attempts').fetchone()[0] == MICRO
    with pytest.raises(FileExistsError):
        g.initialize(p, 300, 99999999, 99)

def test_cutoff_and_allowlist(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    for endpoint, model, tokens, now in [
            (g.ENDPOINT, 'other', 900, 100),
            ('https://other.invalid', g.MODEL, 900, 100),
            (g.ENDPOINT, g.MODEL, 901, 100),
            (g.ENDPOINT, g.MODEL, 900, 200)]:
        with pytest.raises(g.GuardBlocked):
            g.reserve(endpoint, model, tokens, now)

def test_atomic_concurrency(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    def attempt(_):
        try:
            call()
            return 1
        except g.GuardBlocked:
            return 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        assert sum(ex.map(attempt, range(8))) == 1

def test_cap_and_missing_ledger(tmp_path, monkeypatch):
    p = setup(tmp_path, monkeypatch, budget=99999999, cap=1)
    call()
    with pytest.raises(g.GuardBlocked):
        call()
    monkeypatch.setenv('SCC_SPEND_LEDGER', str(tmp_path / 'campus.db'))
    with pytest.raises(g.GuardBlocked):
        call()


def _meta_mock(monkeypatch, tmp_path, budget=MICRO, count=1000, fail_at=None):
    from app import ai_module
    p = setup(tmp_path, monkeypatch, budget=budget)
    monkeypatch.setattr(g.time, 'time', lambda: 100)
    monkeypatch.setattr(ai_module, 'BASE_URL', g.ENDPOINT)
    monkeypatch.setattr(ai_module, 'DEFAULT_MODEL', g.MODEL)
    calls = []
    class R:
        def __init__(self, payload): self._p = payload
        def raise_for_status(self): pass
        def json(self): return self._p
    def post(url, **kw):
        assert kw['allow_redirects'] is False
        calls.append(url)
        if fail_at and url.endswith(fail_at):
            raise TimeoutError()
        if url.endswith('/responses/input_tokens'):
            return R({'object': 'response.input_tokens', 'input_tokens': count})
        assert url.endswith('/responses')
        assert kw['json']['max_output_tokens'] == 900
        assert kw['json']['reasoning'] == {'effort': 'low'}
        assert kw['json']['store'] is False
        return R({'status': 'completed',
                  'output': [{'type': 'message', 'role': 'assistant',
                              'content': [{'type': 'output_text', 'text': 'summary text'}]}],
                  'usage': {'input_tokens': 980, 'output_tokens': 120}})
    monkeypatch.setattr(ai_module.requests, 'post', post)
    return ai_module, calls, p

def test_direct_meta_disabled_never_sends(monkeypatch, tmp_path):
    from app import ai_module
    monkeypatch.setattr(ai_module, 'BASE_URL', g.ENDPOINT)
    monkeypatch.setattr(ai_module, 'DEFAULT_MODEL', g.MODEL)
    monkeypatch.delenv('SCC_PAID_GUARD', raising=False)
    calls = []
    monkeypatch.setattr(ai_module.requests, 'post', lambda *a, **k: calls.append(1))
    with pytest.raises(g.GuardBlocked):
        ai_module._call_model('summary', 'example')
    assert calls == []

def test_direct_meta_counts_then_sends(monkeypatch, tmp_path):
    ai_module, calls, p = _meta_mock(monkeypatch, tmp_path)
    assert ai_module._call_model('summary', 'example') == 'summary text'
    assert [u.split('/')[-1] for u in calls] == ['input_tokens', 'responses']
    row = sqlite3.connect(p).execute(
        'SELECT status, usage_json FROM attempts').fetchone()
    assert row[0] == 'response-received' and 'input_tokens_counted' in row[1]

def test_direct_meta_failed_attempt_reserved(monkeypatch, tmp_path):
    ai_module, calls, p = _meta_mock(monkeypatch, tmp_path, fail_at='/responses')
    with pytest.raises(TimeoutError):
        ai_module._call_model('summary', 'example')
    with pytest.raises(g.GuardBlocked):
        ai_module._call_model('summary', 'example')
    gens = [u for u in calls if u.endswith('/responses')]
    assert len(gens) == 1  # second attempt blocked at reserve, before network
    assert len(calls) == 2  # attempt 1: count+generation; attempt 2: no network

def test_direct_meta_count_failure_still_reserved(monkeypatch, tmp_path):
    ai_module, calls, p = _meta_mock(monkeypatch, tmp_path, fail_at='/responses/input_tokens')
    with pytest.raises(TimeoutError):
        ai_module._call_model('summary', 'example')
    with pytest.raises(g.GuardBlocked):
        ai_module._call_model('summary', 'example')  # budget exhausted by the failed attempt
    assert calls == ['https://api.meta.ai/v1/responses/input_tokens']

def test_direct_meta_input_ceiling_blocks_before_generation(monkeypatch, tmp_path):
    ai_module, calls, p = _meta_mock(monkeypatch, tmp_path,
                                     budget=10 * MICRO, count=g.MAX_INPUT_TOKENS + 1)
    with pytest.raises(g.GuardBlocked):
        ai_module._call_model('summary', 'example')
    assert calls == ['https://api.meta.ai/v1/responses/input_tokens']
    row = sqlite3.connect(p).execute('SELECT status FROM attempts').fetchone()
    assert row[0] == 'blocked-input-ceiling'


def test_usage_contradiction_halts_future_calls(monkeypatch, tmp_path):
    from app import ai_module
    p = setup(tmp_path, monkeypatch, budget=10 * MICRO)
    monkeypatch.setattr(g.time, 'time', lambda: 100)
    monkeypatch.setattr(ai_module, 'BASE_URL', g.ENDPOINT)
    monkeypatch.setattr(ai_module, 'DEFAULT_MODEL', g.MODEL)
    class R:
        def __init__(self, payload): self._p = payload
        def raise_for_status(self): pass
        def json(self): return self._p
    def post(url, **kw):
        if url.endswith('/responses/input_tokens'):
            return R({'input_tokens': 1000})
        return R({'status': 'completed',
                  'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': 'x'}]}],
                  'usage': {'input_tokens': 1000, 'output_tokens': 901}})  # over hard cap
    monkeypatch.setattr(ai_module.requests, 'post', post)
    assert ai_module._call_model('summary', 'example') == 'x'
    with pytest.raises(g.GuardBlocked, match='contradicted'):
        ai_module._call_model('summary', 'example')

def test_byte_cap_blocks_before_network(monkeypatch, tmp_path):
    ai_module, calls, p = _meta_mock(monkeypatch, tmp_path)
    monkeypatch.setattr(g, 'MAX_INPUT_BYTES', 100)
    with pytest.raises(g.GuardBlocked, match='byte cap'):
        ai_module._call_model('summary', 'x' * 200)
    assert calls == []
    assert sqlite3.connect(p).execute('SELECT COUNT(*) FROM attempts').fetchone()[0] == 0
