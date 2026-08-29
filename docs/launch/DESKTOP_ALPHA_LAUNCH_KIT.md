# Desktop Alpha Launch Kit — DR-3D

Status: **PUBLISHED (2026-08-29)** — Desktop Alpha 0.1.0 released (`desktop-v0.1.0-alpha`). Day-0/2/7 posts per section 3 tracking.
Baseline: `0e0c8e0d9d9e4922dafff2cd0977f0a29d416dd2`
Apple path: COMPLETE (signing + notarization + stapling done)

Everything below is launch-day copy. No public post, tag, or release has
been made. GitHub URL placeholders (`<RELEASE_URL>`) are filled at publish.

---

## 1. GitHub Release — final-copy draft

**Title:**
Hermes HUD Desktop Alpha 0.1.0 — Your local window into Hermes

**Body:**
A native macOS window into your Hermes Agent — your agent's timeline,
skill health, and honest cost picture, all on your desktop.

- **Native macOS app** (Apple Silicon)
- **Local-first, read-only** — Desktop observability data stays local; the
  Desktop app sends no outbound telemetry
- **Zero outbound telemetry** — HUD never phones home
- **📍 Agent Timeline** — what your agent did, in order
- **📊 Skill Analytics** — which skills actually ran, and how they fared
- **💰 Cost Intelligence** — estimated cost with honest pricing coverage
- **Automatic Hermes discovery** — connects to your running Dashboard
- **Safe Dashboard startup** — can start the local Dashboard for you
  (never a second instance, fixed safe command)
- **Menu-bar tray** — Open / Retry / Quit
- **Observer Core** — the observability mark for a multi-agent future

**This is an Alpha:**
- requires **Hermes Agent** (HUD plugin ≥ 1.1.1) — the app is a window
  into your existing Hermes setup, not an installer for it
- **Apple Silicon (arm64) only**
- **no auto-updater** yet
- Web HUD remains fully supported — this is an additional surface, not a
  replacement

Install: [docs/desktop/INSTALL_MACOS.md](../desktop/INSTALL_MACOS.md)

Assets: `Hermes-HUD-Desktop-0.1.0-macOS-arm64.dmg` + `SHA256SUMS.txt`

---

## 2. README Desktop section — draft patch (NOT applied)

Insert after the Web Quick Start block, at a high position on the front
page. The two surfaces are presented side by side; Desktop does not
replace Web.

```markdown
## Desktop Alpha for macOS

A native macOS app (Apple Silicon) — your local window into Hermes:
Agent Timeline, Skill Analytics, Cost Intelligence, health, sessions, cron.

- **Local-first · read-only · zero outbound telemetry**
- Automatically discovers Hermes; connects to a running Dashboard or can
  safely start it for you
- Alpha: requires Hermes Agent (HUD plugin ≥ 1.1.1), arm64 only, no
  auto-updater; Web HUD remains fully supported

[Install](docs/desktop/INSTALL_MACOS.md) · [Security](docs/desktop/SECURITY.md)
```

Do NOT apply until the Public Release Gate passes (Go/No-Go all PASS).

---

## 3. X (Twitter) launch copy

### Launch post (Day 0)

```
Hermes HUD now has a native macOS app.

📍 Agent Timeline
📊 Skill Analytics
💰 Cost Intelligence
🔒 Local-first · read-only · zero outbound telemetry

Apple Silicon Desktop Alpha.
<RELEASE_URL>
```

### Day-2 technical post

```
How Hermes HUD Desktop stays honest:

• HUD page gets zero native capability (no shell, no fs)
• Dashboard started with one fixed, safe command — never a second instance
• Compatibility checked before connect; fails closed
• No outbound telemetry — usage signals come only from GitHub

Alpha for Apple Silicon. <RELEASE_URL>
```

### Day-7 feedback post

```
A week of Desktop Alpha — what we want to know:

Did installation work? Did Hermes discovery work?
Which HUD view is most useful?
What failed?

And: which agent should Observer Core support next?
<RELEASE_URL>
```

No superlatives ("first/only/best"); technical, understated, credible.

---

## 4. GitHub Discussion announcement — draft

**Title:** Desktop Alpha is here — feedback wanted

**Body:**
Hermes HUD now has a native macOS Desktop app (Alpha, Apple Silicon) —
a local window into Hermes with Agent Timeline, Skill Analytics and Cost
Intelligence.

Questions we'd love your answers to:

- Did installation work?
- Did Hermes discovery work?
- Which HUD view is most useful to you?
- What failed?
- Which agent should Observer Core support next?

Local-first, read-only, zero outbound telemetry. Web HUD remains fully
supported.

---

## 5. Visual asset plan

No Observer Core redesign. Screenshots to be captured from the **final
signed/notarized RC** (re-shoot or confirm then):

1. Desktop HUD main window
2. Agent Timeline
3. Skill Analytics
4. Cost Intelligence
5. Observer Core in Dock / menu bar
6. DMG install screen

**Privacy/redaction gate (mandatory for every screenshot):**
- no secrets · no personal paths · no email · no tokens
- no real private conversations · no fake Apple signing screenshots
- demo/sanitized data only, labeled as such if needed

---

## 6. 90-day launch tracking sheet — definition

No in-app telemetry. Track only (platform-side / public):

| Day | DMG downloads | stars | external Issues | Discussions | external PRs | meaningful users | non-Hermes collector requests |
|---|---|---|---|---|---|---|---|
| 0 | | | | | | | |
| 7 | | | | | | | |
| 30 | | | | | | | |
| 60 | | | | | | | |
| 90 | | | | | | | |

Thresholds reference: docs/product/DESKTOP_ALPHA_90_DAY_VALIDATION.md
(min ≥25/5/3 · strong ≥100/15/5 · platform = repeated non-Hermes
collector requests).

---

## 7. Public support boundary — draft

- **Tested:** macOS Apple Silicon
- **Alpha software** — expect rough edges; versions may change
- **Best-effort community support** (Issues / Discussions; no SLA)
- **Web HUD remains available** — Desktop is additive, not a replacement

No SLA commitments of any kind.
