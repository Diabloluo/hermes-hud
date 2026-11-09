"""Synthetic current-host ISO ledger and legacy epoch regression cases."""
import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from dashboard.hud import collectors

NOW = 1794230000.0


def iso(value, offset=0):
    return datetime.fromtimestamp(value, timezone(timedelta(hours=offset))).isoformat()


@pytest.mark.parametrize('encode', [lambda t:t, lambda t:str(t), iso, lambda t:iso(t,8), lambda t:iso(t,-5)])
def test_cron_summary_uses_30day_window_and_real_duration(tmp_path,monkeypatch,encode):
    cron=tmp_path/'cron';cron.mkdir();db=cron/'executions.db'
    conn=sqlite3.connect(db)
    # Column types and required fields follow Hermes v0.23 executions schema.
    conn.execute('CREATE TABLE executions (id TEXT PRIMARY KEY, job_id TEXT NOT NULL, source TEXT NOT NULL, process_id TEXT NOT NULL, pid INTEGER NOT NULL, status TEXT NOT NULL, claimed_at TEXT NOT NULL, started_at TEXT, finished_at TEXT, error TEXT)')
    for eid,claim,st in [('recent',NOW-60,'completed'),('old',NOW-60*86400,'failed')]:
        conn.execute('INSERT INTO executions VALUES (?,?,?,?,?,?,?,?,?,?)',(eid,'job','test','fixture',999999,st,encode(claim),encode(claim),encode(claim+30),None))
    conn.commit();conn.close()
    monkeypatch.setattr(collectors,'HERMES_HOME',tmp_path)
    monkeypatch.setattr(collectors.time,'time',lambda:NOW)
    before=hashlib.sha256(db.read_bytes()).hexdigest()
    result=collectors.collect_cron_executions(limit=1)
    summary=result['summary']['job']
    assert summary['runs']==1 and summary['completed']==1 and summary['failed']==0
    assert summary['total_seconds']==30.0
    assert hashlib.sha256(db.read_bytes()).hexdigest()==before


def test_malformed_and_missing_timestamps_remain_safe(tmp_path,monkeypatch):
    cron=tmp_path/'cron';cron.mkdir()
    conn=sqlite3.connect(cron/'executions.db')
    conn.execute('CREATE TABLE executions (id TEXT, job_id TEXT, source TEXT, status TEXT, claimed_at TEXT, started_at TEXT, finished_at TEXT, pid INTEGER,error TEXT)')
    conn.executemany('INSERT INTO executions VALUES (?,?,?,?,?,?,?,?,?)',[
        ('bad','invalid','test','failed','not-a-date','not-a-date','not-a-date',999999,None),
        ('unknown','job','test','unknown',iso(NOW-10),None,None,999999,None),
        ('missed','job','test','missed',iso(NOW-20),None,None,999999,None)])
    conn.commit();conn.close()
    monkeypatch.setattr(collectors,'HERMES_HOME',tmp_path)
    monkeypatch.setattr(collectors.time,'time',lambda:NOW)
    result=collectors.collect_cron_executions()
    assert 'error' not in result and 'invalid' not in result['summary']
    assert result['summary']['job']['runs']==2
    assert result['summary']['job']['unknown']==2
    assert result['summary']['job']['total_seconds']==0


@pytest.mark.parametrize('invalid',['NaN','Infinity','-Infinity'])
def test_nonfinite_values_cannot_poison_json(tmp_path,monkeypatch,invalid):
    import json
    cron=tmp_path/'cron';cron.mkdir()
    conn=sqlite3.connect(cron/'executions.db')
    conn.execute('CREATE TABLE executions (id TEXT,job_id TEXT,source TEXT,status TEXT,claimed_at TEXT,started_at TEXT,finished_at TEXT,pid INTEGER,error TEXT)')
    conn.executemany('INSERT INTO executions VALUES (?,?,?,?,?,?,?,?,?)',[
        ('invalid-claim','bad-job','test','failed',invalid,invalid,invalid,999999,None),
        ('invalid-start','job','test','completed',iso(NOW-20),invalid,iso(NOW-10),999999,None),
        ('invalid-finish','job','test','completed',iso(NOW-20),iso(NOW-20),invalid,999999,None)])
    conn.commit();conn.close()
    monkeypatch.setattr(collectors,'HERMES_HOME',tmp_path)
    monkeypatch.setattr(collectors.time,'time',lambda:NOW)
    result=collectors.collect_cron_executions()
    assert 'bad-job' not in result['summary']
    assert result['summary']['job']['runs']==2
    assert result['summary']['job']['total_seconds']==0
    json.dumps(result,allow_nan=False)


def test_mixed_time_formats_boundary_and_multiple_jobs(tmp_path,monkeypatch):
    cron=tmp_path/'cron';cron.mkdir()
    conn=sqlite3.connect(cron/'executions.db')
    conn.execute('CREATE TABLE executions (id TEXT,job_id TEXT,source TEXT,status TEXT,claimed_at TEXT,started_at TEXT,finished_at TEXT,pid INTEGER,error TEXT)')
    cutoff=NOW-30*86400
    rows=[
        ('old','job','test','failed',iso(cutoff-.001,8),iso(cutoff-.001),iso(cutoff+30),999999,None),
        ('edge','job','test','completed',str(cutoff),iso(cutoff,8),iso(cutoff+30,-5),999999,None),
        ('recent','job','test','completed',iso(NOW-30,-5),str(NOW-30),iso(NOW-10),999999,None),
        ('other','other-job','test','failed',iso(NOW-50),iso(NOW-50),iso(NOW-40),999999,None),
        ('backwards','other-job','test','failed',iso(NOW-20),iso(NOW-10),iso(NOW-20),999999,None)]
    conn.executemany('INSERT INTO executions VALUES (?,?,?,?,?,?,?,?,?)',rows);conn.commit();conn.close()
    monkeypatch.setattr(collectors,'HERMES_HOME',tmp_path)
    monkeypatch.setattr(collectors.time,'time',lambda:NOW)
    result=collectors.collect_cron_executions(limit=1)
    assert len(result['executions'])==1
    assert result['summary']['job']['runs']==2
    assert result['summary']['job']['failed']==0
    assert result['summary']['job']['total_seconds']==50
    assert result['summary']['other-job']['runs']==2
    assert result['summary']['other-job']['total_seconds']==10
