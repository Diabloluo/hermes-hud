"""R02 review F1/F2: synthetic mixed snapshots and isolated incident lifecycle."""
import pytest
from test_alert_semantics_frontend import render,find_key
from test_alert_semantics import evaluate,check

def assert_attention_check(result, key, severity):
    attention = next(node for node in result["tree"]["children"]
                     if node["props"].get("className") == "hud-attention")
    row = find_key(attention, key)
    assert set(row["props"]["className"].split()) == {"hud-incident", severity}
    assert row["children"][0].startswith("mixed-source fixture")


@pytest.mark.parametrize("severity", ["critical", "warning"])
@pytest.mark.parametrize("activity",["historical","inactive","unknown","current"])
@pytest.mark.parametrize("locale",["zh","en"])
def test_f1_health_severity_overrides_channel_snapshot(severity,activity,locale):
    result=render(locale,"Overview",{"gateway":{"platforms":{"sample":{"activity":activity,"state":"connected"}}}}, {"checks":[{"key":"channel:sample","severity":severity,"message":"mixed-source fixture"}]})
    assert_attention_check(result, "channel:sample", severity)

@pytest.mark.parametrize("severity", ["critical", "warning"])
@pytest.mark.parametrize("meta",[{"enabled":False},{"state":"paused"},{"state":"completed"},{"enabled":True,"inactive":True}])
def test_f1_health_severity_overrides_inactive_cron(severity,meta):
    result=render("en","Overview",{"cron":{"jobs":[{"id":"sample",**meta}]}}, {"checks":[{"key":"cron:sample","severity":severity,"message":"mixed-source fixture"}]})
    assert_attention_check(result, "cron:sample", severity)

@pytest.mark.parametrize("meta",[{"enabled":False},{"state":"paused"},{"state":"completed"},{"state":"disabled"},{"enabled":True,"paused_at":1},{"inactive":True}])
@pytest.mark.parametrize("prior_status",["active","pending_recovery"])
def test_f2_inactive_is_not_recovery_or_current_failure(tmp_path,monkeypatch,meta,prior_status):
    from dashboard import plugin_api as api
    from hud.storage import TelemetryStore
    store=TelemetryStore(db_path=tmp_path/"synthetic.db")
    monkeypatch.setattr(api,"store",store)
    fp="cron:sample:fail"
    store.upsert_incident(fp,"critical","fixture","historical failure",now=1000)
    if prior_status=="pending_recovery":store.mark_pending_recovery(fp,now=1001)
    before=next(i for i in store.list_incidents() if i["fingerprint"]==fp)
    health=evaluate(jobs=[{"id":"sample","name":"fixture","failure_streak":26,**meta}])
    assert check(health,"cron:sample")["severity"]=="normal"
    assert not any(i["fingerprint"]==fp for i in health["incidents"])
    assert "cron:sample:" in health["unknown_incident_prefixes"]
    api._update_telemetry({},health)
    item=next(i for i in store.list_incidents() if i["fingerprint"]==fp)
    assert item["status"]==prior_status
    assert item["count"]==before["count"]==1 and item["last_seen"]==before["last_seen"]


def test_f2_prefix_is_exact_and_does_not_hide_other_job_recovery(tmp_path,monkeypatch):
    from dashboard import plugin_api as api
    from hud.storage import TelemetryStore
    store=TelemetryStore(db_path=tmp_path/"synthetic.db");monkeypatch.setattr(api,"store",store)
    for fp in ["cron:sample:fail","cron:sample2:fail"]:store.upsert_incident(fp,"critical","fixture","old",now=1000)
    health=evaluate(jobs=[{"id":"sample","name":"old","enabled":False,"failure_streak":3},{"id":"sample2","name":"current","enabled":True,"failure_streak":0}])
    api._update_telemetry({},health)
    states={i["fingerprint"]:i["status"] for i in store.list_incidents()}
    assert states["cron:sample:fail"]=="active" and states["cron:sample2:fail"]=="recovered"


def test_f2_reenable_failure_is_current_and_clean_observation_can_recover(tmp_path,monkeypatch):
    from dashboard import plugin_api as api
    from hud.storage import TelemetryStore
    store=TelemetryStore(db_path=tmp_path/"synthetic.db");monkeypatch.setattr(api,"store",store)
    job={"id":"sample","name":"fixture","enabled":True,"failure_streak":3}
    failing=evaluate(jobs=[job]);assert check(failing,"cron:sample")["severity"]=="critical"
    api._update_telemetry({},failing)
    inactive=evaluate(jobs=[{**job,"enabled":False}]);api._update_telemetry({},inactive)
    assert next(i for i in store.list_incidents() if i["fingerprint"]=="cron:sample:fail")["status"]=="active"
    clean=evaluate(jobs=[{**job,"failure_streak":0}]);api._update_telemetry({},clean)
    assert next(i for i in store.list_incidents() if i["fingerprint"]=="cron:sample:fail")["status"]=="recovered"
