# 驿览 · RelayGlance Desktop (Tauri 2)

The **0.1.1 source candidate** applies the approved RelayGlance radar brand.
It is not a built, signed, notarized or released binary. The published Hermes
HUD Desktop 0.1.0 tag and assets are historical and must not be overwritten.

## Security invariant (must not regress)

- Remote HUD WebView (`http://127.0.0.1:<port>/hud`) has **zero Tauri
  capabilities**. It uses ordinary fetch/WebSocket/localStorage only.
- `capabilities/local-bundled.json` is local-only. The bundled setup page has
  one narrow `start_dashboard` command; Rust checks the page origin and runs
  only the fixed Dashboard argv. The remote HUD cannot invoke it.
- Navigation stays restricted to the existing allowed local origins.
- Plugin identity `hermes-hud`, `/hud`, `/api/plugins/hermes-hud`, schema 1,
  bundle ID `com.diabloluo.hermes-hud-desktop`, Cargo package and executable
  `hermes-hud-desktop` remain unchanged. No data migration is introduced.

## Branding

- Bundle, window, setup title and tray tooltip: **驿览 · RelayGlance**.
- App filename: `驿览 · RelayGlance.app`.
- Candidate DMG: `RelayGlance-Desktop-0.1.1-macOS-arm64.dmg`.
- The full-color icon is resampled directly from the approved, hash-pinned
  `dashboard/dist/relayglance-radar.png`; the source artwork is unchanged.
- The black/alpha radar tray glyph follows the same rings, sweep and return
  motif. It remains a macOS template image and is no longer overwritten by
  the default color app icon.

To regenerate icon sizes, iconset, ICNS and the bundled setup image:

```bash
python3 -m venv /path/to/isolated-icons-venv
/path/to/isolated-icons-venv/bin/pip install -r tools/requirements-icons.txt
/path/to/isolated-icons-venv/bin/python tools/make_relayglance_icons.py
```

`icons/brand-assets.json` records the source and output hashes. The builder
also accepts `--output-dir` for reproducibility checks outside the checkout.

## Build and verification

Requires Rust stable, Xcode Command Line Tools and macOS WKWebView. Build
only after coordinating with other work on the selected Mac. Keep target,
logs and temporary packaging data on a verified external work disk when
internal space is constrained. Do not stop a running Dashboard to build.

```bash
# Inside experiments/desktop-alpha, with external paths already verified:
export CARGO_TARGET_DIR="$EXTERNAL_BUILD_ROOT/target"
export TMPDIR="$EXTERNAL_BUILD_ROOT/tmp"
mkdir -p "$CARGO_TARGET_DIR" "$TMPDIR"
cargo test --locked
cargo test --locked --features desktop-test-hooks
cargo build --locked --release
# Use the existing Tauri packaging/signing workflow for app/dmg artifacts.
```

The repository's `desktop-release.yml` is a **non-publishing validation
skeleton**, not a signing or notarization pipeline. Lightweight cloud
checks are not evidence of a successful native build or installed upgrade.

Release gates and the rename/rollback plan:
[0.1.1 candidate](../../docs/release/DESKTOP_ALPHA_0.1.1.md) ·
[Go/No-Go](../../docs/release/DESKTOP_ALPHA_GO_NO_GO.md) ·
[Upgrade guide](../../docs/desktop/UPGRADE_RELAYGLANCE.md).
