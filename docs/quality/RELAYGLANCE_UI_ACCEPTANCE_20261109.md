# RelayGlance Web branding: bounded acceptance

Date: 2026-11-09. Scope: the display-only Web rebrand, not a new native
Desktop application or general certification of every Hermes feature.

## Source and identity

- Functional/visual candidate: `3a786193751ec7d5aa297da9924eec4cf4b200de`.
- Release-version preparation: `55dfe90ea66574092ac932febd50190238ca95a9`.
  The latter changes only the manifest version to 1.2.4, its version test,
  changelog and branding documentation. JavaScript, CSS and radar PNG bytes
  are identical to the UI-tested candidate.
- Repository, plugin ID, API prefix, `/hud`, configuration/history paths,
  language-storage key and API schema remain unchanged.

## Executed

A separate Mac host instance used synthetic data and a unique loopback port,
with temporary files and evidence on external storage. The live Dashboard
and Gateway were not restarted or changed by this acceptance run.

- The real host displayed the RelayGlance sidebar label, localized page
  name and selected radar image. WebSocket live mode was observed.
- Chinese, English, French and Arabic displayed; Arabic used RTL layout.
- Dark and light themes were exercised. A 390×844 viewport was checked in
  English, Chinese and Arabic.
- All 13 panels were visited twice. Locale selection was cycled twice.
  Route unmount/remount, Back/Forward, reload and persistence in a newly
  opened test tab were exercised. One brand header remained throughout.
- No JavaScript runtime console errors were observed. The synthetic host's
  uninitialized Sessions database produced its expected 503 warning; this
  was not presented as a healthy production database or a branding defect.
- Actual profile-scoped JS, CSS and PNG responses matched the candidate
  file hashes. Prefix HTML injection was checked separately.
- Test tabs were closed, viewport overrides reset and the owned isolated
  server stopped. Its port was released; existing live processes remained.

The final version-preparation candidate's isolated Python suite had **443
passed, 32 skipped and 1 deselected**. The deselected case reads real user
telemetry. The manual 10-minute benchmark was not run. Python compile,
JavaScript syntax and whitespace checks passed. Independent source review
found no blocking issue; its two documentation comments were addressed.

## Not established by this run

- Full reverse-proxy browser acceptance. Profile asset bytes and prefix
  injection are narrower evidence and do not replace that end-to-end run.
- Full fresh-install or uninstall acceptance across all supported hosts.
- Desktop Alpha installation, new Dock/tray artwork, signing,
  notarization, Gatekeeper or native upgrade behavior.
- Production data correctness beyond the separate v1.2.3 compatibility
  work. Synthetic missing-gateway/database warnings are not live faults.

The first cloud Chromium attempt and an approved isolated retry could not
start because `process_singleton socket()` was denied. That environment
failure is not counted as a successful browser test. The later Mac test
above is the actual UI evidence. A passing candidate does not by itself
mean it has been merged, published or deployed.
