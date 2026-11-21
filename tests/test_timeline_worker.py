"""Timeline IO remains in a worker, including actual SQLite lock contention."""
import asyncio
import sqlite3
import threading
import time
from contextlib import closing

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from test_cost_views_contract import fixture_db, add_usage


def setup_api(home, monkeypatch):
    from dashboard import plugin_api as api
    from hud import storage
    monkeypatch.setattr(api.collectors, 'HERMES_HOME', home)
    monkeypatch.setattr(api, 'store', storage.TelemetryStore(db_path=home/'telemetry.db'))
    return api


@pytest.mark.parametrize("locale,opened,resolved", [
    ("zh-CN", "事故已发生：Gateway 不存活", "事故已恢复：Gateway 不存活"),
    ("en", "Incident opened: Gateway is down", "Incident resolved: Gateway is down"),
    ("fr", "Incident ouvert : Gateway est arrêtée", "Incident résolu : Gateway est arrêtée"),
    ("ar", "حادثة مفتوحة: Gateway متوقفة", "تم حل الحادثة: Gateway متوقفة"),
])
def test_timeline_localizes_new_and_stored_incidents(tmp_path, monkeypatch, locale, opened, resolved):
    api = setup_api(tmp_path, monkeypatch)
    from hud import timeline

    now = int(time.time())
    title = "Gateway 不存活"
    api.store.upsert_incident("gateway:not-alive", "critical", title, "", now=now)
    stored = timeline.normalize_event({
        "event_type": "incident.resolved", "timestamp": now - 1, "source": "hud",
        "source_record_id": "incident:gateway:not-alive:resolved",
        "correlation_id": "incident:gateway:not-alive",
        "summary": f"Incident resolved: {title}",
    })
    assert api.store.record_timeline_event(stored)

    app = FastAPI()
    app.include_router(api.router)
    with TestClient(app) as client:
        first = client.get("/timeline", params={"limit": 1, "locale": locale})
        first.raise_for_status()
        assert first.json()["has_more"]
        newest, = first.json()["events"]
        assert newest["display_summary"] == opened
        assert newest["summary"] == f"Incident opened: {title}"

        page = client.get("/timeline", params={"limit": 1, "locale": locale,
                         "before": newest["timestamp"], "before_id": newest["event_id"]})
        page.raise_for_status()
        historical, = page.json()["events"]
        assert historical["display_summary"] == resolved
        assert historical["summary"] == stored["summary"]
        assert historical["event_id"] == stored["event_id"]

        legacy = client.get("/timeline").json()["events"]
        assert all("display_summary" not in event for event in legacy)
        with closing(api.store._connect()) as conn:
            assert conn.execute("SELECT summary FROM timeline_events WHERE event_id = ?",
                                (stored["event_id"],)).fetchone() == (stored["summary"],)


@pytest.mark.parametrize("source,fingerprint,title,expected", [
    ("hud", "channel:matrix:test:stale", "matrix:test 心跳过期", "matrix:test heartbeat stale"),
    ("hud", "channel:matrix:stale", "matrix 断开", "matrix disconnected"),
    ("hud", "cron:job:fail", "Cron 连续失败: 夜间任务", "Cron repeated failures: 夜间任务"),
    ("hud", "gateway:not-alive", "自定义健康事件", "自定义健康事件"),
    ("hermes", "gateway:not-alive", "Gateway 不存活", None),
])
def test_timeline_retains_recorded_names_and_custom_titles(source, fingerprint, title, expected):
    from dashboard.hud import timeline

    summary = f"Incident opened: {title}"
    event = {"source": source, "event_type": "incident.opened",
             "correlation_id": f"incident:{fingerprint}", "summary": summary}
    localized = timeline.with_display_summary(event, "en")
    assert localized["summary"] == summary
    assert localized.get("display_summary") == (f"Incident opened: {expected}" if expected else None)


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
