"""Timeline IO remains in a worker, including actual SQLite lock contention."""
import asyncio
import sqlite3
import threading
import time

from test_cost_views_contract import fixture_db, add_usage


def setup_api(home, monkeypatch):
    from dashboard import plugin_api as api
    from hud import storage
    monkeypatch.setattr(api.collectors, 'HERMES_HOME', home)
    monkeypatch.setattr(api, 'store', storage.TelemetryStore(db_path=home/'telemetry.db'))
    return api


def test_all_timeline_sqlite_connections_are_closed_on_worker(fixture_db, monkeypatch):
    con, home, now = fixture_db
    add_usage(con, now, .5, 'estimated', 'fixture_prices')
    api = setup_api(home, monkeypatch)
    original=sqlite3.connect;connections=[];main=threading.get_ident()
    class Tracked(sqlite3.Connection):
        closed=False
        def close(self):
            self.closed=True
            super().close()
    def connect(*args,**kwargs):
        kwargs['factory']=Tracked
        value=original(*args,**kwargs)
        connections.append((value,threading.get_ident()))
        return value
    monkeypatch.setattr(sqlite3,'connect',connect)
    result=asyncio.run(api.get_timeline(limit=1))
    assert len(result['events'])==1 and result['has_more']
    assert connections
    assert all(thread!=main for _,thread in connections)
    assert all(connection.closed for connection,_ in connections)


def test_slow_timeline_collection_does_not_block_other_coroutines(fixture_db,monkeypatch):
    from hud import timeline
    con,home,now=fixture_db
    api=setup_api(home,monkeypatch)
    original=timeline.collect_timeline
    entered=threading.Event();release=threading.Event()
    def slow(*args,**kwargs):
        entered.set();assert release.wait(2)
        return original(*args,**kwargs)
    monkeypatch.setattr(timeline,'collect_timeline',slow)
    async def scenario():
        start=time.perf_counter();request=asyncio.create_task(api.get_timeline())
        try:
            while not entered.is_set():
                await asyncio.sleep(.001)
            await asyncio.sleep(.02)
            assert time.perf_counter()-start < .5
            assert not request.done()
        finally:release.set()
        return await request
    assert asyncio.run(scenario())['events']


def test_real_telemetry_lock_does_not_block_event_loop(fixture_db,monkeypatch):
    con,home,now=fixture_db
    api=setup_api(home,monkeypatch)
    def bounded_connect():return sqlite3.connect(home/'telemetry.db',timeout=.1)
    monkeypatch.setattr(api.store,'_connect',bounded_connect)
    locker=sqlite3.connect(home/'telemetry.db');locker.execute('BEGIN IMMEDIATE')
    async def scenario():
        async def ticker():
            await asyncio.sleep(.01);return time.perf_counter()
        start=time.perf_counter();tick=asyncio.create_task(ticker())
        result=await api.get_timeline()
        assert (await tick)-start < .1
        return result
    try:assert asyncio.run(scenario())['events']==[]
    finally:locker.rollback();locker.close()
