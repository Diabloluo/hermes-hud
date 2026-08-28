# Security — Hermes HUD Desktop

In plain language, this is what the Desktop app does and does not do.

## Local-first

- Everything runs on **your machine**. HUD reads Hermes local data and
  shows it to you.
- **No outbound telemetry.** The app does not phone home, does not track
  installs, does not collect usage stats. What it shows is local.

## Localhost only

- The app talks to the Hermes Dashboard at **127.0.0.1 (localhost)** —
  your machine only. No internet connection is needed or used for
  observability.

## Hermes core data is read-only

- Hermes `state.db` and core stores are opened **read-only**. HUD never
  writes to Hermes core data.

## The remote HUD page has zero native capability

- The HUD page loaded from the Dashboard runs with **no native app powers**:
  no filesystem, no shell, no arbitrary commands, no native dialogs, no
  updater. It behaves like an ordinary web page talking to localhost.

## The app may start the local Dashboard

- If the Dashboard is not running, the app can start it for you with a
  fixed, safe command (`hermes dashboard --host 127.0.0.1 --port 9119
  --no-open`). No shell interpolation, no arbitrary command execution.
- The app never starts a *second* Dashboard if one is already running.

## Compatibility checks

- The app verifies HUD plugin compatibility (`api_schema_version == 1`;
  plugin version ≥ 1.1.0 per the frozen binary, public support baseline
  v1.1.1+) before showing HUD, and fails closed with a clear message
  otherwise.

## Alert helper (optional, separate)

- The optional `hud_alert.py` helper can push incident alerts to Telegram /
  Feishu if **you** configure credentials. That is separate from the
  Desktop app's own zero-outbound observability boundary — nothing in the
  Desktop app itself sends outbound notifications.
