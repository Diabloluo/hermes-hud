"""Snapshot sampling contracts: bounded queries, cadence and unknown states."""
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from dashboard.hud import collectors, rules, sampling
from test_cost_views_contract import fixture_db, add_usage


def test_active_message_queries_ignore_completed_history(fixture_db, monkeypatch):
    con, home, now = fixture_db
    con.execute('UPDATE sessions SET ended_at=NULL')
    con.execute('CREATE INDEX idx_messages_session ON messages(session_id,timestamp)')
    con.execute("INSERT INTO messages VALUES ('s','user','new',?)", (now-2,))
    con.commit()
    original = collectors._ro_connect
    work = {'vm': 0, 'sql': []}
    active_sql = ['']
    def connect(path, **kwargs):
        conn = original(path, **kwargs)
        def trace(sql):
            active_sql[0] = sql
            if 'FROM messages' in sql:
                work['sql'].append(sql)
        def progress():
            if 'FROM messages' in active_sql[0]:
                work['vm'] += 1
            return 0
        conn.set_trace_callback(trace);conn.set_progress_handler(progress, 1)
        return conn
    monkeypatch.setattr(collectors, '_ro_connect', connect)
    first = collectors.collect_active_sessions()
    first_work = work['vm']
    con.executemany('INSERT INTO messages VALUES (?,?,?,?)',
                    [('completed-history', 'user', 'old', now-100-i) for i in range(20000)])
    con.commit();work['vm'] = 0
    second = collectors.collect_active_sessions()
    assert [s['id'] for s in first] == [s['id'] for s in second] == ['s']
    assert abs(second[0]['idle_seconds']-2) <= 1
    assert work['vm'] < 128  # bounded indexed lookup; unrelated full scan would execute >20k instructions
    assert len(work['sql']) == 2
    assert all('WHERE session_id=' in sql and 'GROUP BY' not in sql for sql in work['sql'])
    con.execute('DELETE FROM messages WHERE session_id=?', ('s',));con.commit()
    assert collectors.collect_active_sessions()[0]['idle_seconds'] is None


def test_no_active_sessions_do_not_query_messages(fixture_db, monkeypatch):
    original = collectors._ro_connect;messages=[]
    def connect(path, **kwargs):
        conn = original(path, **kwargs)
        conn.set_trace_callback(lambda sql: messages.append(sql) if 'FROM messages' in sql else None)
        return conn
    monkeypatch.setattr(collectors, '_ro_connect', connect)
    assert collectors.collect_active_sessions() == []
    assert messages == []


def test_snapshot_db_cadence_wal_and_locale(fixture_db, monkeypatch):
    con, home, now = fixture_db
    add_usage(con, now, .5, 'estimated', 'fixture_prices')
    con.execute('PRAGMA journal_mode=WAL')
    clock=[100.0]
    monkeypatch.setattr(sampling, 'time', SimpleNamespace(monotonic=lambda:clock[0], time=lambda:now+clock[0]))
    monkeypatch.setattr(collectors, '_DB_SAMPLE', sampling.PeriodicSample(30))
    original=collectors._ro_connect;reads=[]
    def connect(path, **kwargs):
        reads.append(str(path));return original(path, **kwargs)
    monkeypatch.setattr(collectors, '_ro_connect', connect)
    first=collectors.collect_snapshot_db('zh')
    assert first['sessions_total'] == 1
    con.execute("UPDATE session_model_usage SET estimated_cost_usd=.7");con.commit()
    for locale in ('en', 'fr', 'ar', 'zh'):
        value=collectors.collect_snapshot_db(locale)
        assert value['model_usage']['estimated_cost_usd'] == .5
        assert value['sampled_at'] == first['sampled_at']
        value['model_usage']['estimated_cost_usd']=99 # responses cannot poison cache
    assert len(reads) == 1
    clock[0] += 30
    updated=collectors.collect_snapshot_db('en')
    assert updated['model_usage']['estimated_cost_usd'] == .7
    assert len(reads) == 2


def test_snapshot_db_replacement_errors_and_recovery(tmp_path, monkeypatch):
    monkeypatch.setattr(collectors, 'HERMES_HOME', tmp_path)
    monkeypatch.delenv('HUD_STATE_DB', raising=False)
    clock=[10.0];calls=[]
    monkeypatch.setattr(sampling, 'time', SimpleNamespace(monotonic=lambda:clock[0], time=lambda:clock[0]))
    monkeypatch.setattr(collectors, '_DB_SAMPLE', sampling.PeriodicSample(30))
    def fake(locale):
        calls.append(locale)
        if not (tmp_path/'state.db').exists():
            return {'error': '失败', 'error_key':'err_statedb_conn_failed', 'error_args':{}}
        return {'error':None,'sessions_total':len(calls)}
    monkeypatch.setattr(collectors, 'collect_db', fake)
    failed=collectors.collect_snapshot_db('en')
    assert failed['error'] != '失败'
    assert failed['sample_status'] == 'unavailable'
    collectors.collect_snapshot_db();assert len(calls) == 1
    clock[0]+=2;collectors.collect_snapshot_db();assert len(calls) == 2
    (tmp_path/'state.db').write_text('synthetic')
    assert collectors.collect_snapshot_db()['error'] is None
    assert len(calls) == 3
    replacement=tmp_path/'replacement';replacement.write_text('synthetic replacement')
    replacement.replace(tmp_path/'state.db')
    collectors.collect_snapshot_db();assert len(calls) == 4
    monkeypatch.setenv('HUD_TIMEZONE','Asia/Shanghai')
    collectors.collect_snapshot_db();assert len(calls) == 5


def test_midnight_forces_new_db_statistics(tmp_path, monkeypatch):
    monkeypatch.setattr(collectors,'HERMES_HOME',tmp_path)
    monkeypatch.setattr(collectors,'_DB_SAMPLE',sampling.PeriodicSample(30))
    calls=[];day=[1000.0]
    class ClockDate:
        @classmethod
        def now(cls,tz):return cls()
        def replace(self,**kwargs):return self
        def timestamp(self):return day[0]
    monkeypatch.setattr(collectors,'datetime',ClockDate)
    monkeypatch.setattr(collectors,'collect_db',lambda locale: (calls.append(locale) or {'error':None}))
    collectors.collect_snapshot_db();day[0]+=86400;collectors.collect_snapshot_db()
    assert len(calls)==2


def test_background_diagnostics_singleflight_and_expiry(monkeypatch):
    clock=[100.0]
    monkeypatch.setattr(sampling,'time',SimpleNamespace(monotonic=lambda:clock[0],time=lambda:clock[0]))
    sampler=sampling.BackgroundSamples(30)
    release=threading.Event();started=threading.Event();calls=[]
    def slow():
        calls.append(1);started.set();assert release.wait(3)
        return {'managed':True}
    try:
        first=sampler.read('x',slow,{'managed':None})
        assert first['sample_status']=='pending'
        assert started.wait(1)
        with ThreadPoolExecutor(max_workers=4) as pool:
            values=list(pool.map(lambda _:sampler.read('x',slow,{'managed':None}),range(12)))
        assert all(v['sample_status']=='pending' for v in values)
        assert len(calls)==1
        release.set();sampler.wait_idle()
        fresh=sampler.read('x',slow,{'managed':None})
        assert fresh['sample_status']=='ready' and fresh['managed']
        fresh['managed']=False
        assert sampler.read('x',slow,{})['managed'] is True
        clock[0]+=30
        assert sampler.read('x',slow,{})['sample_status']=='refreshing'
        sampler.wait_idle();assert len(calls)==2
    finally:
        release.set();sampler.wait_idle();sampler._pool.shutdown()


def test_diagnostics_share_across_locales_without_os_access(tmp_path, monkeypatch):
    sampler=sampling.BackgroundSamples(30)
    monkeypatch.setattr(collectors,'_DIAGNOSTIC_SAMPLES',sampler)
    monkeypatch.setattr(collectors,'HERMES_HOME',tmp_path)
    calls=[]
    monkeypatch.setattr(collectors,'collect_launchd_check',lambda locale: (calls.append('launchd') or {'managed':True}))
    monkeypatch.setattr(collectors,'collect_dashboard_procs',lambda locale: (calls.append('process') or {'procs':[{'pid':1}]}))
    try:
        collectors.collect_snapshot_diagnostics('zh');sampler.wait_idle()
        for locale in ('en','fr','ar','zh'):
            assert collectors.collect_snapshot_diagnostics(locale)['launchd']['sample_status']=='ready'
        assert sorted(calls)==['launchd','process']
    finally:
        sampler.wait_idle();sampler._pool.shutdown()


def test_unknown_diagnostics_do_not_create_or_recover_false_incidents(tmp_path, monkeypatch):
    from dashboard import plugin_api as api
    from hud import storage
    store=storage.TelemetryStore(db_path=tmp_path/'telemetry.db')
    monkeypatch.setattr(api,'store',store)
    for fp in ('launchd:not-managed','dashboard:not-running','logs:error-burst'):
        store.upsert_incident(fp,'warning','synthetic','synthetic')
    snap={'launchd':{'sample_status':'pending'},'dashboard':{'sample_status':'stale'},
          'errors':{'count_30m':None,'error':'timestamp unavailable'}}
    health=rules.evaluate_snapshot(snap)
    assert not any(i['fingerprint'].startswith(('launchd:','dashboard:','logs:')) for i in health['incidents'])
    api._update_telemetry(snap,health)
    active={i['fingerprint'] for i in store.list_incidents(active_only=True)}
    assert {'launchd:not-managed','dashboard:not-running','logs:error-burst'} <= active


def test_launchctl_failure_is_unknown(tmp_path, monkeypatch):
    import subprocess
    monkeypatch.setattr(collectors.sys,'platform','darwin')
    monkeypatch.setenv('HOME',str(tmp_path))
    monkeypatch.setattr(subprocess,'run',lambda *args,**kwargs: (_ for _ in ()).throw(subprocess.TimeoutExpired('synthetic',5)))
    value=collectors.collect_launchd_check()
    assert value['managed'] is None
    assert value['error'] and value['status']=='unavailable'
