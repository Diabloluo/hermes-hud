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
| 15 | Release notes draft final (DESKTOP_ALPHA_0.1.0.md) | ☐ |
| 16 | SHA256SUMS.txt correct | ☐ |
| 17 | No secrets in artifact / logs / release assets | ☐ |

Any **No** → No-Go until fixed. This checklist lives here so DR-4/DR-5
have a single, explicit gate.
