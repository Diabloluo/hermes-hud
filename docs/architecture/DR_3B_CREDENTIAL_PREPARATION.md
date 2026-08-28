# Apple Developer Credential Preparation — DR-3B

Status: **COMPLETE** (2026-08-28 — DR-3B closeout)
Baseline: `eb36985c764353a87f71c984e3e6a600feedeae7`
Date: 2026-08-27

## USER-ONLY SECURITY RULE

Never paste into chat / tickets / logs / screenshots:
Apple Account password, 2FA code, .p12 password, .p12 contents/base64,
.p8 contents, private key, GitHub secret values.

Hermes may only see: certificate common name, Team ID, certificate expiry,
API Key ID, Issuer ID, filenames, success/failure status.

## A. Apple Developer enrollment — USER ONLY

1. Enroll in Apple Developer Program (Individual) at
   https://developer.apple.com/programs/ — login / 2FA / payment by you.
2. Confirm: Apple Account 2FA enabled; legal name correct; phone/address
   current; membership = **Active**; role = **Account Holder**.
3. If enrollment is Pending/Under Review → **STOP** (do not re-submit).

## B. Create local CSR — USER ONLY

1. Keychain Access → Certificate Assistant → Request a Certificate From a
   Certificate Authority.
2. Private key is generated locally, stored in your **login Keychain** —
   never uploaded, never shown. Hermes must never export it into the
   project directory.

## C. Developer ID Application — USER ONLY

1. developer.apple.com → Certificates, Identifiers & Profiles →
   Certificates → + → Developer ID → **Developer ID Application**
   (NOT Developer ID Installer — we ship .app inside .dmg, not a .pkg).
2. Upload the local CSR, download the `.cer`, double-click to install into
   login Keychain.

## D. Local certificate verification — HERMES MAY EXECUTE (after C)

```bash
security find-identity -v -p codesigning
```
Must show `Developer ID Application: ...`. Record identity name, Team
Identifier, expiry date, SHA fingerprint (if useful). Do NOT report the
Apple Account email.

## E. Export CI certificate — USER ONLY

1. Keychain Access → My Certificates → Developer ID Application (expand —
   confirm the **private key** is paired).
2. Export as `DeveloperID-HermesHUD.p12` with a **strong random password**
   (never send the password to Hermes).
3. Store the .p12 outside the project in a private directory,
   `chmod 600`. Never `git add` it; no long-term Downloads storage; no
   cloud/public sharing.

## F. App Store Connect API access — USER ONLY

1. appstoreconnect.apple.com → Users and Access → Integrations.
2. If it shows "Request Access" — request it (initiated by Account Holder,
   case-by-case review).
3. If not yet approved → **STOP**: `PENDING_ASC_API_ACCESS`. Do NOT fall
   back to Apple ID + app-specific password.

## G. Create Team API Key — USER ONLY

1. Users and Access → Integrations → Team Keys → Generate API Key.
2. Name suggestion: `Hermes HUD Notarization`; Role: **Developer**
   (current Tauri macOS signing/notarization guidance). Not Admin unless
   evidence shows Developer cannot notarize.
3. Team Key is account-wide, not app-specific.

## H. Download .p8 exactly once — USER ONLY

1. Download `AuthKey_<KEY_ID>.p8` — Apple does not keep a re-downloadable
   copy. Record **Key ID** and **Issuer ID** (reportable to Hermes).
2. `.p8`: `chmod 600`, private storage. Never report contents.

## I. Local API credential validation

Only authentication validation (e.g. `xcrun notarytool` accepting the
credentials). Do NOT submit a real notarization of the Hermes HUD build in
this phase. If Apple's tooling has no safe pure-auth check, defer to DR-5.

## J. GitHub Environment credential staging — USER ONLY

After all of the above validate: Repository → Settings → Environments →
**desktop-release**:

Sensitive **Environment Secrets**:
- `APPLE_CERTIFICATE` (base64 of the .p12)
- `APPLE_CERTIFICATE_PASSWORD`
- `APPLE_API_PRIVATE_KEY` (.p8 content)

**Environment Variables**:
- `APPLE_SIGNING_IDENTITY`
- `APPLE_API_ISSUER`
- `APPLE_API_KEY`

Only in the desktop-release environment — never repository-wide Apple
secrets. Enter values yourself in the GitHub UI. When base64-ing the .p12,
stdout must not be logged; safest is to generate locally and paste directly
into the GitHub Secret input, then delete the temp base64 file. Keep one
secure offline backup of the original .p12/.p8.

## K. Post-staging truth (HERMES may verify — names only, never values)

- Environment secrets present (names): `APPLE_CERTIFICATE`,
  `APPLE_CERTIFICATE_PASSWORD`, `APPLE_API_PRIVATE_KEY`
- Environment variables present (names): `APPLE_SIGNING_IDENTITY`,
  `APPLE_API_ISSUER`, `APPLE_API_KEY`
- Never read values; never print personal identity info.

## DR-3B Closeout (2026-08-28)

- Status: **COMPLETE**
- Developer ID identity = **ready** (1 valid identity; Team ID R49V6YUC3X; expiry 2031-08-29; private key paired)
- .p12 = **ready** (outside repo, chmod 600)
- ASC Team API Key = **ready** (Role: Developer; name "Hermes HUD Notarization")
- .p8 = **ready** (outside repo, chmod 600)
- desktop-release Environment = **3 secrets + 3 variables staged** (names only; values never stored in this repo)
- signing = **not started**
- notarization = **not started**
- Next: DR-4 (Developer ID signed build); credential auth validated at DR-5 (no fake notarization probe).
