"""Synthetic process-read failures must not become a stopped-service incident."""
from types import SimpleNamespace

import pytest

from dashboard.hud import collectors, rules


def process(cmdline, **extra):
    return SimpleNamespace(info={
        "pid": 6363, "name": "python", "cmdline": cmdline,
        "create_time": 123.0, "memory_info": None, **extra,
    })


def install_rows(monkeypatch, rows):
    monkeypatch.setattr(collectors, "psutil", SimpleNamespace(
        process_iter=lambda fields: iter(rows)))


def dashboard_health(result, locale="zh"):
    return rules.evaluate_snapshot({"dashboard": result}, locale)


@pytest.mark.parametrize("locale", ["zh", "en", "fr", "ar"])
def test_unreadable_argv_remains_unknown_in_every_locale(monkeypatch, locale):
    # psutil.as_dict defaults AccessDenied/ZombieProcess attributes to None.
    install_rows(monkeypatch, [process(None)])
    result = collectors.collect_dashboard_procs(locale)
    assert result["error_key"] == "err_diagnostic_query"
    assert result["error"]
    assert result["procs"] == []
    health = dashboard_health(result, locale)
    assert "dashboard:" in health["unknown_incident_prefixes"]
    assert not any(i["fingerprint"] == "dashboard:not-running" for i in health["incidents"])


@pytest.mark.parametrize("broken", [
    SimpleNamespace(info={}),
    process(123),
    process("python3 -m hermes_cli.main dashboard"),
    process(["python3", None, "dashboard"]),
    process(["python3", "-m", "hermes_cli.main", "dashboard"], pid=None),
    process(["hermes", "dashboard"], pid=0),
    process(["hermes", "dashboard"], pid=True),
    process(["hermes", "dashboard"], memory_info=object()),
])
def test_malformed_or_missing_identity_is_unknown(monkeypatch, broken):
    install_rows(monkeypatch, [broken])
    result = collectors.collect_dashboard_procs()
    assert result["error_key"] == "err_diagnostic_query"
    assert result["procs"] == []


def test_per_process_read_failure_is_unknown_without_raw_exception(monkeypatch):
    class Broken:
        @property
        def info(self):
            raise PermissionError("SYNTHETIC_PRIVATE_DETAIL")
    install_rows(monkeypatch, [Broken()])
    result = collectors.collect_dashboard_procs()
    assert result["error_key"] == "err_diagnostic_query"
    assert "SYNTHETIC_PRIVATE_DETAIL" not in str(result)


@pytest.mark.parametrize("rows", [[], [process([])], [process(["python3", "worker.py"])]])
def test_complete_negative_observation_still_reports_stopped(monkeypatch, rows):
    install_rows(monkeypatch, rows)
    result = collectors.collect_dashboard_procs()
    assert result == {"procs": []}
    health = dashboard_health(result)
    assert "dashboard:" not in health["unknown_incident_prefixes"]
    assert any(i["fingerprint"] == "dashboard:not-running" for i in health["incidents"])


@pytest.mark.parametrize("unknown_first", [True, False])
def test_positive_dashboard_identity_survives_other_unreadable_processes(monkeypatch, unknown_first):
    known = process(["python3", "-m", "hermes_cli.main", "dashboard"])
    rows = [process(None), known] if unknown_first else [known, process(None)]
    install_rows(monkeypatch, rows)
    result = collectors.collect_dashboard_procs()
    assert "error" not in result
    assert [p["pid"] for p in result["procs"]] == [6363]
    # RSS is optional and its unavailability does not erase a valid identity.
    assert result["procs"][0]["rss"] is None
    health = dashboard_health(result)
    assert next(c["status"] for c in health["checks"] if c["key"] == "dashboard") == "normal"


def test_iterator_failure_keeps_existing_unknown_contract(monkeypatch):
    def rows(fields):
        yield process(["hermes", "dashboard"])
        raise RuntimeError("SYNTHETIC_PRIVATE_DETAIL")
    monkeypatch.setattr(collectors, "psutil", SimpleNamespace(process_iter=rows))
    result = collectors.collect_dashboard_procs()
    assert result["error_key"] == "err_diagnostic_query"
    assert [p["pid"] for p in result["procs"]] == [6363]
    assert "SYNTHETIC_PRIVATE_DETAIL" not in str(result)
    assert "dashboard:" in dashboard_health(result)["unknown_incident_prefixes"]


def test_no_psutil_remains_unknown(monkeypatch):
    monkeypatch.setattr(collectors, "psutil", None)
    result = collectors.collect_dashboard_procs()
    assert result["error"]
    assert "dashboard:" in dashboard_health(result)["unknown_incident_prefixes"]


def test_unknown_does_not_create_or_recover_a_dashboard_incident(tmp_path, monkeypatch):
    from dashboard import plugin_api as api
    from hud import storage
    store = storage.TelemetryStore(db_path=tmp_path / "telemetry.db")
    monkeypatch.setattr(api, "store", store)

    def refresh(rows):
        install_rows(monkeypatch, rows)
        snap = {"dashboard": collectors.collect_dashboard_procs()}
        health = rules.evaluate_snapshot(snap)
        api._update_telemetry(snap, health)
        return {i["fingerprint"] for i in store.list_incidents(active_only=True)}

    # Unavailable observation is not proof of an outage.
    assert "dashboard:not-running" not in refresh([process(None)])
    # A complete negative observation creates the outage.
    assert "dashboard:not-running" in refresh([])
    # A subsequent failed observation must not clear that known incident.
    assert "dashboard:not-running" in refresh([process(None)])
    # Observing the real process may finally recover it.
    assert "dashboard:not-running" not in refresh([process(["hermes", "dashboard"])])
