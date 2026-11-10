# Desktop Alpha — Go / No-Go Checklist

Every item must be **PASS** before a public Desktop Alpha release. This
checklist is the release gate; nothing below is optional for distribution.

| # | Item | Status |
|---|---|---|
| 1 | Exact release SHA pinned | ☐ |
| 2 | Main CI green on release SHA | ☐ |
| 3 | Fresh Install CI green on release SHA | ☐ |
| 4 | Desktop release CI green (public build + tests + negative-string proof) | ☐ |
| 5 | Developer ID signature valid (`codesign --verify --deep --strict`) | ☐ |
| 6 | Hardened Runtime enabled | ☐ |
| 7 | Notarization result = Accepted (`notarytool`) | ☐ |
| 8 | Staple validates (`xcrun stapler validate`) | ☐ |
| 9 | Gatekeeper downloaded-file test passes (real download path, no bypass) | ☐ |
| 10 | Clean-machine install works (no Terminal, no hidden state) | ☐ |
| 11 | Hermes-running path → Connected | ☐ |
| 12 | Hermes-stopped recovery → Start Dashboard → Connected | ☐ |
| 13 | Incompatible plugin → clear message, fail closed | ☐ |
| 14 | Uninstall verified (app removed; Hermes/plugin/data untouched) | ☐ |
| 15 | Release notes final for the exact version (0.1.1 candidate: DESKTOP_ALPHA_0.1.1.md) | ☐ |
| 16 | SHA256SUMS.txt correct | ☐ |
| 17 | No secrets in artifact / logs / release assets | ☐ |
| 18 | Full-name/radar Finder, Dock, app menu, setup and light/dark tray visual QA | ☐ |
| 19 | Rename upgrade from 0.1.0, same-ID single-instance and rollback verified | ☐ |

Any **No** → No-Go until fixed. This checklist lives here so DR-4/DR-5
have a single, explicit gate.

The 0.1.1 source candidate is **No-Go until native verification is complete**.
Its lightweight branding tests and unsigned bundle verifier do not satisfy
signing, notarization, Gatekeeper, clean-install or upgrade gates.
