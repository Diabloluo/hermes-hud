"""Production-format timezone, clock bounds and uncertainty regressions."""
import os
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from dashboard.hud import collectors, rules


@pytest.fixture
def process_tz(monkeypatch):
    original=os.environ.get('TZ')
    def set_zone(zone):
        monkeypatch.setenv('TZ',zone);time.tzset()
    yield set_zone
    if original is None:os.environ.pop('TZ',None)
    else:os.environ['TZ']=original
    time.tzset()


@pytest.mark.parametrize('zone', ['UTC','Asia/Shanghai','America/Los_Angeles'])
def test_local_log_timestamps_are_recent_in_producer_timezone(process_tz, monkeypatch, tmp_path, zone):
    process_tz(zone)
    monkeypatch.delenv('HUD_LOG_TIMEZONE',raising=False)
    monkeypatch.setenv('HUD_TIMEZONE','Pacific/Auckland') # statistics TZ is unrelated
    monkeypatch.setattr(collectors,'HERMES_HOME',tmp_path)
    now=time.time();logdir=tmp_path/'logs';logdir.mkdir()
    recent=datetime.fromtimestamp(now-60).strftime('%Y-%m-%d %H:%M:%S')+',123 ERROR synthetic'
    old=datetime.fromtimestamp(now-8*3600).strftime('%Y-%m-%d %H:%M:%S')+',000 ERROR synthetic old'
    (logdir/'errors.log').write_text(recent+'\n'+old+'\n')
    result=collectors.collect_error_stats()
    assert result['count_30m']==1
    assert result['timestamp_status']=='known'


@pytest.mark.parametrize('header', ['2026-09-30T01:02:03Z','2026-09-30 09:02:03+08:00',
    '2026-09-30 09:02:03+0800','2026-09-30 09:02:03 +08:00','2026-09-29T18:02:03-07:00',
    '2026-09-30T01:02:03.123Z','2026-09-30 09:02:03,123+08:00'])
def test_explicit_offsets_are_independent_of_local_time(header, process_tz):
    process_tz('America/Los_Angeles')
    expected=datetime(2026,9,30,1,2,3,tzinfo=timezone.utc).timestamp()
    result=collectors._extract_log_ts(header+' ERROR synthetic')
    assert result==pytest.approx(expected+(.123 if '123' in header else 0))


def test_configured_producer_zone_is_used(process_tz,monkeypatch):
    process_tz('UTC');monkeypatch.setenv('HUD_LOG_TIMEZONE','Asia/Shanghai')
    assert collectors._extract_log_ts('2026-09-30 09:02:03 ERROR synthetic')==datetime(
        2026,9,30,1,2,3,tzinfo=timezone.utc).timestamp()
    monkeypatch.setenv('HUD_LOG_TIMEZONE','invalid/zone')
    assert collectors._extract_log_ts('2026-09-30 09:02:03 ERROR synthetic') is None


@pytest.mark.parametrize('header', ['2026-11-01 01:30:00','2026-03-08 02:30:00'])
@pytest.mark.parametrize('configured', [True,False])
def test_dst_ambiguous_or_nonexistent_time_is_unknown(header,configured,process_tz,monkeypatch):
    process_tz('America/Los_Angeles')
    if configured:monkeypatch.setenv('HUD_LOG_TIMEZONE','America/Los_Angeles')
    else:monkeypatch.delenv('HUD_LOG_TIMEZONE',raising=False)
    assert collectors._extract_log_ts(header+' ERROR synthetic') is None
    assert collectors._extract_log_ts('2026-11-01 01:30:00-07:00 ERROR synthetic') is not None


def test_window_boundary_and_future_records(tmp_path,monkeypatch):
    monkeypatch.setattr(collectors,'HERMES_HOME',tmp_path)
    now=datetime(2026,9,30,12,tzinfo=timezone.utc).timestamp()
    monkeypatch.setattr(collectors.time,'time',lambda:now)
    logdir=tmp_path/'logs';logdir.mkdir()
    def line(ts):return datetime.fromtimestamp(ts,timezone.utc).isoformat()+' ERROR synthetic'
    (logdir/'errors.log').write_text('\n'.join(line(ts) for ts in (now-1800,now-1801,now,now+1)))
    result=collectors.collect_error_stats()
    assert result['count_30m']==2
    assert result['future_records']==1


def test_unknown_log_format_never_looks_like_zero(tmp_path,monkeypatch):
    monkeypatch.setattr(collectors,'HERMES_HOME',tmp_path)
    logdir=tmp_path/'logs';logdir.mkdir()
    path=logdir/'errors.log';path.write_text('ERROR synthetic without timestamp\n')
    result=collectors.collect_error_stats()
    assert result['count_30m'] is None and result['error']
    health=rules.evaluate_snapshot({'errors':result})
    assert next(c for c in health['checks'] if c['key']=='error_burst')['status']=='warning'
    assert 'logs:' in health['unknown_incident_prefixes']
    path.write_text('')
    assert collectors.collect_error_stats()['count_30m']==0


def test_mixed_unknown_is_explicitly_partial(tmp_path,monkeypatch):
    monkeypatch.setattr(collectors,'HERMES_HOME',tmp_path)
    logdir=tmp_path/'logs';logdir.mkdir()
    line=datetime.now(timezone.utc).isoformat()+' ERROR synthetic'
    (logdir/'errors.log').write_text(line+'\nERROR missing time\n  File synthetic.py, line 1\n')
    result=collectors.collect_error_stats()
    assert result['count_30m']==1
    assert result['timestamp_status']=='partial'
    assert 'logs:' in rules.evaluate_snapshot({'errors':result})['unknown_incident_prefixes']


def test_message_embedded_timestamp_is_not_a_header():
    assert collectors._extract_log_ts('ERROR payload timestamp=2026-09-30 12:00:00') is None
