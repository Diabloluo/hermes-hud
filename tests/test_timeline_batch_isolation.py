"""Atomic cold ingestion, executor isolation, and cancellation ordering."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import sqlite3
from pathlib import Path
import sys
import threading
import time

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'dashboard'))
from hud import storage, timeline
from test_cost_views_contract import fixture_db
from test_timeline_worker import setup_api


def events(n=100):
    return [timeline.normalize_event({'timestamp':1000+i,'event_type':'tool.completed',
        'source_record_id':f'fixture:{i}','summary':'synthetic event'}) for i in range(n)]


def source_fixture(monkeypatch, values):
    monkeypatch.setattr(timeline,'collect_session_events',lambda *a:values)
    for name in ('collect_tool_events','collect_incident_events','collect_skill_events'):
        monkeypatch.setattr(timeline,name,lambda *a:[])


def watermark(store):
    with closing(store._connect()) as con:
        row=con.execute("SELECT value FROM meta WHERE key='timeline_last_scan'").fetchone()
    return row[0] if row else None


def test_cold_ingestion_connections_are_bounded_and_counts_idempotent(tmp_path,monkeypatch):
    store=storage.TelemetryStore(tmp_path/'telemetry.db')
    values=events()+[events()[0],{'timestamp':1001},{'event_id':'bad','timestamp':None}]
    source_fixture(monkeypatch,values)
    original=store._connect;connections=[]
    def connect():
        con=original();connections.append(con);return con
    monkeypatch.setattr(store,'_connect',connect)
    result=timeline.collect_timeline(tmp_path,store)
    assert len(connections)<=3, 'cold ingestion must not open one connection per event'
    assert (result['written'],result['skipped'])==(100,3)
    assert watermark(store)==str(result['scan_started_at'])
    for con in connections:
        with pytest.raises(sqlite3.ProgrammingError):con.execute('SELECT 1')
    result=timeline.collect_timeline(tmp_path,store,force=True)
    assert (result['written'],result['skipped'])==(0,103)
    assert store.timeline_stats()['total']==100


def test_empty_scan_advances_watermark(tmp_path,monkeypatch):
    store=storage.TelemetryStore(tmp_path/'telemetry.db')
    source_fixture(monkeypatch,[])
    result=timeline.collect_timeline(tmp_path,store)
    assert (result['written'],result['skipped'])==(0,0)
    assert watermark(store)==str(result['scan_started_at'])


def test_bulk_defaults_match_single_event_writer(tmp_path):
    single=storage.TelemetryStore(tmp_path/'single.db')
    bulk=storage.TelemetryStore(tmp_path/'bulk.db')
    value={'event_id':'synthetic','timestamp':1000,'event_type':'tool.completed',
           'source_record_id':'fixture:defaults'}
    single.record_timeline_event(value)
    assert bulk.bulk_record_timeline_events([value])==1
    assert single.query_timeline()==bulk.query_timeline()


@pytest.mark.parametrize('failure',['event','watermark'])
def test_failed_ingestion_rolls_back_events_and_watermark(tmp_path,monkeypatch,failure):
    store=storage.TelemetryStore(tmp_path/'telemetry.db')
    with closing(store._connect()) as con,con:
        con.execute("INSERT INTO meta(key,value) VALUES('timeline_last_scan','123')")
        if failure=='event':
            con.execute("CREATE TRIGGER injected BEFORE INSERT ON timeline_events "
                "WHEN NEW.source_record_id='fixture:73' BEGIN SELECT RAISE(ABORT,'fixture failure'); END")
        else:
            con.execute("CREATE TRIGGER injected BEFORE INSERT ON meta "
                "WHEN NEW.key='timeline_last_scan' BEGIN SELECT RAISE(ABORT,'fixture failure'); END")
    source_fixture(monkeypatch,events())
    with pytest.raises(sqlite3.DatabaseError):timeline.collect_timeline(tmp_path,store)
    assert store.timeline_stats()['total']==0
    assert watermark(store)=='123'
    with closing(store._connect()) as con,con:con.execute('DROP TRIGGER injected')
    result=timeline.collect_timeline(tmp_path,store)
    assert result['written']==100 and store.timeline_stats()['total']==100
    assert watermark(store)==str(result['scan_started_at'])


def fresh_api(home,monkeypatch):
    api=setup_api(home,monkeypatch)
    # Respect the implementation under test; isolate loop-bound locks between tests.
    lock=asyncio.Lock() if isinstance(api._timeline_lock,asyncio.Lock) else threading.Lock()
    monkeypatch.setattr(api,'_timeline_lock',lock)
    monkeypatch.setattr(api,'_snapshot_lock',asyncio.Lock())
    monkeypatch.setattr(api,'_snapshot_cache',{})
    monkeypatch.setattr(api.collectors,'build_snapshot',lambda locale:{'synthetic':True})
    monkeypatch.setattr(api.rules,'evaluate_snapshot',lambda *a:{'overall':'normal'})
    monkeypatch.setattr(api,'_detect_events',lambda *a:[])
    monkeypatch.setattr(api,'_maybe_telemetry',lambda *a:None)
    return api


async def entered(event):
    end=time.monotonic()+2
    while not event.is_set():
        assert time.monotonic()<end,'worker did not enter'
        await asyncio.sleep(.001)


def test_timeline_waiters_leave_executor_capacity_for_snapshot(fixture_db,monkeypatch):
    _,home,_=fixture_db;api=fresh_api(home,monkeypatch)
    started=threading.Event();release=threading.Event();original=timeline.collect_timeline
    def slow(*a,**k):
        started.set();assert release.wait(3);return original(*a,**k)
    monkeypatch.setattr(timeline,'collect_timeline',slow)
    async def scenario():
        asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(max_workers=2))
        requests=[asyncio.create_task(api.get_timeline())]
        try:
            await entered(started)
            requests.extend(asyncio.create_task(api.get_timeline()) for _ in range(7))
            await asyncio.sleep(.03)
            snap=await asyncio.wait_for(api._get_snapshot('en'),timeout=.25)
            assert snap['synthetic']
        finally:
            release.set();await asyncio.gather(*requests,return_exceptions=True)
    asyncio.run(scenario())


def test_cancelled_active_request_drains_worker_before_releasing_lock(fixture_db,monkeypatch):
    _,home,_=fixture_db;api=fresh_api(home,monkeypatch)
    started=threading.Event();release=threading.Event();original=timeline.collect_timeline
    state={'calls':0,'active':0,'maximum':0};guard=threading.Lock()
    def slow(*a,**k):
        with guard:
            state['calls']+=1;call=state['calls'];state['active']+=1
            state['maximum']=max(state['maximum'],state['active'])
        try:
            if call==1:started.set();assert release.wait(3)
            return original(*a,**k)
        finally:
            with guard:state['active']-=1
    monkeypatch.setattr(timeline,'collect_timeline',slow)
    async def scenario():
        first=asyncio.create_task(api.get_timeline());second=None;waiting=None
        try:
            await entered(started);first.cancel();await asyncio.sleep(.02)
            first.cancel();second=asyncio.create_task(api.get_timeline())
            waiting=asyncio.create_task(api.get_timeline());await asyncio.sleep(.02);waiting.cancel()
            await asyncio.sleep(.02)
            assert not first.done(), 'cancellation must drain the still-running SQLite worker'
            assert state['calls']==1 and state['maximum']==1
            release.set()
            with pytest.raises(asyncio.CancelledError):await first
            await second
            with pytest.raises(asyncio.CancelledError):await waiting
            assert state['calls']==2 and state['maximum']==1
        finally:
            release.set()
            await asyncio.gather(*(r for r in (first,second,waiting) if r),return_exceptions=True)
    asyncio.run(scenario())
