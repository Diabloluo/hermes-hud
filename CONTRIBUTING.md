# Contributing

Thanks for considering a contribution to Hermes HUD. Keep it small, keep it safe.

## Dev setup

```bash
git clone https://github.com/Diabloluo/hermes-hud
cd hermes-hud
python3 -m venv .venv && source .venv/bin/activate
pip install pytest
```

The plugin runs as a user-level Dashboard plugin at `~/.hermes/plugins/hermes-hud/`
(see README for install). Local iteration: symlink or copy the repo there and restart
`hermes dashboard`.

## Tests

```bash
python -m pytest tests/ -q --ignore=tests/performance_verify.py
```

- All tests run against `tmp_path` fixtures — **no real `~/.hermes`, no network, no real Telegram/Feishu**.
- Keep it that way: never add a test that reads live data or sends real requests.
- `tests/performance_verify.py` is a manual 10-minute benchmark; it never runs in CI.

## PR workflow

1. Branch from `main`: `git switch -c fix/your-change`
2. Make the change + tests; run the full suite (must stay 84+ passed, 0 failed)
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
