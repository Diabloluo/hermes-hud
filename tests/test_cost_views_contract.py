"""Cross-view fixtures: provenance and sanitized cwd, without real Hermes data."""
import sqlite3
import time
from pathlib import Path

import pytest

from dashboard.hud import collectors, cost, timeline


@pytest.fixture
def fixture_db(tmp_path, monkeypatch):
    now = time.time()
    con = sqlite3.connect(tmp_path / 'state.db')
    con.executescript('''
    CREATE TABLE sessions (
        id TEXT, source TEXT, user_id TEXT, model TEXT, started_at REAL,
        ended_at REAL, title TEXT, message_count INTEGER, tool_call_count INTEGER,
        input_tokens INTEGER, output_tokens INTEGER, cache_read_tokens INTEGER,
        cache_write_tokens INTEGER, reasoning_tokens INTEGER,
        estimated_cost_usd REAL, actual_cost_usd REAL, cost_status TEXT,
        cost_source TEXT, end_reason TEXT, cwd TEXT, billing_provider TEXT);
    CREATE TABLE messages (session_id TEXT, role TEXT, content TEXT, timestamp REAL);
    CREATE TABLE session_model_usage (
        session_id TEXT, model TEXT, task TEXT, api_call_count INTEGER,
        input_tokens INTEGER, output_tokens INTEGER, cache_read_tokens INTEGER,
        cache_write_tokens INTEGER, reasoning_tokens INTEGER,
        estimated_cost_usd REAL, actual_cost_usd REAL, cost_status TEXT,
        cost_source TEXT, first_seen REAL, last_seen REAL, billing_provider TEXT);
    ''')
    con.execute('INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                ('s', 'test', 'test', 'm', now-20, now-10, 'Synthetic', 1, 0,
                 10, 1, 0, 0, 0, 99.0, None, None, None, None,
                 '/Users/synthetic/Project/token=EXAMPLE_ONLY_SECRET', 'test'))
    con.execute("INSERT INTO messages VALUES ('s','user','Synthetic',?)", (now-15,))
    con.commit()
    monkeypatch.setattr(collectors, 'HERMES_HOME', tmp_path)
    monkeypatch.setenv('HUD_STATE_DB', str(tmp_path/'state.db'))
    yield con, tmp_path, now
    con.close()


def add_usage(con, now, estimate, status, source, task=''):
    con.execute('INSERT INTO session_model_usage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                ('s', 'm', task, 1, 10, 1, 0, 0, 0, estimate, None,
                 status, source, now-20, now-10, 'test'))
    con.commit()


@pytest.mark.parametrize('rows,known,unknown,expected,complete', [
    ([(.5, None, None)], 0, 1, 0, False),
    ([(.5, 'unknown', 'none')], 0, 1, 0, False),
    ([(.5, 'estimated', None)], 0, 1, 0, False),
    ([(.5, 'estimated', 'fixture_prices')], 1, 0, .5, True),
    ([(0, 'estimated', 'fixture_prices')], 1, 0, 0, True),
    ([(.5, 'estimated', 'fixture_prices'), (.7, None, None)], 1, 1, .5, False),
])
def test_cost_matches_canonical_across_views(fixture_db, rows, known, unknown, expected, complete):
    con, home, now = fixture_db
    for i, row in enumerate(rows):
        add_usage(con, now, *row, task='' if i == 0 else 'compression')
    canonical = cost.compute_summary(home, 'all')
    assert canonical['estimated_cost_usd'] == pytest.approx(expected)
    detail = collectors.collect_session_detail('s')
    views = [collectors.collect_recent_sessions()[0], collectors.search_sessions('Synthetic')[0],
             detail, collectors.collect_usage()['totals'],
             collectors.collect_usage()['by_day'][0], collectors.collect_usage()['by_model'][0],
             collectors.collect_db()['usage'], collectors.collect_db()['model_usage']]
    for view in views:
        assert view['estimated_cost_usd'] == pytest.approx(expected)
        assert view['pricing_known_rows'] == known
        assert view['pricing_unknown_rows'] == unknown
        assert view['cost_complete'] == complete
    assert detail['cwd'].startswith('~/')
    assert 'synthetic' not in detail['cwd']
    assert 'EXAMPLE_ONLY_SECRET' not in detail['cwd']
    assert len(detail['model_usage']) == len(rows)
    assert detail['model_usage'][0]['cost_complete'] == (known > 0)
    completed = next(e for e in timeline.collect_session_events(home)
                     if e['event_type'] == 'session.completed')
    assert completed['cost_usd'] == (expected if complete else None)
    # Already persisted pre-fix records must not keep displaying stale raw sums.
    stale = [{'event_type': 'session.completed', 'session_id': 's', 'cost_usd': 99.0}]
    assert timeline.refresh_session_event_costs(home, stale)[0]['cost_usd'] == completed['cost_usd']


def test_no_usage_is_unknown_session_but_healthy_zero_global(fixture_db):
    con, home, now = fixture_db
    assert cost.compute_summary(home, 'all')['cost_complete']
    assert cost.compute_summary(home, 'all')['estimated_cost_usd'] == 0
    assert not collectors.collect_session_detail('s')['cost_complete']
    assert not collectors.collect_recent_sessions()[0]['cost_complete']
    completed = next(e for e in timeline.collect_session_events(home)
                     if e['event_type'] == 'session.completed')
    assert completed['cost_usd'] is None
    unidentified = [{'event_type': 'session.completed', 'cost_usd': 99.0}]
    assert timeline.refresh_session_event_costs(home, unidentified)[0]['cost_usd'] is None


def test_missing_legacy_provenance_never_becomes_known(fixture_db):
    con, home, now = fixture_db
    add_usage(con, now, .5, 'estimated', 'fixture_prices')
    con.execute('ALTER TABLE session_model_usage DROP COLUMN cost_source')
    con.commit()
    detail = collectors.collect_session_detail('s')
    assert detail is not None
    assert detail['pricing_unknown_rows'] == 1
    assert not detail['model_usage'][0]['cost_complete']
    assert collectors.collect_usage()['totals']['pricing_unknown_rows'] == 1
    assert collectors.collect_db()['model_usage']['pricing_unknown_rows'] == 1


@pytest.mark.parametrize('cwd,expected', [(None, None), ('', ''), ('relative/project', 'relative/project'),
    ('/Users/synthetic/project', '~/project'), ('/home/synthetic/project', '~/project')])
def test_detail_cwd_contract(fixture_db, cwd, expected):
    con, home, now = fixture_db
    con.execute('UPDATE sessions SET cwd=?', (cwd,))
    con.commit()
    assert collectors.collect_session_detail('s')['cwd'] == expected


def test_unavailable_usage_source_is_not_zero(fixture_db):
    con, home, now = fixture_db
    con.execute('DROP TABLE session_model_usage')
    con.commit()
    view = collectors.collect_recent_sessions()[0]
    assert view['estimated_cost_usd'] is None
    assert not view['cost_complete']
    assert view['cost_source_status'] == 'unavailable'


def test_rest_responses_and_persisted_history(fixture_db, monkeypatch):
    import hashlib
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from dashboard import plugin_api as api
    from hud import storage as api_storage, timeline as api_timeline

    con, home, now = fixture_db
    add_usage(con, now, .5, None, None)
    monkeypatch.setattr(api.collectors, 'HERMES_HOME', home)
    telemetry = api_storage.TelemetryStore(db_path=home/'telemetry.db')
    monkeypatch.setattr(api, 'store', telemetry)
    completed = next(e for e in api_timeline.collect_session_events(home)
                     if e['event_type'] == 'session.completed')
    completed['cost_usd'] = 99.0
    assert telemetry.record_timeline_event(completed)
    state_before = hashlib.sha256((home/'state.db').read_bytes()).hexdigest()
    app = FastAPI();app.include_router(api.router, prefix='/api/plugins/hermes-hud')
    with TestClient(app) as client:
        prefix = '/api/plugins/hermes-hud'
        detail = client.get(prefix+'/sessions/s').json()
        assert 'EXAMPLE_ONLY_SECRET' not in str(detail['cwd'])
        assert detail['estimated_cost_usd'] == 0
        assert not detail['cost_complete']
        for path in ('/sessions', '/sessions/search?q=Synthetic'):
            response = client.get(prefix+path)
            assert response.status_code == 200
            assert response.json()[0]['pricing_unknown_rows'] == 1
        usage = client.get(prefix+'/usage').json()
        assert usage['totals']['est_cost'] == 0
        assert not usage['totals']['cost_complete']
        response = client.get(prefix+'/timeline')
        assert response.status_code == 200
        event = next(e for e in response.json()['events'] if e['event_type'] == 'session.completed')
        assert event['cost_usd'] is None
    persisted = next(e for e in telemetry.query_timeline()
                     if e['event_type'] == 'session.completed')
    assert persisted['cost_usd'] == 99.0 # response revalidation did not rewrite history
    assert hashlib.sha256((home/'state.db').read_bytes()).hexdigest() == state_before


def test_partial_snapshot_error_cannot_return_unverified_legacy_cost(fixture_db):
    con, home, now = fixture_db
    add_usage(con, now, .5, None, None)
    con.execute('ALTER TABLE session_model_usage DROP COLUMN last_seen')
    con.commit()
    snapshot = collectors.collect_db()
    assert snapshot['error'] is not None
    assert snapshot['usage']['estimated_cost_usd'] is None
    assert snapshot['model_usage']['estimated_cost_usd'] is None
    assert not snapshot['usage']['cost_complete']
