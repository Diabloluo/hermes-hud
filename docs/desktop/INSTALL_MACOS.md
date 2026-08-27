# Install — Hermes HUD Desktop (macOS, Apple Silicon)

> Public distribution is pending signing + notarization. Until then this
> document describes the intended user path; local/internal installs use the
> unsigned build from the release kit rehearsal.

## Normal user path (no Terminal required)

1. **Download** `Hermes-HUD-Desktop-0.1.0-macOS-arm64.dmg` from the GitHub
   Release (once published).
2. **Open the DMG** (double-click).
3. **Drag `Hermes HUD` into Applications**.
4. **Launch** Hermes HUD (Finder → Applications → double-click).
5. On first launch the app:
   - detects Hermes on your machine,
   - connects to an already-running Dashboard, **or**
   - offers **Start Hermes Dashboard** (safely starts the local Dashboard),
   - shows **Connected** and the HUD window.

## Prerequisites

- **Hermes Agent** already installed (≥ 0.19.0) with the **HUD plugin**
  (≥ 1.1.0). Hermes HUD Desktop is a window into your existing Hermes
  setup — it does not install Hermes Agent.
- macOS on **Apple Silicon** (arm64).

## System requirements

- macOS current release (see release notes for minimum)
- Apple Silicon (M1 or newer)

## Terminal?

Normal users never need Terminal for install or first launch. Terminal is
only mentioned in [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for advanced
diagnostics.
