#!/bin/bash
# verify_release_bundle.sh — DR-3C release bundle verifier (unsigned scope).
#
# Checks:
#   canonical filename · SHA256SUMS.txt contract (REQUIRED, no SKIP) ·
#   exact architecture via `lipo -archs` (arm64 only) · bundle identifier ·
#   Desktop version · RelayGlance radar icon bytes · no desktop-test-hooks ·
#   no test instrumentation strings · DMG mounts · Applications symlink
#
# Future DR-4/DR-5 extend: Developer ID signature, Hardened Runtime,
# notarization, stapling, Gatekeeper — reported SKIP, never faked.
#
# Source mode: VERIFY_SOURCE=1 source this file to load only the check
# functions (used by test_verify_release_bundle.sh).
set -u

EXPECTED_VERSION="0.1.1"
EXPECTED_PRODUCT_NAME="驿览 · RelayGlance"
EXPECTED_DMG_NAME="RelayGlance-Desktop-${EXPECTED_VERSION}-macOS-arm64.dmg"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXPECTED_ICON="$SCRIPT_DIR/../icons/icon.icns"

canonical_name_ok() { [ "$1" = "$EXPECTED_DMG_NAME" ]; }

# ---------- A. SHA256SUMS.txt contract (canonical) ----------
# sha256_ok <dmg> <sums_file> <dmg_basename>
# returns: 0 = exact match · 1 = sums absent · 2 = entry absent · 3 = mismatch · 4 = duplicate entry
sha256_ok() {
  local dmg="$1" sums="$2" base="$3"
  [ -f "$sums" ] || return 1
  local want count
  # Match the whole filename, never an entry such as release.dmg.bak.
  count=$(awk -v base="$base" 'substr($0, 67) == base { n++ } END { print n+0 }' "$sums")
  [ "$count" != "0" ] || return 2
  [ "$count" = "1" ] || return 4
  want=$(awk -v base="$base" 'substr($0, 67) == base { print substr($0, 1, 64) }' "$sums")
  [ "$(shasum -a 256 "$dmg" | awk '{print $1}')" = "$want" ] || return 3
  return 0
}

# ---------- B. Exact architecture (`lipo -archs`, mechanical) ----------
# arch_ok <lipo_output> — exactly "arm64" passes; anything else fails.
arch_ok() { [ "$1" = "arm64" ]; }

# Parse hdiutil's structured receipt rather than guessing the mount point.
# A parent device is used for cleanup; never detach an unrelated volume.
mount_info() { # attach_plist device|mount
  python3 - "$1" "$2" <<'MOUNT_INFO_PY'
import pathlib, plistlib, re, sys
try:
    entities = plistlib.loads(pathlib.Path(sys.argv[1]).read_bytes())["system-entities"]
    if sys.argv[2] == "device":
        values = [e["dev-entry"] for e in entities
                  if re.fullmatch(r"/dev/disk[0-9]+", e.get("dev-entry", ""))]
    elif sys.argv[2] == "mount":
        values = [e["mount-point"] for e in entities if e.get("mount-point")]
    else:
        raise ValueError("unknown field")
    if len(values) != 1 or not values[0].startswith("/") or "\n" in values[0]:
        raise ValueError("expected exactly one absolute device/mount path")
    print(values[0])
except (KeyError, ValueError, OSError, plistlib.InvalidFileException):
    sys.exit(1)
MOUNT_INFO_PY
}

if [ "${VERIFY_SOURCE:-}" = "1" ]; then
  return 0 2>/dev/null || exit 0
fi

DMG="${1:-}"
if [ -z "$DMG" ] || [ ! -f "$DMG" ]; then
  echo "usage: $0 <release.dmg>"
  echo "expected: $EXPECTED_DMG_NAME"
  exit 2
fi
DMG_BASENAME="$(basename "$DMG")"
SUM_FILE="$(dirname "$DMG")/SHA256SUMS.txt"

FAIL=0
say()  { printf '%-42s %s\n' "$1" "$2"; }
pass() { say "$1" "PASS"; }
fail() { say "$1" "FAIL"; FAIL=1; }
skip() { say "$1" "SKIP (DR-4/DR-5)"; }

# 1. canonical filename
if canonical_name_ok "$DMG_BASENAME"; then
  pass "canonical filename"
else
  fail "canonical filename (got: $DMG_BASENAME)"
fi

# 2. SHA256SUMS.txt contract
rc=0
sha256_ok "$DMG" "$SUM_FILE" "$DMG_BASENAME"; rc=$?
case $rc in
  0) pass "SHA256SUMS.txt hash exact match" ;;
  1) fail "SHA256SUMS.txt present (absent)" ;;
  2) fail "SHA256SUMS.txt entry for $DMG_BASENAME (missing)" ;;
  3) fail "SHA256SUMS.txt hash mismatch" ;;
  4) fail "SHA256SUMS.txt duplicate entry" ;;
esac

# Fail closed before mounting an incorrectly named or unverified image.
[ "$FAIL" = "0" ] || { echo "RESULT: FAIL — NOT FOR DISTRIBUTION"; exit 1; }

# 3. Read-only mount at the system-managed /Volumes location. Some macOS
# versions reject custom mount points on external APFS volumes with ownership
# disabled. Do not change disk ownership/security settings to work around it.
ATTACH_PLIST=$(mktemp "${TMPDIR:-/tmp}/relayglance-attach.XXXXXX") || exit 1
ATTACH_LOG="${ATTACH_PLIST}.stderr"
DEVICE=""
cleanup() {
  local status=$?
  if [ -n "$DEVICE" ]; then
    if ! hdiutil detach "$DEVICE" >/dev/null 2>&1; then
      echo "cleanup failed: could not detach task-owned $DEVICE" >&2
      status=1
    fi
  fi
  rm -f "$ATTACH_PLIST" "$ATTACH_LOG"
  trap - EXIT
  exit "$status"
}
trap cleanup EXIT
if hdiutil attach "$DMG" -readonly -nobrowse -plist >"$ATTACH_PLIST" 2>"$ATTACH_LOG"; then
  DEVICE=$(mount_info "$ATTACH_PLIST" device) || {
    fail "attached device receipt"; exit 1;
  }
  MNT=$(mount_info "$ATTACH_PLIST" mount) || {
    fail "single mounted volume receipt"; exit 1;
  }
  pass "DMG mounts read-only"
else
  fail "DMG mounts"
  cat "$ATTACH_LOG" >&2
  echo "cannot continue without mounted DMG"
  exit 1
fi

# 4. Applications symlink
[ -L "$MNT/Applications" ] && [ "$(readlink "$MNT/Applications")" = "/Applications" ] \
  && pass "Applications symlink" || fail "Applications symlink"

APP="$MNT/$EXPECTED_PRODUCT_NAME.app"
[ -d "$APP" ] && pass "app bundle display name" || fail "app bundle display name"
BIN="$APP/Contents/MacOS/hermes-hud-desktop"
PLIST="$APP/Contents/Info.plist"

# 5. exact architecture
ARCH_OUT=$(lipo -archs "$BIN" 2>/dev/null)
if arch_ok "$ARCH_OUT"; then
  pass "exact architecture = arm64"
else
  fail "exact architecture (lipo -archs = '${ARCH_OUT:-unreadable}')"
fi

# 6. bundle identifier
BID=$(/usr/libexec/PlistBuddy -c "Print :CFBundleIdentifier" "$PLIST" 2>/dev/null)
[ "$BID" = "com.diabloluo.hermes-hud-desktop" ] && pass "bundle identifier" || fail "bundle identifier (got: $BID)"

# Display name changes, executable identity does not.
NAME=$(/usr/libexec/PlistBuddy -c "Print :CFBundleName" "$PLIST" 2>/dev/null)
[ "$NAME" = "$EXPECTED_PRODUCT_NAME" ] && pass "bundle display name" || fail "bundle display name (got: $NAME)"
EXE=$(/usr/libexec/PlistBuddy -c "Print :CFBundleExecutable" "$PLIST" 2>/dev/null)
[ "$EXE" = "hermes-hud-desktop" ] && pass "executable identity" || fail "executable identity (got: $EXE)"

# 7. Desktop version
VER=$(/usr/libexec/PlistBuddy -c "Print :CFBundleShortVersionString" "$PLIST" 2>/dev/null)
[ "$VER" = "$EXPECTED_VERSION" ] && pass "desktop version $EXPECTED_VERSION" || fail "desktop version (got: $VER)"

# 8. Exact source icon, not merely any icon.icns bearing that filename.
ICON="$APP/Contents/Resources/icon.icns"
if [ -f "$ICON" ] && cmp -s "$ICON" "$EXPECTED_ICON"; then
  pass "RelayGlance radar icon.icns exact bytes"
else
  fail "RelayGlance radar icon.icns exact bytes"
fi

# 9. no desktop-test-hooks
HOOKS=$(strings "$BIN" | grep -cF "desktop-test-hooks" || true)
[ "$HOOKS" = "0" ] && pass "no desktop-test-hooks string" || fail "desktop-test-hooks present ($HOOKS)"

# 10. no test instrumentation strings
BAD=0
for s in HUD_HERMES_BIN HUD_DESKTOP_TEST_HOME HUD_DESKTOP_AUTOSTART \
         HUD_DESKTOP_TEST_MODE /tmp/hud-state.log /tmp/hud-handshake.log \
         /tmp/hud-detect.log; do
  c=$(strings "$BIN" | grep -cF "$s" || true)
  [ "$c" = "0" ] || { echo "    test string present: $s ($c)"; BAD=1; }
done
[ "$BAD" = "0" ] && pass "no test instrumentation strings" || fail "test instrumentation strings"

# 11. future signing checks (NOT faked)
skip "Developer ID signature"
skip "Hardened Runtime"
skip "notarization"
skip "stapling"
skip "Gatekeeper downloaded-file test"


if [ "$FAIL" = "1" ]; then
  echo
  echo "RESULT: FAIL — NOT FOR DISTRIBUTION"
  exit 1
fi
echo
echo "RESULT: PASS (structure verification only) — NOT A DISTRIBUTION APPROVAL"
exit 0
