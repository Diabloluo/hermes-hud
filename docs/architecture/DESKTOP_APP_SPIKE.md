# Desktop App Architecture Spike — ADR

Status: **Accepted (spike-level)** · Date: 2026-08-26 · Baseline: released v1.1.0
Scope: research + minimal architecture decision. **No** full Desktop App build this phase.

## Context

Hermes HUD currently runs as a user-level Dashboard plugin (`dashboard/plugin_api.py`
+ `dashboard/dist/index.js`), served by the Hermes Dashboard (FastAPI) at
`127.0.0.1:<port>/hud`, authenticated by the Dashboard's loopback session token.
v1.1.0 shipped Agent Timeline, Skill Analytics and Cost Intelligence as stable
REST/WS endpoints. We want a native-feeling **Hermes HUD.app** that shares the
same business logic (no second backend, no forked aggregation).

```
Hermes Agent (state.db read-only)
        ↓
HUD Core / Backend API  (plugin_api.py — FastAPI, 21 REST + 1 WS)
        ↓
┌──────────────┬───────────────┐
│ Web Client   │ Desktop Client│
└──────────────┴───────────────┘
```

## Constraints

- Desktop **must not** read `state.db` directly as its primary interface — HUD
  Backend API only (parity with Web client).
- No rewriting of verified Timeline / Skill Analytics / Cost Intelligence.
- No second cost surface; `/cost/*` stays canonical.
- 127.0.0.1 only by default; auth required; no raw secrets to JS.
- No tag / release this phase.

## Options Considered

### A. Tauri 2 vs Electron

| Criterion | Tauri 2 | Electron | Verdict for HUD |
|---|---|---|---|
| Bundle size | 3–15 MB (bare <600 KB) | 50–150 MB+ | Tauri wins decisively |
| Idle RAM | ~30–50 MB (**reference benchmark**, see [L] below) | ~120–400 MB | Tauri |
| Cold start | ~380 ms (**reference benchmark**) | ~1,420 ms | Tauri |
| Rendering | OS WebView (WKWebView on macOS) | Bundled Chromium | Electron identical; Tauri fine for our UI |
| Backend | Rust core | Node.js | **Irrelevant** — HUD backend stays Python |
| Security default | capability allowlist (closed by default) | opt-in hardening | Tauri |
| macOS | production-grade (notarization via notarytool, 4-step sign/package/notarize/staple) | mature | both OK |
| Windows | WebView2 | Chromium | both OK (not this phase) |
| Linux | WebKitGTK (quirks) | Chromium | both "expected" only |
| System tray | tray-icon plugin (v2) | mature | both OK |
| Notifications | notification plugin | mature | both OK |
| Auto-update | Tauri updater (full-binary, younger) | electron-updater/Sparkle (battle-tested) | noted; not built this phase |
| Signing/notarization | `tauri signer` + notarytool | Forge/osx-sign | both require Apple Developer account |

> **Benchmark truth note**: idle-RAM ~42 MB and cold-start ~380 ms above are
> **reference benchmarks** from public Tauri-vs-Electron 2026 comparisons
> (woyable / forasoft / pkgpulse), NOT measured on this machine for Hermes HUD.
> They will be replaced with our own measured numbers in Desktop Foundation
> v0.1 (Actual Desktop Benchmark, section L).

## L. Hermes HUD Prototype Measured Benchmark (2026-08-27, Desktop Foundation v0.1)

Machine: Mac (Apple Silicon) · macOS 26.6.2 (25G83) · arm64 · rustc 1.98.0 ·
cargo 1.98.0 · Tauri 2.11.4 (tauri-cli) · release build (LTO + strip).

| Metric | Hermes HUD prototype (measured) | Tauri reference | Electron reference |
|---|---|---|---|
| .app bundle size | **5.4 MB** | 3–15 MB | 50–150 MB |
| executable size | 5,683,616 bytes (5.4 MB) | — | — |
| idle RSS (main + WebContent) | **97.8 + 23.6 = 121.4 MB** | ~42 MB (bare) | ~168 MB |
| cold launch → HUD connection ×3 | 0.83 / 0.83 / 0.83 s → **median 0.83 s** | ~380 ms (bare) | ~1,420 ms |
| warm launch ×3 | 0.84 / 0.82 / 0.82 s → **median 0.82 s** | — | — |
| first HUD usable render | ~1.5–2 s (est.; connection + WKWebView page load + React first paint) | — | — |

Notes:
- Our app ships an embedded Tauri shell only — no plugin backend (Python
  Dashboard provides it), hence 5.4 MB.
- idle RSS includes the WKWebView WebContent process (23.6 MB) which the bare
  Tauri reference does not count; the main-process figure (97.8 MB) is the
  comparable number.
- cold vs warm are near-identical (0.83 vs 0.82 s): Rust cold start is fast
  and WebKit process reuse dominates.
- Measurements taken with `lsof`-detected first connection to the Dashboard
  at 127.0.0.1:9119 (median of 3 runs, not best run).

**Decision: Tauri 2.** Size/RAM/security defaults win; the Node-vs-Rust concern
is moot because our business logic lives in the existing Python backend and the
Rust shell only needs HTTP + WS + tray.

### B. Process Model

1. **Desktop App connects to the already-running Hermes Dashboard** — app is a
   WebView pointed at `http://127.0.0.1:<port>/hud` plus a thin Rust shell
   (tray, notifications, window). Startup = zero backend work; shutdown =
   nothing to clean; port = Dashboard owns it; crash recovery = Dashboard
   already has launchd/watchdog; upgrades = HUD plugin upgrades are invisible
   to the app.
2. Desktop App starts/manages an independent HUD backend — duplicate process,
   port conflicts, second instance semantics, heavier packaging. Rejected.
3. Desktop App embeds a Python sidecar — Rust+Python dual runtime, packaging
   and upgrade complexity (PyInstaller/uv + Tauri). Only if Dashboard cannot
   be relied on. Rejected for v1.

**Recommended: Option 1** — connect to the running Hermes Dashboard, with an
optional "auto-start dashboard" convenience (spawn `hermes dashboard` if
unreachable), gated behind a user preference. Developer mode keeps manual
port input.

### C. Web UI Reuse

`dist/index.js` is an IIFE that consumes `window.__HERMES_PLUGIN_SDK__`
(React/hooks/auth-fetch injected by the Dashboard) and uses
`localStorage`/`WebSocket`/`fetch` — all available in WKWebView.

Two ways to load it in Tauri:
- **(a) Point the WebView at the live Dashboard URL** (`http://127.0.0.1:<port>/hud`):
  the Dashboard injects the SDK as usual → **100% reuse, zero frontend change**,
  auth handled by the page itself. This is the recommended path.
- (b) Bundle `dist/index.js` locally and inject a SDK shim — requires an SDK
  polyfill + React bundling; unnecessary complexity. Rejected.

**Web UI reusable: YES (via URL loading, reuse-first).**

### D. Local Connection Contract (draft)

- Discovery: probe `127.0.0.1:9119` (default) then well-known ports; `/health`
  reachable = Dashboard up.
- Auth: **the `/hud` page itself handles Dashboard session-token auth (loopback
  page-token injection) — the native Rust shell does NOT parse HTML, does NOT
  scrape session tokens, and does NOT perform authenticated REST** (see
  Security Model Correction below).
- Reconnect: WS exponential backoff inside the page (already the Web client's
  behaviour); REST poll fallback likewise.
- Version negotiation: `api_schema_version` (HUD_API_SCHEMA_VERSION = 1) in
  `/health` + `/settings` (Desktop Foundation v0.1, contract D).

### Security Model Correction — two security planes

1. **Remote HUD WebView** (loads `http://127.0.0.1:<port>/hud`):
   - Tauri IPC capability = **NONE** · shell = NONE · fs = NONE · dialog = NONE
     · updater = NONE · native commands = NONE
   - The `/hud` page talks to the Dashboard the same way a normal browser does:
     `fetch` / `WebSocket` / `localStorage` — plain HTTP to `127.0.0.1:<port>`.
   - **No Tauri HTTP plugin capability is granted to the remote URL.**
2. **Native Rust shell**:
   - Exposes **no command bridge** to the `/hud` page (no `invoke` handlers
     reachable from remote content).
   - Native capabilities (tray, window) are shell-only, driven by native code.

### Auth Boundary (v0.1)

- WebView page itself handles existing Dashboard session-token auth.
- Native Rust does **not** parse HTML / scrape session tokens / hold tokens.
- Page-token scraping is **rejected for the native layer** — brittle HTML
  coupling, unnecessary secret handling. Prototype does not need it.
- Native incident polling / native authenticated REST / app-token / token
  persistence / native notifications: **deferred** until a stable desktop
  handshake exists.

### E. Desktop API Contract (v1.1.0 coverage)

| Desktop surface | Endpoint | Status |
|---|---|---|
| Overview | `/snapshot`, `/health` | Desktop-ready |
| Timeline | `/timeline`, `/timeline/stats` | Desktop-ready |
| Skills | `/skills` | Desktop-ready |
| Skill Analytics | `/skills/analytics`, `/skills/analytics/{skill}` | Desktop-ready |
| Cost Intelligence | `/cost/summary|timeseries|models|sessions|budget` | Desktop-ready (schema_version=1) |
| Sessions | `/sessions`, `/sessions/{id}`, `/sessions/search` | Desktop-ready |
| Incidents | `/incidents` | Desktop-ready |
| Settings/status | `/settings`, `/data-quality` | Needs contract cleanup (no schema_version) |

Gaps (recorded, **not** built this phase):
1. `/health` + `/settings` schema/version fields for app↔backend negotiation.
2. Optional dedicated app-token flow (vs page-token scraping) for a future
   non-loopback scenario — currently loopback-only is sufficient.
3. WS event envelope versioning.

### F. Security Boundary

- 127.0.0.1 only (Dashboard default) — unchanged.
- Tauri capabilities (v2 allowlist): **shell = none** (no shell bridge to
  WebView); fs = none (no file access from renderer); http = only
  `http://127.0.0.1:*` (REST/WS); updater = disabled this phase; notifications
  = system notifications only; tray = tray-icon. Default minimal permissions.
- CSP on the Tauri window: restrict to `http://127.0.0.1:*` + `ws://127.0.0.1:*`.
- No raw secrets passed to JS beyond what the Dashboard already injects
  (loopback session token, page-scoped). No `state.db` writes (read-only
  boundary unchanged).

### G. macOS Product Experience (design target)

Hermes HUD.app: double-click to open → auto-detect Hermes Dashboard →
auto-connect → connection status in window + tray → Menu Bar / System Tray
(Open Dashboard, Quit) → system notifications for incidents. No manual port,
no Terminal, no manual browser. Developer mode (manual port) retained.

### H. Prototype Result

**BLOCKED: prototype toolchain unavailable** — no `cargo`/`rustc` on this
machine and installing a Rust toolchain is out of scope for a research spike
(no system-env modification). Architecture report is complete regardless;
the minimal Tauri prototype (window → load `/hud` → call `/snapshot`,
`/timeline`, `/cost/summary` → WS reconnect) is the first task of the next
implementation phase.

### I. Packaging Architecture (design only)

- HUD plugin stays independently installed/updatable via
  `scripts/enable_dashboard_plugin.py` (unchanged; it is the backend).
- Desktop App **does not bundle the plugin** — it is a shell over the
  Dashboard-served backend.
- Python runtime: provided by the user's Hermes installation (Dashboard
  process); the app never ships Python.
- Hermes ≥ 0.19.0 check: the app verifies via `/health`/version negotiation
  (backend is HUD v1.1.0 which asserts Hermes ≥ 0.19.0 at enable time).
- Compatibility matrix (recommended):

| Desktop version | HUD API schema | HUD plugin |
|---|---|---|
| 0.1.x (alpha) | 1 | v1.1.0+ |

### J. Update Strategy (compare only, not implemented)

- GitHub Release (manual) → Tauri updater (signed, full-binary) for the app;
  plugin updates remain independent (`git pull`/reinstall + enable script).
- Desktop app and HUD plugin update **independently**; version negotiation
  (D) prevents mismatch.

### K. Distribution

- macOS: `.app` + `.dmg`; signing + notarization require an Apple Developer
  account (`xcrun notarytool`, 4-step pipeline) — purchase/account is a
  decision for the implementation phase.
- Windows `.msi`/`.exe` and Linux AppImage/deb: **out of scope**; do not claim
  tested.

## Decision

- **Tauri suitable: YES** (size/RAM/security; Node-vs-Rust moot — backend is Python)
- **Web UI reusable: YES** (load live `/hud` URL; zero frontend change)
- **Existing backend reusable: YES** (21 REST + WS; only gap = version negotiation)
- **Python sidecar required: NO** (connect to running Dashboard)
- **Recommended process model:** Desktop shell → running Hermes Dashboard
  (Option 1), optional auto-start dashboard preference
- **Recommended auth model:** loopback session-token (page-token extraction +
  `X-Hermes-Session-Token`; WS same token); future app-token flow optional
- **macOS alpha feasible: YES** (once Rust toolchain available; signing/
  notarization deferred to account purchase)

## Risks

1. WKWebView quirks vs Chromium (minor for our dependency-light UI).
2. Page-token scraping couples app to Dashboard HTML — acceptable while
   loopback-only; revisit with a real app-token endpoint.
3. Tauri updater younger than Electron's; acceptable for alpha (manual
   GitHub Release install initially).
4. Dashboard not running → app must explain/auto-start; handled by
   discovery + optional spawn.
5. WebView variance across macOS versions — test matrix needed.

## Next Implementation Phase

1. Install Rust toolchain (user decision) → `experiments/desktop-spike/`
   minimal Tauri app: window → load `http://127.0.0.1:9119/hud` → verify
   `/snapshot`, `/timeline`, `/cost/summary` calls → WS reconnect demo.
2. Backend contract cleanup (tiny, non-functional-change): `api_version` in
   `/health` + `/settings`; WS envelope version.
3. macOS alpha: tray + notifications + auto-start preference; .dmg + signing
   (needs Apple Developer account).
