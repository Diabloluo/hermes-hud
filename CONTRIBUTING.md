# Contributing

Thanks for considering a contribution to RelayGlance (formerly Hermes HUD). Keep it small, keep it safe.

## Dev setup

```bash
git clone https://github.com/Diabloluo/hermes-hud
cd hermes-hud
python3 -m venv .venv && source .venv/bin/activate
pip install pytest fastapi httpx
```

The plugin runs as a user-level Dashboard plugin at `~/.hermes/plugins/hermes-hud/`
(see README for install). Local iteration: symlink or copy the repo there and restart
`hermes dashboard`.

## Tests

```bash
HERMES_HOME="$(mktemp -d)" python -m pytest tests/ -q \
  --ignore=tests/performance_verify.py \
  --deselect=tests/test_secrets_scan.py::test_real_telemetry_readonly_scan
```

- Use an isolated `HERMES_HOME` for local runs. The existing `test_real_telemetry_readonly_scan` reads `Path.home() / ".hermes/hud"` directly, so changing `HERMES_HOME` alone does not isolate it. The command above explicitly excludes it. Run that optional live-data scan only with separate authorization.
- GUI / real-CLI tests may skip when their prerequisites are absent. Report skipped or excluded checks separately; a unit-suite pass is not complete installation or UI acceptance.
- New tests must use synthetic fixtures, not live data or real Telegram/Feishu requests.
- `tests/performance_verify.py` is a manual 10-minute benchmark; it never runs in CI.

## PR workflow

1. Branch from `main`: `git switch -c fix/your-change`
2. Make the change + tests; run the applicable suite with zero failures and report any skips/exclusions. Do not treat an old fixed test count as coverage.
3. Push and open a PR with a short, honest description
4. CI runs pytest across 3 Python versions × 2 OSes plus static checks; wait for green
5. GitGuardian scans every PR; if it flags something, fix the actual issue —
   do not silence scanners with broad ignore rules

## Security boundary

- **Never** read `~/.hermes/.env`, `auth.json`, or real credentials in code or tests
- **Never** modify Hermes core data (`state.db`, cron jobs, gateway) — HUD is read-only
- Any new output field must pass through `hud/redaction.py` before reaching API/telemetry/WebSocket
- New collectors follow the existing pattern: standalone function, internal try/except,
  returns `{"error": ...}` on failure, never raises
- Test fixtures may use synthetic credentials but must be low-entropy / runtime-assembled
  (no literal `password=`, no realistic-looking secrets) so secret scanners stay quiet
