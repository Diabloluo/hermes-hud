"""Activity without pricing rows must not be advertised as complete/free."""
import hashlib

import pytest

from dashboard.hud import collectors
from test_cost_views_contract import add_usage, fixture_db  # noqa: F401


def usage_views():
    usage = collectors.collect_usage()
    assert "error" not in usage
    return [usage["totals"], *usage["by_day"], *usage["by_model"]]


def test_missing_usage_matches_session_contract_over_http(fixture_db, monkeypatch):
    con, home, now = fixture_db
    monkeypatch.setenv("HERMES_HOME", str(home))
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from dashboard import plugin_api as api

    monkeypatch.setattr(api.collectors, "HERMES_HOME", home)
    before = hashlib.sha256((home / "state.db").read_bytes()).hexdigest()
    app = FastAPI()
    app.include_router(api.router, prefix="/api/plugins/hermes-hud")
    with TestClient(app) as client:
        prefix = "/api/plugins/hermes-hud"
        detail = client.get(prefix + "/sessions/s").json()
        sessions = client.get(prefix + "/sessions").json()
        usage = client.get(prefix + "/usage").json()
    assert not detail["cost_complete"]
    assert not sessions[0]["cost_complete"]
    for view in [usage["totals"], *usage["by_day"], *usage["by_model"]]:
        assert not view["cost_complete"]
        assert view["sessions_without_usage"] == 1
        assert view["pricing_coverage_ratio"] is None
        assert view["usage_rows"] == 0
        assert view["est_cost"] == 0  # Known subtotal, not a complete/free bill.
    assert hashlib.sha256((home / "state.db").read_bytes()).hexdigest() == before


@pytest.mark.parametrize("same_model", [True, False])
def test_known_cost_does_not_hide_session_without_usage(fixture_db, same_model):
    con, home, now = fixture_db
    add_usage(con, now, .5, "estimated", "fixture_prices")
    con.execute("INSERT INTO sessions SELECT 'orphan', source, user_id, ?, started_at,"
                " ended_at, title, message_count, tool_call_count, input_tokens,"
                " output_tokens, cache_read_tokens, cache_write_tokens, reasoning_tokens,"
                " estimated_cost_usd, actual_cost_usd, cost_status, cost_source,"
                " end_reason, cwd, billing_provider FROM sessions WHERE id='s'",
                ("m" if same_model else "other",))
    con.commit()
    usage = collectors.collect_usage()
    assert not collectors.collect_session_detail("orphan")["cost_complete"]
    assert collectors.collect_session_detail("s")["cost_complete"]
    for view in [usage["totals"], *usage["by_day"],
                 next(v for v in usage["by_model"] if v["model"] ==
                      ("m" if same_model else "other"))]:
        assert not view["cost_complete"]
        assert view["sessions_without_usage"] == 1
    assert usage["totals"]["est_cost"] == .5
    assert usage["totals"]["usage_rows"] == 1
    assert usage["totals"]["pricing_unknown_rows"] == 0
    if not same_model:
        priced = next(v for v in usage["by_model"] if v["model"] == "m")
        assert priced["cost_complete"]
        assert priced["sessions_without_usage"] == 0


def test_empty_database_remains_complete_zero(fixture_db):
    con, home, now = fixture_db
    con.execute("DELETE FROM sessions")
    con.commit()
    usage = collectors.collect_usage()
    assert usage["by_day"] == usage["by_model"] == usage["by_task"] == []
    assert usage["totals"]["cost_complete"]
    assert usage["totals"]["est_cost"] == 0
    assert usage["totals"]["sessions_without_usage"] == 0


@pytest.mark.parametrize("estimate", [0, .5])
def test_recorded_priced_session_remains_complete(fixture_db, estimate):
    con, home, now = fixture_db
    add_usage(con, now, estimate, "estimated", "fixture_prices")
    for view in usage_views():
        assert view["cost_complete"]
        assert view["sessions_without_usage"] == 0
        assert view["est_cost"] == estimate


def test_recent_activity_with_only_out_of_window_pricing_is_incomplete(fixture_db):
    con, home, now = fixture_db
    add_usage(con, now, .5, "estimated", "fixture_prices")
    con.execute("UPDATE session_model_usage SET last_seen=?", (now - 31 * 86400,))
    con.commit()
    # Lifetime session pricing and window usage answer different questions.
    assert collectors.collect_session_detail("s")["cost_complete"]
    for view in usage_views():
        assert not view["cost_complete"]
        assert view["sessions_without_usage"] == 0
        assert view["usage_rows"] == 0


def test_unpriced_record_stays_unknown_without_inventing_missing_rows(fixture_db):
    con, home, now = fixture_db
    add_usage(con, now, .5, None, None)
    for view in usage_views():
        assert not view["cost_complete"]
        assert view["sessions_without_usage"] == 0
        assert view["pricing_unknown_rows"] == 1
        assert view["est_cost"] == 0
