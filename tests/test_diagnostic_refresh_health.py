"""F1: real sampling/REST snapshot/health-event path across periodic expiry.

All OS collectors are synthetic. The sampler, build_snapshot, _get_snapshot,
rules and event comparison remain real; a clock crosses three 30-second periods.
"""
import asyncio
import threading
from types import SimpleNamespace

import pytest


def healthy_snapshot(diagnostics):
    return {
        'gateway': {'alive': True, 'state': 'running', 'pid': 4242,
                    'heartbeat_age': 0, 'platforms': {}},
        'system': {'disk_free_percent': 80, 'memory': {'percent': 40}},
        'db': {'error': None, 'today_sessions': {}},
        'errors': {'count_30m': 0}, 'cron': {'jobs': []},
        'active_sessions': [], **diagnostics,
    }


@pytest.mark.parametrize('platform', ['darwin', 'linux'])
@pytest.mark.parametrize('locale', ['zh', 'en', 'fr', 'ar'])
def test_periodic_refresh_keeps_healthy_overall_and_emits_no_health_change(
        tmp_path, monkeypatch, platform, locale):
    from dashboard import plugin_api as api
    from hud import sampling, storage

    clock = [0.0]
    timer = SimpleNamespace(monotonic=lambda: clock[0], time=lambda: 1900000000 + clock[0])
    monkeypatch.setattr(sampling, 'time', timer)
    monkeypatch.setattr(api, 'time', timer)
    monkeypatch.setattr(api.rules, 'time', timer)
    monkeypatch.setattr(api.collectors, 'time', timer)
    monkeypatch.setattr(api.collectors, 'sys', SimpleNamespace(platform=platform))
    monkeypatch.setattr(api.collectors, 'HERMES_HOME', tmp_path)
    sampler = sampling.BackgroundSamples(30)
    monkeypatch.setattr(api.collectors, '_DIAGNOSTIC_SAMPLES', sampler)
    monkeypatch.setattr(api, 'store', storage.TelemetryStore(db_path=tmp_path/'telemetry.db'))
    monkeypatch.setattr(api, '_snapshot_cache', {})
    monkeypatch.setattr(api, '_snapshot_lock', asyncio.Lock())
    monkeypatch.setattr(api, '_last_snapshot', None)
    monkeypatch.setattr(api, '_last_overall', None)
    monkeypatch.setattr(api, '_last_telemetry_ts', 0.0)
    calls = {'launchd': 0, 'dashboard': 0}

    def launchd(_locale):
        calls['launchd'] += 1
        return ({'managed': True, 'status': 'managed'} if platform == 'darwin'
                else {'managed': False, 'status': 'not_applicable'})

    def dashboard(_locale):
        calls['dashboard'] += 1
        return {'procs': [{'pid': 4242}]}

    monkeypatch.setattr(api.collectors, 'collect_launchd_check', launchd)
    monkeypatch.setattr(api.collectors, 'collect_dashboard_procs', dashboard)
    base = healthy_snapshot({})
    for collector, value in (
            ('collect_gateway', base['gateway']), ('collect_system', base['system']),
            ('collect_snapshot_db', base['db']), ('collect_cron_jobs', base['cron']),
            ('collect_cron_executions', {}), ('collect_logs', {}),
            ('collect_error_stats', base['errors']), ('collect_memory', {}),
            ('collect_active_sessions', [])):
        monkeypatch.setattr(api.collectors, collector, lambda *a, _value=value, **kw: _value)

    # No observation at cold start is intentionally unknown, not evidence of health.
    assert api.collectors.collect_snapshot_diagnostics(locale)['launchd']['sample_status'] == 'pending'
    sampler.wait_idle()
    previous = None
    boundaries = []

    async def scenario():
        nonlocal previous
        for elapsed in range(0, 94, 2):
            clock[0] = elapsed
            prior_overall = previous['_health']['overall'] if previous else None
            snap = await api._get_snapshot(locale)
            assert snap['_health']['overall'] == 'normal', (elapsed, snap['_health'])
            checks = {c['key']: c['status'] for c in snap['_health']['checks']}
            assert checks['launchd'] == checks['dashboard'] == 'normal'
            assert not snap['_health']['incidents']
            assert not any(e['type'] == 'health' for e in snap['_events'])
            # Exercise the actual health-event branch with populated health data,
            # as well as checking the events returned by the real snapshot route.
            api._last_overall = prior_overall
            assert not any(e['type'] == 'health' for e in api._detect_events(snap, previous))
            api._last_overall = snap['_health']['overall']
            if elapsed in (30, 60, 90):
                boundaries.append(snap['launchd']['sample_status'])
                assert snap['launchd']['sample_status'] == 'refreshing'
                assert snap['launchd']['sample_age_seconds'] == 30
            previous = snap
            sampler.wait_idle()

    try:
        asyncio.run(scenario())
        assert boundaries == ['refreshing'] * 3
        assert calls == {'launchd': 4, 'dashboard': 4}
    finally:
        sampler.wait_idle()
        sampler._pool.shutdown()


def test_slow_refresh_is_bounded_and_failed_result_stays_unknown(monkeypatch):
    from hud import sampling, rules

    clock = [0.0]
    monkeypatch.setattr(sampling, 'time', SimpleNamespace(
        monotonic=lambda: clock[0], time=lambda: 1900000000 + clock[0]))
    sampler = sampling.BackgroundSamples(30)
    release, started = threading.Event(), threading.Event()
    calls = []

    def collect():
        calls.append(1)
        if len(calls) > 1:
            started.set()
            assert release.wait(3)
            return {'error': 'synthetic collection failure', 'managed': None}
        return {'managed': True, 'status': 'managed'}

    def health(sample):
        return rules.evaluate_snapshot(healthy_snapshot({
            'launchd': sample, 'dashboard': {'procs': [{'pid': 4242}]}}))

    try:
        pending = sampler.read('launchd', collect, {'managed': None})
        assert pending['sample_status'] == 'pending'
        assert health(pending)['overall'] == 'warning'
        sampler.wait_idle()
        assert sampler.read('launchd', collect, {})['sample_status'] == 'ready'
        for age in (30, 59.999):
            clock[0] = age
            refreshing = sampler.read('launchd', collect, {})
            assert refreshing['sample_status'] == 'refreshing'
            assert health(refreshing)['overall'] == 'normal'
        assert started.wait(1)
        clock[0] = 60
        stale = sampler.read('launchd', collect, {})
        assert stale['sample_status'] == 'stale'
        assert 'launchd:' in health(stale)['unknown_incident_prefixes']
        assert health(stale)['overall'] == 'warning'
        release.set()
        sampler.wait_idle()
        failed = sampler.read('launchd', collect, {})
        assert failed['sample_status'] == 'unavailable'
        assert health(failed)['overall'] == 'warning'
    finally:
        release.set()
        sampler.wait_idle()
        sampler._pool.shutdown()


@pytest.mark.parametrize('service', ['launchd', 'dashboard'])
def test_completed_refresh_exposes_real_service_failure(monkeypatch, service):
    from dashboard import plugin_api as api
    from hud import sampling, rules

    clock = [0.0]
    monkeypatch.setattr(sampling, 'time', SimpleNamespace(
        monotonic=lambda: clock[0], time=lambda: 1900000000 + clock[0]))
    sampler = sampling.BackgroundSamples(30)
    calls = []

    def collect():
        calls.append(1)
        if service == 'launchd':
            return {'managed': len(calls) == 1, 'status': 'checked'}
        return {'procs': [{'pid': 4242}] if len(calls) == 1 else []}

    def snapshot(sample):
        return healthy_snapshot({
            'launchd': sample if service == 'launchd' else {'managed': True},
            'dashboard': sample if service == 'dashboard' else {'procs': [{'pid': 4242}]}})

    try:
        sampler.read(service, collect, {})
        sampler.wait_idle()
        sampler.read(service, collect, {})
        clock[0] = 30
        during = sampler.read(service, collect, {})
        assert during['sample_status'] == 'refreshing'
        assert rules.evaluate_snapshot(snapshot(during))['overall'] == 'normal'
        sampler.wait_idle()
        clock[0] = 32
        after = sampler.read(service, collect, {})
        snap = snapshot(after)
        snap['_health'] = rules.evaluate_snapshot(snap)
        assert after['sample_status'] == 'ready'
        assert snap['_health']['overall'] == 'warning'
        assert any(i['fingerprint'].startswith(service + ':') for i in snap['_health']['incidents'])
        monkeypatch.setattr(api, '_last_overall', 'normal')
        changes = [e for e in api._detect_events(snap, snapshot(during)) if e['type'] == 'health']
        assert len(changes) == 1 and changes[0]['to'] == 'warning'
    finally:
        sampler.wait_idle()
        sampler._pool.shutdown()
