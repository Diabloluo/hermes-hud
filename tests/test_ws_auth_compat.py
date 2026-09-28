"""Synthetic-only WS admission tests: no live HOME, credentials or providers."""

import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dashboard"))
from hud import ws_auth

MODERN = "hermes_cli.web_server_chat"
LEGACY = "hermes_cli.web_server"


def _host(request=True, auth=True):
    return types.SimpleNamespace(
        _ws_request_is_allowed=lambda ws: request,
        _ws_auth_ok=lambda ws: auth,
    )


def _imports(monkeypatch, modern=None, legacy=None, failure=None):
    calls = []

    def load(name):
        calls.append(name)
        if name == MODERN:
            if failure is not None:
                raise failure
            if modern is not None:
                return modern
            raise ModuleNotFoundError(name=MODERN)
        if legacy is None:
            raise ModuleNotFoundError(name=LEGACY)
        return legacy

    monkeypatch.setattr(ws_auth, "import_module", load)
    return calls


@pytest.mark.parametrize("layout", ["modern", "legacy"])
@pytest.mark.parametrize("request_allowed,auth,allowed", [
    (True, True, True), (False, True, False), (True, False, False),
    (False, False, False), (True, "truthy-but-not-bool", False),
])
def test_delegate_both_gates(monkeypatch, layout, request_allowed, auth, allowed):
    host = _host(request_allowed, auth)
    calls = _imports(monkeypatch, **{layout: host})
    assert ws_auth.dashboard_ws_allowed(object()) is allowed
    assert calls == ([MODERN] if layout == "modern" else [MODERN, LEGACY])


def test_modern_rejection_never_uses_permissive_legacy(monkeypatch):
    calls = _imports(monkeypatch, modern=_host(auth=False), legacy=_host())
    assert not ws_auth.dashboard_ws_allowed(object())
    assert calls == [MODERN]


@pytest.mark.parametrize("failure", [
    ModuleNotFoundError("broken dependency", name="missing_dependency"), ImportError("broken host"),
    RuntimeError("broken initialization"),
])
def test_import_failure_never_downgrades(monkeypatch, failure, caplog):
    calls = _imports(monkeypatch, legacy=_host(), failure=failure)
    assert not ws_auth.dashboard_ws_allowed(object())
    assert calls == [MODERN]
    assert str(failure) not in caplog.text


def test_missing_helpers_fail_closed(monkeypatch):
    calls = _imports(monkeypatch, modern=types.SimpleNamespace(), legacy=_host())
    assert not ws_auth.dashboard_ws_allowed(object())
    assert calls == [MODERN]


def test_no_supported_host_fails_closed(monkeypatch):
    _imports(monkeypatch)
    assert not ws_auth.dashboard_ws_allowed(object())


def test_request_rejection_does_not_consume_ticket(monkeypatch):
    def unexpected(ws):
        pytest.fail("invalid origin/peer must not consume a ticket")

    host = _host(request=False)
    host._ws_auth_ok = unexpected
    _imports(monkeypatch, modern=host)
    assert not ws_auth.dashboard_ws_allowed(object())


def test_auth_exception_is_closed_and_sanitized(monkeypatch, caplog):
    marker = "synthetic-provider-error-not-for-logs"

    def broken(ws):
        raise RuntimeError(marker)

    host = _host()
    host._ws_auth_ok = broken
    _imports(monkeypatch, modern=host, legacy=_host())
    assert not ws_auth.dashboard_ws_allowed(object())
    assert marker not in caplog.text


@pytest.mark.parametrize("layout", ["modern", "legacy"])
@pytest.mark.parametrize("credential,allowed", [("valid", True), ("invalid", False), ("", False)])
def test_real_asgi_route_admits_or_rejects_before_snapshot(monkeypatch, tmp_path, layout, credential, allowed):
    fastapi = pytest.importorskip("fastapi")
    if not hasattr(fastapi, "FastAPI"):
        pytest.skip("FastAPI stub is not an ASGI server")
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    import plugin_api

    host = _host()
    host._ws_auth_ok = lambda ws: ws.query_params.get("credential") == "valid"
    _imports(monkeypatch, **{layout: host})
    collected = []

    async def snapshot(locale):
        collected.append(locale)
        return {"_health": {"overall": "normal", "counts": {}}, "cron": {}}

    monkeypatch.setattr(plugin_api, "_get_snapshot", snapshot)
    app = fastapi.FastAPI()
    app.include_router(plugin_api.router)
    with TestClient(app) as client:
        if allowed:
            with client.websocket_connect("/events?locale=ar&credential=" + credential) as ws:
                assert ws.receive_json()["schema_version"] == 1
            assert collected == ["ar"]
        else:
            with pytest.raises(WebSocketDisconnect) as error:
                with client.websocket_connect("/events?credential=" + credential):
                    pytest.fail("unauthorized socket was accepted")
            assert error.value.code == 1008
            assert collected == []
