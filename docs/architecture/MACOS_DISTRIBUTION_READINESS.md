# macOS Distribution Readiness — DR-1

Status: **Plan / Inventory / Design** (no credentials, no signing, no release)
Baseline: `391815f469c51ceea4a73ff2f0ae1d89f6aa17c8` (macOS Alpha v0.1, frozen)
Date: 2026-08-27

This document designs the path from **local unsigned Alpha** to a **Developer ID
signed + Apple notarized + stapled + GitHub downloadable** macOS application.
DR-1 does NOT create certificates, submit notarization, or publish anything.

## A. Frozen Alpha invariants (MUST NOT CHANGE)

- remote /hud WebView capability = ZERO (capabilities/local-bundled.json `local: true`)
- page-context compatibility handshake, semver gate, fail closed
- fixed Dashboard argv (`<hermes> dashboard --host 127.0.0.1 --port <p> --no-open`), probe-before-spawn
- single instance, Observer Core brand, state machine
- Distribution work must not weaken any of these.

## B. Distribution Target

- **macOS direct distribution via GitHub Release** (Developer ID Application).
- NOT Mac App Store → no Apple Distribution profile, no sandbox/provisioning
  architecture, no App Store entitlements.

## C. Apple Requirements Truth Table

| Item | Verdict | Official doc |
|---|---|---|
| Paid Apple Developer Program membership | **REQUIRED** (Developer ID certs + notarization require membership) | https://developer.apple.com/programs/ |
| Developer ID Application certificate | **REQUIRED** (Gatekeeper trusts Developer ID identity) | https://developer.apple.com/developer-id/ |
| Hardened Runtime | **REQUIRED** for Developer ID distribution | https://developer.apple.com/documentation/security/hardened-runtime |
| Notarization | **REQUIRED** for Developer ID apps distributed outside MAS (Gatekeeper blocks unnotarized by default on modern macOS) | https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution |
| Stapling | **RECOMMENDED** (offline Gatekeeper validation; unstabled still passes online) | https://developer.apple.com/documentation/security/customizing-the-notarization-workflow |
| notarytool | **REQUIRED** (current tool) | https://developer.apple.com/documentation/technotes/tn3147-migrating-to-the-latest-notarization-tool |
| altool | **DEPRECATED** — notary service no longer accepts altool uploads | TN3147 (above) |

No credentials / account IDs / secrets are recorded here.

## D. Current Bundle Audit (baseline Alpha)

```
Hermes HUD.app
└─ Contents
   ├─ MacOS/hermes-hud-desktop   (single arm64 binary, 5.7 MB, adhoc-signed)
   ├─ Resources/icon.icns        (Observer Core, 108 KB)
   └─ Info.plist                 (CFBundleIdentifier=com.diabloluo.hermes-hud-desktop,
                                  CFBundleShortVersionString=0.1.0,
                                  CFBundleVersion=0.1.0)
```

- **No Frameworks directory, no dylibs, no nested binaries** — Tauri statically
  links; the signable object set is exactly `Contents/MacOS/hermes-hud-desktop`
  (plus Resources for completeness). Developer ID signing must cover the binary
  and the bundle as a whole.
- Architecture: **arm64 only** (Apple Silicon). Not universal — see P.
- Entitlements today: none (adhoc).

## E. Bundle Identifier Freeze

`com.diabloluo.hermes-hud-desktop` — **KEEP**. It is unique, stable, and has no
Apple technical blocker. No cosmetic changes.

## F. Version Contract

| Surface | Current | Role |
|---|---|---|
| HUD plugin (backend) | 1.1.0 | semver-gated by Desktop handshake (≥ 1.1.0) |
| Desktop app | 0.1.0-alpha | user-facing desktop release |
| API schema | 1 | wire contract, `api_schema_version` |

- macOS `CFBundleShortVersionString` (user-facing marketing version) currently
  renders `0.1.0` — the `-alpha` marker is lost. Design decision:
  - user-facing label: **Desktop Alpha 0.1.0** (marketing "Alpha 0.1.0")
  - `CFBundleShortVersionString` = `0.1.0` (pure numeric — safest for macOS/
    Tauri tooling and Gatekeeper display)
  - prerelease clarity carried by release name/tag (`desktop-v0.1.0-alpha`) and
    About text, not by the bundle version string.
- This is a design recommendation; DR-3 may apply it. No change now.

## G. Hardened Runtime / Minimal Entitlements

The native layer is intentionally narrow: local process spawn, local network
(127.0.0.1), tray, window. Least-privilege analysis:

| Proposed entitlement | Purpose | Required? | Security impact |
|---|---|---|---|
| (none — Hardened Runtime defaults) | — | — | Default HR blocks JIT, unsigned dylibs, etc. |
| `com.apple.security.cs.disable-library-validation` | load unsigned dylibs | **NO** — no dylibs in bundle | Would weaken HR — avoid |
| `com.apple.security.cs.allow-unsigned-executable-memory` | JIT/exec memory | **NO** — no JIT | Would weaken HR — avoid |
| `com.apple.security.get-task-allow` | debugger attach | **NO** — release | Debug-only, must be absent |
| `com.apple.security.network.client` | outbound net | **NO** — app only talks to 127.0.0.1 | Not needed; loopback is not gated by this |
| `com.apple.security.app-sandbox` | sandbox | **NO** — Developer ID direct distribution does not require sandbox (MAS only) | Not applicable |

**Conclusion: the signed app ships with zero custom entitlements** (Hardened
Runtime on, no exceptions). Process spawn and loopback network are ordinary
POSIX operations not gated by App Sandbox-style entitlements. If a build-time
empirical failure appears in DR-3, revisit with evidence — not preemptively.

## H. Signing Architecture (design only)

- **Local developer signing**: macOS login Keychain, Developer ID Application
  certificate. `APPLE_SIGNING_IDENTITY` env names the identity.
- **GitHub Actions signing**: `APPLE_CERTIFICATE` (base64 .p12) +
  `APPLE_CERTIFICATE_PASSWORD` imported into an ephemeral temp keychain during
  the job; `APPLE_SIGNING_IDENTITY` selects it. .p12 lives only in repo secrets —
  never committed, never an artifact, never printed.
- Tauri officially supports this CI signing variable set.

## I. Notarization Authentication Architecture

| Angle | Option A: App Store Connect API Key | Option B: Apple ID + app-specific password + Team ID |
|---|---|---|
| Security | scoped key, no 2FA dependency | app-specific password is long-lived; tied to Apple ID |
| CI suitability | **excellent** (no interactive 2FA) | poor (2FA/timing issues in headless CI) |
| Revocation | revoke key in ASC, instant | revoke app-specific password |
| Rotation | regenerate key, re-upload secret | regenerate password |
| Least privilege | scope key to notarization only | Apple ID password can access account surface |
| Owner dependency | key owner must be ASC user | account owner for app-specific passwords |
| Secret exposure | .p8 short-lived in runner | password similar exposure |

**Recommended: Option A (App Store Connect API Key)** — Tauri envs
`APPLE_API_ISSUER`, `APPLE_API_KEY` (key ID), `APPLE_API_KEY_PATH` (file).
Backup: `APPLE_ID` + `APPLE_PASSWORD` + `APPLE_TEAM_ID`. DR-1 creates no real key.

## J. Secret Inventory (proposed GitHub Actions secrets)

| Logical name | Content | Used by |
|---|---|---|
| `APPLE_CERTIFICATE` | base64 Developer ID .p12 | import → temp keychain |
| `APPLE_CERTIFICATE_PASSWORD` | .p12 password | import |
| `APPLE_SIGNING_IDENTITY` | e.g. "Developer ID Application: …" | codesign -s |
| `APPLE_API_ISSUER` | ASC API issuer UUID | notarytool |
| `APPLE_API_KEY` | ASC API key ID | notarytool |
| `APPLE_API_PRIVATE_KEY` | .p8 content | write to ephemeral file |

.p8 lifecycle in CI: secret → ephemeral file → `APPLE_API_KEY_PATH` → build →
secure delete (job ends; runner disposed). Never commit/artifact/log/cache.

## K. CI Architecture (design only — `desktop-release.yml`, future)

```
checkout exact tag/SHA
→ Rust/Tauri toolchain setup
→ cargo test
→ backend pytest
→ security tests (cargo test env-gated)
→ import temporary signing cert (secrets → temp keychain)
→ build release app (tauri build)
→ Developer ID sign (+ Hardened Runtime)
→ codesign verify
→ notarize (notarytool submit)
→ wait for Accepted
→ staple
→ stapler validate
→ spctl Gatekeeper assessment
→ build/verify DMG
→ SHA256
→ artifact staging
```
Any failure → NO RELEASE. **Workflow MUST NOT run on pull_request from forks**
and MUST NOT expose secrets there; release only from tag push or manual
dispatch on main with tag input.

## L. Notarytool only

Notarization is built on `xcrun notarytool`. `altool` is deprecated and the
Apple notary service no longer accepts it (TN3147).

## M. Verification Contract (future, DR-3)

```bash
codesign --verify --deep --strict --verbose=2 Hermes\ HUD.app
codesign -dv --verbose=4 Hermes\ HUD.app        # TeamIdentifier, Authority chain, Runtime Version
xcrun stapler validate Hermes\ HUD.app
spctl --assess --type execute --verbose Hermes\ HUD.app
```
Report: TeamIdentifier, Authority, Runtime Version (Hardened Runtime),
notarization result (Accepted). No unnecessary account data in reports.

## N. Download Truth Test (release-gate design)

Local build success is NOT Gatekeeper evidence. Pre-release truth test:
GitHub Release asset → HTTPS download → quarantine attribute present → mount
DMG → drag to Applications → first launch → Gatekeeper passes **without bypass**.
Forbidden in tests: `xattr -d com.apple.quarantine`, `spctl --master-disable`,
right-click workaround, "Open Anyway". Public Alpha gate = real user path only.

## O. Public vs Internal Build Boundary (inventory for DR-2)

| Item | Classification | DR-2 action |
|---|---|---|
| `HUD_DESKTOP_TEST_MODE` gate | TEST ONLY | keep gated (already release-ignored) |
| `HUD_HERMES_BIN` / `HUD_DESKTOP_TEST_HOME` / `HUD_DESKTOP_AUTOSTART` | TEST ONLY | ignored without TEST_MODE (done) |
| `/tmp/hud-state.log`, `/tmp/hud-handshake.log`, `/tmp/hud-detect.log` | TEST ONLY | no-op or removed in public build |
| `HUD_DESKTOP_SMOKE` instrumentation | TEST ONLY | not present in current build; ensure absent |
| autostart fixture path | TEST ONLY | TEST_MODE-gated (done) |
| state machine / handshake / probe logic | SAFE IN PUBLIC | keep |
| Observer Core brand, About identity | SAFE IN PUBLIC | keep |
| release/nav/security code | SAFE IN PUBLIC | keep |

DR-2 checklist: strip test-only logging, confirm zero test-mode escape hatches
in the public binary, rerun full regression.

## P. Release Asset Contract (future Public Alpha)

- `Hermes-HUD-Desktop-0.1.0-macOS-arm64.dmg`
- `SHA256SUMS.txt`
- **Apple Silicon only** (build is arm64) — explicitly stated; no fake universal.

## Q. GitHub Release Architecture

Desktop releases live under a distinct tag namespace to avoid confusion with
the HUD plugin (v1.1.0): **`desktop-v0.1.0-alpha`** (prerelease). Recommendation:
`desktop-v<semver>` with `-alpha` prerelease suffix until GA. No tag created now.

## R. README Architecture (design only, not modified this phase)

Sections for public docs: Desktop Alpha · System Requirements · Install ·
First Launch · Start Dashboard · Security model · Uninstall · Known
limitations · Web UI remains supported.

## S. Apple Developer Account Decision

**Yes — paid Apple Developer membership ($99/yr) is required** for Developer
ID signing + notarization of an app distributed outside the Mac App Store.
User manual steps (DR-3, after Second Auditor approves DR-1):
1. Enroll in Apple Developer Program (https://developer.apple.com/programs/).
2. Create a Developer ID Application certificate (Certificates → Developer ID
   Application) and export the .p12 + record signing identity.
3. Create an App Store Connect API key (Users and Access → Keys) scoped to
   notarization; record issuer + key ID + .p8.
4. Add the six secrets to the repo settings (J).
DR-1 does not induce creating certificates/keys early.

## T. Threat Model (signing/distribution added risks)

| Attack | Mitigation | CI control |
|---|---|---|
| Certificate theft (.p12 leak) | .p12 only in secrets; temp keychain per job; never artifact/log | secrets scoping, no artifacts |
| API key leakage (.p8) | ephemeral file + secure delete + runner disposal | APPLE_API_KEY_PATH only during job |
| Malicious release workflow change | review gate on workflow file; release only from tag/main | branch protection on .github |
| Unsigned replacement asset | SHA256SUMS + checksum verify in pipeline | artifact staging + hash compare |
| Tag/commit mismatch | pipeline checks out exact tag; verifies SHA | `git checkout $GITHUB_SHA` + assert |
| Secret exfiltration via PR | **release workflow never runs on fork PRs**; secrets unavailable to PR | `pull_request` paths excluded; `permissions: contents: read` |
| Fork-triggered workflow | no `pull_request_target` for release; no secrets on PR | trigger = tag push / manual dispatch |
| Artifact substitution | signed+notarized app verified by spctl before staging | verification steps gate release |

## U. Freeze Rule (DR-1 scope)

Allowed: this architecture document, distribution checklist, optional workflow
skeleton with NO secrets / NO active release.
Forbidden: certificate creation, Apple account login, ASC API key creation,
real signing, real notarization, tag, GitHub Release, changing Alpha product
behavior, updater, Windows/Linux.

## DR-2 / DR-3 Entry Criteria

- **DR-2**: user provides Apple Developer membership + manual cert/key steps
  (S); public/internal boundary cleanup (O) executed; workflow skeleton
  validated (cannot publish / cannot access secrets / cannot run on PR).
- **DR-3**: real Developer ID signing + notarization on CI, Gatekeeper truth
  test (N) passed on a real download, first public Desktop Alpha release.
