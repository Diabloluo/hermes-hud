"""Unbindable input is skipped; real transaction and IO failures remain fatal."""
from contextlib import closing
import json
import logging
from pathlib import Path
import sqlite3
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dashboard'))
from hud import storage, timeline

EPOCH = 1700000000
PRIVATE = 'synthetic-private-content-must-not-be-logged'


def mixed_ledger(home, monkeypatch, poison):
    for name in ('collect_session_events', 'collect_tool_events', 'collect_incident_events'):
        monkeypatch.setattr(timeline, name, lambda *a: [])
    records = [{'job_id': f'good-{i}', 'skill': 'synthetic-skill',
                'finished_at': EPOCH, 'fingerprint': f'good-fp-{i}'} for i in range(53)]
    bad = {
        'fingerprint': {'job_id': 'bad-fingerprint', 'skill': 'synthetic-skill',
                        'finished_at': EPOCH, 'fingerprint': {'private': PRIVATE}},
        'timestamp': {'job_id': 'bad-time', 'skill': 'synthetic-skill',
                      'finished_at': 1 << 63, 'fingerprint': PRIVATE},
    }
    selected = list(bad.values()) if poison == 'both' else [bad[poison]]
    records[17:17] = selected
    p = home / 'job-ledger' / 'jobs.jsonl'
    p.parent.mkdir(parents=True)
    p.write_text('\n'.join(json.dumps(r) for r in records) + '\n')
    return p, len(selected)


def watermark(store):
    with closing(store._connect()) as c:
        row = c.execute("SELECT value FROM meta WHERE key='timeline_last_scan'").fetchone()
    return row[0] if row else None


@pytest.mark.parametrize('poison', ['fingerprint', 'timestamp', 'both'])
def test_bad_input_does_not_poison_valid_batch_or_next_scan(tmp_path, monkeypatch, caplog, poison):
    ledger, count = mixed_ledger(tmp_path, monkeypatch, poison)
    store = storage.TelemetryStore(tmp_path / 'hud' / 'telemetry.db')
    monkeypatch.setattr(timeline.time, 'time', lambda: EPOCH + 1)
    with caplog.at_level(logging.WARNING, logger='hud.timeline'):
        result = timeline.collect_timeline(tmp_path, store)
    assert (result['written'], result['skipped'], result['invalid']) == (53, count, count)
    assert sum(result['invalid_reasons'].values()) == count
    assert watermark(store) == str(EPOCH + 1)
    assert len(store.query_timeline(limit=100)) == 53
    with closing(store._connect()) as c:
        identities = {r[0] for r in c.execute('SELECT source_record_id FROM timeline_events')}
    assert identities == {f'job:good-{i}:completed' for i in range(53)}
    assert 'rejected input' in caplog.text and PRIVATE not in caplog.text
    assert 'bad-fingerprint' not in caplog.text and 'bad-time' not in caplog.text
    # Poison remains in the ledger. The 5s overlap must still allow the next valid event.
    with ledger.open('a') as f:
        f.write(json.dumps({'job_id': 'next-good', 'skill': 'synthetic-skill',
                            'finished_at': EPOCH + 1, 'fingerprint': 'next-fp'}) + '\n')
    monkeypatch.setattr(timeline.time, 'time', lambda: EPOCH + 2)
    result = timeline.collect_timeline(tmp_path, store)
    assert (result['written'], result['skipped'], result['invalid']) == (1, 53 + count, count)
    assert watermark(store) == str(EPOCH + 2) and store.timeline_stats()['total'] == 54
    # Entirely invalid is a successful empty valid scan, with visible skipped counts.
    ledger.write_text('\n'.join(line for line in ledger.read_text().splitlines()
                                 if 'bad-fingerprint' in line or 'bad-time' in line) + '\n')
    monkeypatch.setattr(timeline.time, 'time', lambda: EPOCH + 3)
    result = timeline.collect_timeline(tmp_path, store)
    assert (result['written'], result['skipped'], result['invalid']) == (0, count, count)
    assert watermark(store) == str(EPOCH + 3)


@pytest.mark.parametrize('failure', ['event', 'watermark', 'commit', 'io'])
def test_poison_filter_does_not_swallow_database_failures(tmp_path, monkeypatch, failure):
    mixed_ledger(tmp_path, monkeypatch, 'both')
    store = storage.TelemetryStore(tmp_path / 'hud' / 'telemetry.db')
    monkeypatch.setattr(timeline.time, 'time', lambda: EPOCH + 1)
    with closing(store._connect()) as c, c:
        c.execute("INSERT INTO meta(key,value) VALUES('timeline_last_scan','123')")
        if failure == 'event':
            c.execute("CREATE TRIGGER injected BEFORE INSERT ON timeline_events "
                      "WHEN NEW.source_record_id='job:good-23:completed' "
                      "BEGIN SELECT RAISE(ABORT,'synthetic transaction fault'); END")
        elif failure == 'watermark':
            c.execute("CREATE TRIGGER injected BEFORE INSERT ON meta "
                      "WHEN NEW.key='timeline_last_scan' "
                      "BEGIN SELECT RAISE(ABORT,'synthetic watermark fault'); END")
        elif failure == 'commit':
            c.execute('CREATE TABLE fixture_parent(id INTEGER PRIMARY KEY)')
            c.execute('CREATE TABLE fixture_child(pid INTEGER REFERENCES fixture_parent(id) '
                      'DEFERRABLE INITIALLY DEFERRED)')
            c.execute("CREATE TRIGGER injected AFTER INSERT ON timeline_events "
                      "WHEN NEW.source_record_id='job:good-23:completed' "
                      "BEGIN INSERT INTO fixture_child(pid) VALUES(1); END")
    original = store._connect
    opened = []
    calls = 0
    def tracked():
        nonlocal calls
        calls += 1
        if failure == 'io' and calls == 2:
            raise sqlite3.OperationalError('synthetic disk IO error')
        c = original()
        if failure == 'commit':
            c.execute('PRAGMA foreign_keys=ON')
        opened.append(c)
        return c
    monkeypatch.setattr(store, '_connect', tracked)
    with pytest.raises(sqlite3.DatabaseError):
        timeline.collect_timeline(tmp_path, store)
    for c in opened:
        with pytest.raises(sqlite3.ProgrammingError):
            c.execute('SELECT 1')
    monkeypatch.setattr(store, '_connect', original)
    assert store.timeline_stats()['total'] == 0 and watermark(store) == '123'
    if failure != 'io':
        with closing(store._connect()) as c, c:
            c.execute('DROP TRIGGER injected')
    result = timeline.collect_timeline(tmp_path, store)
    assert (result['written'], result['skipped'], result['invalid']) == (53, 2, 2)
    assert watermark(store) == str(EPOCH + 1)


@pytest.mark.parametrize('field,value,reason', [
    ('timestamp', -(1 << 63) - 1, 'integer_range:timestamp'),
    ('tokens', 1 << 63, 'integer_range:tokens'),
    ('duration_ms', -(1 << 63) - 1, 'integer_range:duration_ms'),
    ('correlation_id', [PRIVATE], 'binding_type:correlation_id'),
    ('tool_call_id', {'private': PRIVATE}, 'binding_type:tool_call_id'),
    ('correlation_id', PRIVATE + '\ud800', 'string_encoding:correlation_id'),
])
def test_optional_and_lower_bound_poison_values_are_visible(tmp_path, monkeypatch, field, value, reason):
    valid = timeline.normalize_event({'timestamp': EPOCH, 'event_type': 'tool.completed',
                                      'source_record_id': 'synthetic-valid'})
    bad = {**valid, 'event_id': 'synthetic-bad', field: value}
    monkeypatch.setattr(timeline, 'collect_session_events', lambda *a: [valid, bad])
    for name in ('collect_tool_events', 'collect_incident_events', 'collect_skill_events'):
        monkeypatch.setattr(timeline, name, lambda *a: [])
    store = storage.TelemetryStore(tmp_path / 'telemetry.db')
    result = timeline.collect_timeline(tmp_path, store)
    assert (result['written'], result['skipped'], result['invalid']) == (1, 1, 1)
    assert result['invalid_reasons'] == {reason: 1}


@pytest.mark.parametrize('value', [-(1 << 63), (1 << 63) - 1, None, 42])
def test_bindable_scalar_values_and_integer_boundaries_are_preserved(tmp_path, monkeypatch, value):
    event = timeline.normalize_event({'timestamp': EPOCH, 'event_type': 'tool.completed',
                                      'source_record_id': 'synthetic-boundary'})
    event.update(duration_ms=value, correlation_id=value)
    monkeypatch.setattr(timeline, 'collect_session_events', lambda *a: [event])
    for name in ('collect_tool_events', 'collect_incident_events', 'collect_skill_events'):
        monkeypatch.setattr(timeline, name, lambda *a: [])
    store = storage.TelemetryStore(tmp_path / 'telemetry.db')
    result = timeline.collect_timeline(tmp_path, store)
    assert (result['written'], result['skipped'], result['invalid']) == (1, 0, 0)
    with closing(store._connect()) as c:
        row = c.execute('SELECT duration_ms,correlation_id FROM timeline_events').fetchone()
    assert tuple(row) == (value, str(value) if value is not None else None)
