"""Offline synthetic state only. No real process, service or user data reads."""
import pytest
from dashboard.hud import collectors, rules

def evaluate(platform=None, jobs=None, disk=20):
    snap={"gateway":{"alive":True,"heartbeat_age":1,"platforms":{} if platform is None else {"sample":platform}},"db":{},"system":{"disk_free_percent":disk},"cron":{"jobs":jobs or []}}
    return rules.evaluate_snapshot(snap)

def check(result,key):
    return next(c for c in result["checks"] if c["key"]==key)

def collect(monkeypatch, platform, **top):
    state={"pid":101,"start_time":123,"updated_at":999,"platforms":{"sample":platform},**top}
    monkeypatch.setattr(collectors,"_read_json",lambda _:state)
    monkeypatch.setattr(collectors,"psutil",type("Fake",(),{"pid_exists":staticmethod(lambda _:True)}))
    monkeypatch.setattr(collectors,"_now_epoch",lambda:1000)
    return collectors.collect_gateway()["platforms"]["sample"]

@pytest.mark.parametrize("state",["connected","disconnected","degraded","retrying"])
def test_old_writer_is_historical_not_current(monkeypatch,state):
    p=collect(monkeypatch,{"state":state,"writer_pid":99,"writer_start_time":120,"updated_at":1,"needs_attention":True})
    assert p["activity"]=="historical"
    assert check(evaluate(p),"channel:sample")["severity"]=="normal"
    assert not any(i["fingerprint"].startswith("channel:") for i in evaluate(p)["incidents"])

@pytest.mark.parametrize("meta",[{}, {"writer_pid":101},{"writer_start_time":123},{"writer_pid":True,"writer_start_time":123},{"writer_pid":101,"writer_start_time":"bad"}])
def test_missing_writer_is_unknown(monkeypatch,meta):
    p=collect(monkeypatch,{"state":"connected",**meta})
    result=evaluate(p)
    assert p["activity"]=="unknown"
    assert check(result,"channel:sample")["severity"]=="warning"
    assert "channel:sample:" in result["unknown_incident_prefixes"]

@pytest.mark.parametrize("state",["disconnected","degraded","retrying"])
def test_current_real_failure_is_not_suppressed(monkeypatch,state):
    p=collect(monkeypatch,{"state":state,"writer_pid":101,"writer_start_time":123,"needs_attention":False})
    assert check(evaluate(p),"channel:sample")["severity"]=="critical"

@pytest.mark.parametrize("state",["disabled","stopped"])
def test_explicit_disabled_platform(monkeypatch,state):
    p=collect(monkeypatch,{"state":state,"writer_pid":101,"writer_start_time":123})
    # stopped is NOT evidence of operator disablement.
    assert check(evaluate(p),"channel:sample")["severity"] == ("normal" if state=="disabled" else "critical")

def test_status_time_is_not_heartbeat(monkeypatch):
    p=collect(monkeypatch,{"state":"connected","writer_pid":101,"writer_start_time":123,"updated_at":1})
    assert p["updated_at"]==1 and p["heartbeat_age"] is None
    assert p["timestamp_semantics"]=="status_update"
    assert check(evaluate(p),"channel:sample")["severity"]=="normal"

@pytest.mark.parametrize("source,age,expected",[("periodic",1,"normal"),("periodic",61,"warning"),(None,900,"normal"),("status_update",900,"normal"),("periodic",None,"normal")])
def test_only_verified_periodic_age_is_used(source,age,expected):
    p={"state":"connected","activity":"current","heartbeat_source":source,"heartbeat_age":age}
    assert check(evaluate(p),"channel:sample")["severity"]==expected

@pytest.mark.parametrize("metadata",[{"enabled":False},{"state":"paused"},{"state":"completed"},{"state":"disabled"},{"enabled":True,"paused_at":1}])
def test_inactive_cron_preserves_history_without_current_failure(monkeypatch,metadata):
    job={"id":"example","name":"synthetic","failure_streak":26,**metadata}
    monkeypatch.setattr(collectors,"_read_json",lambda _:{"jobs":[job]})
    result=collectors.collect_cron_jobs()
    assert result["jobs"][0]["failure_streak"]==26
    assert result["summary"]["failing"]==0
    assert result["summary"]["historical_failing"]==1
    assert result["summary"]["enabled"]==0
    assert check(evaluate(jobs=result["jobs"]),"cron:example")["severity"]=="normal"
    assert not any(i["fingerprint"].startswith("cron:") for i in evaluate(jobs=result["jobs"])["incidents"])

@pytest.mark.parametrize("meta",[{}, {"enabled":True},{"enabled":None},{"state":"error"}])
def test_legacy_or_active_failure_not_silenced(monkeypatch,meta):
    j={"id":"example","name":"synthetic","failure_streak":3,**meta}
    monkeypatch.setattr(collectors,"_read_json",lambda _:{"jobs":[j]})
    c=collectors.collect_cron_jobs()
    assert c["summary"]["failing"]==1
    assert check(evaluate(jobs=c["jobs"]),"cron:example")["severity"]=="critical"

@pytest.mark.parametrize("free,severity",[(0,"critical"),(4.99,"critical"),(5,"warning"),(7,"warning"),(14.99,"warning"),(15,"normal"),(100,"normal")])
def test_disk_thresholds_unchanged(free,severity):
    assert check(evaluate(disk=free),"disk")["severity"]==severity

@pytest.mark.parametrize("writer,expected",[({"writer_pid":101,"writer_start_time":122},"historical"),({"writer_pid":102,"writer_start_time":123},"historical"),({"writer_pid":101,"writer_start_time":123},"current"),({"writer_pid":101,"writer_start_time":float("nan")},"unknown"),({"writer_pid":101.0,"writer_start_time":123},"unknown")])
def test_identity_pairs_and_pid_reuse(monkeypatch,writer,expected):
    p=collect(monkeypatch,{"state":"connected",**writer})
    assert p["activity"]==expected

@pytest.mark.parametrize("top",[{"pid":None},{"start_time":None},{"pid":True},{"start_time":0}])
def test_gateway_identity_missing(monkeypatch,top):
    p=collect(monkeypatch,{"state":"connected","writer_pid":101,"writer_start_time":123},**top)
    assert p["activity"]=="unknown"

def test_current_connected_needs_attention_warns(monkeypatch):
    p=collect(monkeypatch,{"state":"connected","writer_pid":101,"writer_start_time":123,"needs_attention":True})
    assert check(evaluate(p),"channel:sample")["severity"]=="warning"
    assert any(i["fingerprint"]=="channel:sample:attention" for i in evaluate(p)["incidents"])

@pytest.mark.parametrize("state",[None,"unknown",""])
def test_current_writer_unknown_state_preserves_incidents(monkeypatch,state):
    p=collect(monkeypatch,{"state":state,"writer_pid":101,"writer_start_time":123})
    assert "channel:sample:" in evaluate(p)["unknown_incident_prefixes"]
    assert check(evaluate(p),"channel:sample")["severity"]=="warning"

def test_legacy_enabled_not_falsely_disabled(monkeypatch):
    monkeypatch.setattr(collectors,"_read_json",lambda _:{"jobs":[{"id":"legacy","failure_streak":1}]})
    result=collectors.collect_cron_jobs()
    assert result["jobs"][0]["enabled"] is None
    assert result["summary"]["disabled"]==0
    assert result["summary"]["enabled_unknown"]==1
    assert result["summary"]["failing"]==1

def test_fallback_metadata_keeps_inactivity(monkeypatch):
    monkeypatch.setattr(collectors,"_read_json",lambda _:{"jobs":[{"id":"fallback","name":"fixture","enabled":False,"failure_streak":4}]})
    def fail(_):raise ValueError("synthetic")
    monkeypatch.setattr(collectors,"_job_model",fail)
    result=collectors.collect_cron_jobs()
    assert result["summary"]["parse_warnings"]==1
    assert result["summary"]["failing"]==0
    assert result["jobs"][0]["inactive"] is True

@pytest.mark.parametrize("locale",["zh","en","fr","ar"])
def test_new_text_is_localized(locale):
    from dashboard.hud.i18n import t
    for key in ("channel_historical","channel_inactive","channel_unknown","channel_reported_connected","cron_inactive_history"):
        text=t(key,locale,name="sample",streak=3)
        assert text!=key and "sample" in text and "{" not in text

@pytest.mark.parametrize("activity",["historical","unknown"])
def test_noncurrent_keeps_existing_incident_unknown(tmp_path,monkeypatch,activity):
    from dashboard import plugin_api as api
    from hud.storage import TelemetryStore
    store=TelemetryStore(db_path=tmp_path/"synthetic.db")
    monkeypatch.setattr(api,"store",store)
    store.upsert_incident("channel:sample:disconnected","critical","old","synthetic",now=1000)
    health=evaluate({"state":"connected","activity":activity})
    # Exercise the production reconciliation API directly with synthetic data.
    api._update_telemetry({}, health)
    assert next(i for i in store.list_incidents(active_only=True) if i["fingerprint"]=="channel:sample:disconnected")["status"]=="active"

@pytest.mark.parametrize("meta,expected",[({"writer_pid":99,"writer_start_time":120},"historical"),({},"unknown"),({"writer_pid":101,"writer_start_time":123},"inactive")])
@pytest.mark.parametrize("disabled",[{"state":"disabled"},{"state":"disconnected","enabled":False}])
def test_disable_requires_current_provenance(monkeypatch,meta,expected,disabled):
    p=collect(monkeypatch,{**disabled,**meta})
    assert p["activity"]==expected
    health=evaluate(p)
    if expected!="inactive":assert "channel:sample:" in health["unknown_incident_prefixes"]
