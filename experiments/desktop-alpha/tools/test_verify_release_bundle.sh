#!/bin/bash
# test_verify_release_bundle.sh — DR-3C verifier regression fixtures.
# Loads check functions via source mode; no DMG mounting needed.
set -u

SRC="$(dirname "$0")/verify_release_bundle.sh"
VERIFY_SOURCE=1
# shellcheck disable=SC1090
. "$SRC"

TMP=$(mktemp -d "${TMPDIR:-/tmp}/relayglance-bundle-test.XXXXXX") || exit 1
trap 'rm -rf "$TMP"' EXIT

PASSED=0; FAILED=0
t() { # name expected actual
  if [ "$2" = "$3" ]; then PASSED=$((PASSED+1)); echo "PASS  $1";
  else FAILED=$((FAILED+1)); echo "FAIL  $1 (expected=$2 got=$3)"; fi
}

DMG="$TMP/fake.dmg"
printf 'fake-content' > "$DMG"
GOOD=$(shasum -a 256 "$DMG" | awk '{print $1}')

# fixture 1: correct SHA256SUMS + arm64 → PASS (sha256 rc=0, arch rc=0)
printf '%s  fake.dmg\n' "$GOOD" > "$TMP/SHA256SUMS.txt"
sha256_ok "$DMG" "$TMP/SHA256SUMS.txt" "fake.dmg"; t "correct checksum" 0 $?
arch_ok "arm64"; t "arch arm64" 0 $?

# fixture 2: missing SHA256SUMS → FAIL (rc=1)
rm -f "$TMP/SHA256SUMS.txt"
sha256_ok "$DMG" "$TMP/SHA256SUMS.txt" "fake.dmg"; t "missing SHA256SUMS" 1 $?

# fixture 3: wrong hash → FAIL (rc=3)
printf '%s  fake.dmg\n' "$(printf 'other' | shasum -a 256 | awk '{print $1}')" > "$TMP/SHA256SUMS.txt"
sha256_ok "$DMG" "$TMP/SHA256SUMS.txt" "fake.dmg"; t "wrong checksum" 3 $?

# fixture 4: no DMG entry → FAIL (rc=2)
printf '%s  other.dmg\n' "$GOOD" > "$TMP/SHA256SUMS.txt"
sha256_ok "$DMG" "$TMP/SHA256SUMS.txt" "fake.dmg"; t "no DMG entry" 2 $?

# fixture 5: architecture matrix
arch_ok "arm64";        t "arch arm64 exact" 0 $?
arch_ok "arm64 x86_64"; t "arch universal" 1 $?
arch_ok "x86_64";       t "arch x86_64" 1 $?
arch_ok "";             t "arch unreadable" 1 $?
arch_ok "arm64e";       t "arch arm64e" 1 $?

# Brand migration contract: legacy assets are historical, never silently
# relabeled as the new release. Check them from the old release tag instead.
canonical_name_ok "RelayGlance-Desktop-0.1.1-macOS-arm64.dmg"; t "new canonical filename" 0 $?
canonical_name_ok "Hermes-HUD-Desktop-0.1.0-macOS-arm64.dmg"; t "legacy filename rejected" 1 $?
canonical_name_ok "RelayGlance-Desktop-0.1.0-macOS-arm64.dmg"; t "wrong desktop version rejected" 1 $?
canonical_name_ok "RelayGlance-Desktop-0.1.1-macOS-x86_64.dmg"; t "wrong architecture name rejected" 1 $?

# A similarly named asset and duplicate entries must not satisfy checksum
# verification. No mount, system settings, or installed apps are touched.
printf '%s  fake.dmg.bak\n' "$GOOD" > "$TMP/SHA256SUMS.txt"
sha256_ok "$DMG" "$TMP/SHA256SUMS.txt" "fake.dmg"; t "filename suffix rejected" 2 $?
printf '%s  fake.dmg\n%s  fake.dmg\n' "$GOOD" "$GOOD" > "$TMP/SHA256SUMS.txt"
sha256_ok "$DMG" "$TMP/SHA256SUMS.txt" "fake.dmg"; t "duplicate checksum rejected" 4 $?

# Structured mount receipts support spaces/non-ASCII names, reject ambiguity,
# and never invent a device for cleanup.
python3 - "$TMP" <<'MOUNT_FIXTURE_PY'
from pathlib import Path
import plistlib, sys
root = Path(sys.argv[1])
good = {"system-entities": [{"dev-entry": "/dev/disk99"},
        {"dev-entry": "/dev/disk99s1", "mount-point": "/Volumes/驿览 · RelayGlance"}]}
(root / "mount.plist").write_bytes(plistlib.dumps(good))
good["system-entities"].append({"dev-entry": "/dev/disk99s2", "mount-point": "/Volumes/other"})
(root / "ambiguous.plist").write_bytes(plistlib.dumps(good))
(root / "malformed.plist").write_text("not a plist")
(root / "empty-mount.plist").write_bytes(plistlib.dumps({"system-entities": [
    {"dev-entry": "/dev/disk99"}, {"dev-entry": "/dev/disk99s1", "mount-point": ""}]}))
(root / "no-device.plist").write_bytes(plistlib.dumps({"system-entities": [
    {"dev-entry": "/dev/disk99s1", "mount-point": "/Volumes/RelayGlance"}]}))
MOUNT_FIXTURE_PY
t "mount parent device" "/dev/disk99" "$(mount_info "$TMP/mount.plist" device)"
t "mount Unicode path" "/Volumes/驿览 · RelayGlance" "$(mount_info "$TMP/mount.plist" mount)"
mount_info "$TMP/ambiguous.plist" mount >/dev/null; t "ambiguous mount rejected" 1 $?
mount_info "$TMP/malformed.plist" device >/dev/null; t "malformed receipt rejected" 1 $?
mount_info "$TMP/empty-mount.plist" mount >/dev/null; t "empty mount path rejected" 1 $?
mount_info "$TMP/no-device.plist" device >/dev/null; t "missing parent device rejected" 1 $?

echo
echo "RESULT: $PASSED passed, $FAILED failed"
[ "$FAILED" = "0" ] && exit 0 || exit 1
