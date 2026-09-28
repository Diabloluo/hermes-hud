"""Delegate WebSocket admission to Hermes across its router extraction.

Never implement token/ticket checks here or fall back after a host rejection.
Imports stay lazy: the plugin can load while Dashboard startup is in progress.
"""

from importlib import import_module
import logging

log = logging.getLogger(__name__)


def dashboard_ws_allowed(ws) -> bool:
    """Use the current host's request and credential gates; fail closed."""
    module_name = "hermes_cli.web_server_chat"
    try:
        try:
            host = import_module(module_name)
        except ModuleNotFoundError as exc:
            # Only absence of the extracted module denotes an older host.
            # Missing dependencies inside a modern host must not downgrade it.
            if exc.name != module_name:
                raise
            host = import_module("hermes_cli.web_server")
        return (host._ws_request_is_allowed(ws) is True
                and host._ws_auth_ok(ws) is True)
    except Exception:
        # Do not log URLs, credentials or exception text from an auth provider.
        log.warning("Dashboard WebSocket admission unavailable; refusing connection")
        return False
