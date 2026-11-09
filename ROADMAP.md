# Roadmap

Updated 2026-11-09. Items below are not committed delivery dates. Maintenance
comes before expanding the product; the [frozen strategy](docs/strategy/STRATEGIC_DIRECTION.md)
does not authorize a rename, a second adapter or a Plugin SDK build.

## Completed

- macOS Desktop Alpha 0.1.0 public release, Developer ID signing and Apple
  notarization (`desktop-v0.1.0-alpha`, 2026-08-29).
- HUD UI languages: Chinese, English, French and Arabic (RTL), shipped in
  plugin 1.2.0 (2026-09-28). Host UI language coverage still depends on Hermes.
- Plugin 1.2.2 data-contract corrections (2026-11-01); Desktop remains 0.1.0.

## Now

- Small compatibility and correctness fixes for the existing Hermes adapter,
  including the Cron aggregate timestamp defect found in the
  [0.23.0 check](docs/quality/HERMES_023_COMPATIBILITY_20261109.md).
- Keep cost provenance, unknown-state handling and incident recovery reliable.
- Community feedback on Timeline / Skill Analytics / Cost Intelligence.
- Record fresh-install, Web UI and Desktop acceptance separately from backend
  checks. The 0.23.0 isolated backend check does not complete those stages.

## Next checks (not shipping commitments)

- A pinned Hermes 0.23 compatibility lane alongside the existing 0.19
  fresh-install lane, without silently dropping older-version coverage.
- Linux real-machine compatibility verification (community testing welcome).
- Refresh external-use evidence without equating downloads or stars with users;
  keep historical validation snapshots intact.

## Exploring (not active development)

- Plugin SDK / first external collector only after the existing strategy's
  demand gate and a separate product decision.
- Multi-agent observability, collector ecosystem and marketplace / templates.
- Linux / Windows Desktop feasibility and a mobile companion.
- One-command plugin + alert-helper installer and precise tool start/end events.
- Billing sync with provider dashboards, if a verified billing source is added.
  Current recorded costs are not provider invoices.
