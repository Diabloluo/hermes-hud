# Desktop RelayGlance source checks — 2026-11-09

Base: `3a786193751ec7d5aa297da9924eec4cf4b200de`.
Scope: Desktop 0.1.1 source candidate, not a signed/released binary.

## Passed in the isolated cloud checkout

- Full repository pytest with isolated `HERMES_HOME`, no real telemetry
  scan and no performance long run: **450 passed, 32 skipped, 1 deselected**.
  The skipped checks are environment-dependent; they are not passes.
- Desktop/Web branding subset: **16 passed**.
- Bundle-verifier shell fixtures: **16 passed**, including new filename,
  version/architecture rejects, exact checksum entry and duplicate rejection.
- Python compile checks, JavaScript syntax, shell syntax and diff whitespace.
- Icon regeneration into a separate output directory produces the same
  manifest hashes. The approved source PNG remains unchanged.
- ICNS structure and all 11 PNG-backed representations match their expected
  sizes/bytes; the 10-file iconset includes Retina sizes. Tray images contain
  only black/alpha pixels with transparent backgrounds and antialiasing.
- The setup page's JavaScript changes only two user-visible HUD labels to
  RelayGlance; its logic and `__hud_*` hooks are unchanged. Native runtime
  changes are limited to display strings and removing the default app icon
  override that replaced the tray template. Technical identities and local
  security capability files are unchanged.

## Not yet verified by these checks

No Rust toolchain is installed in this cloud executor. Native compile/tests,
macOS icon rendering, Finder/Dock/menu/setup visual QA, bundle packaging,
Developer ID signing, Hardened Runtime, notarization, stapling, downloaded-file
Gatekeeper, clean install, upgrade and rollback require a coordinated macOS
run. The [release gate](../release/DESKTOP_ALPHA_GO_NO_GO.md) remains No-Go
until those checks pass. Prior Dashboard/blank-window reports are not resolved
or certified by a display-only rebrand.

## Subsequent macOS source validation

The Desktop changes were transplanted onto the merged Web 1.2.4 commit
`69886dc08eee748c10f1ed92d0e090221e950d99`, preserving all Web files and
version 1.2.4. The new fixture helpers are confined to `#[cfg(test)]` and
use per-test unique directories under `TMPDIR`; the bundle-verifier fixture
also honors `TMPDIR` and fails immediately if that directory cannot be used.

On macOS arm64 with Rust 1.98.0, both `cargo test --offline --locked` and
`cargo test --offline --locked --features desktop-test-hooks` passed all
12 tests. `iconutil` successfully decoded the new ICNS into an iconset.
These checks used isolated source/build/cache/temp/log directories on an
external work disk, two low-priority build jobs and no live app/service
changes. They do not constitute GUI, upgrade, notarization or distribution
approval; final artifact receipts must identify their exact source commit.

The bundle verifier now uses macOS's system-managed read-only, non-browsing
mount point and parses its device/path receipt. An external custom mount
point was rejected by macOS despite a valid DMG; the normal system mount
succeeded without changing disk ownership or security settings. The expanded
verifier fixtures pass 22 cases, including Unicode paths, ambiguous mounts,
malformed receipts, empty paths and absent parent devices. Only the recorded
task-owned device is detached.

Mount ownership is verified against before/after image snapshots. An already
attached target is refused without attachment or detachment. Nine mocked
end-to-end cases cover new/reused devices, bad snapshots and receipts,
partial failures and failed cleanup. Uncertain outcomes preserve receipts
without guessing a device or forcing unmounts. The owned-device flow also
passed against the task's actual signed candidate DMG.
