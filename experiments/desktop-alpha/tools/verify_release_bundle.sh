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

# Structured receipts and before/after snapshots establish device ownership.
# hdiutil may reuse an already-attached image, so a returned device alone is
# never sufficient permission to detach it.
mount_info() { python3 "$SCRIPT_DIR/mount_receipt.py" "$2" "$1"; }
MOUNT_WORK=""
DEVICE=""
MNT=""
MOUNT_UNCERTAIN=0

mount_bundle() { # dmg; caller must always run cleanup_mount, even on failure
  local dmg="$1" attach_rc=0 candidate actual
  MOUNT_WORK=$(mktemp -d "${TMPDIR:-/tmp}/relayglance-verify.XXXXXX") || return 1
  DEVICE=""; MNT=""; MOUNT_UNCERTAIN=0
  if ! hdiutil info -plist >"$MOUNT_WORK/before.plist" 2>"$MOUNT_WORK/before.stderr"; then
    cat "$MOUNT_WORK/before.stderr" >&2; return 1
  fi
  python3 "$SCRIPT_DIR/mount_receipt.py" free "$MOUNT_WORK/before.plist" "$dmg" || return 1
  hdiutil attach "$dmg" -readonly -nobrowse -plist \
    >"$MOUNT_WORK/attach.plist" 2>"$MOUNT_WORK/attach.stderr" || attach_rc=$?
  if ! hdiutil info -plist >"$MOUNT_WORK/after.plist" 2>"$MOUNT_WORK/after.stderr"; then
    MOUNT_UNCERTAIN=1; return 1
  fi
  if ! DEVICE=$(python3 "$SCRIPT_DIR/mount_receipt.py" owned \
      "$MOUNT_WORK/before.plist" "$MOUNT_WORK/after.plist" "$dmg"); then
    DEVICE=""; MOUNT_UNCERTAIN=1; return 1
  fi
  # A failed attach may still have created exactly one provable new device.
  # Keep DEVICE for safe cleanup, but do not report a successful mount.
  if [ "$attach_rc" != 0 ]; then
    cat "$MOUNT_WORK/attach.stderr" >&2; return 1
  fi
  if [ -z "$DEVICE" ]; then
    MOUNT_UNCERTAIN=1
    echo "attach returned without a provably new owned device; no detach will be guessed" >&2
    return 1
  fi
  candidate=$(mount_info "$MOUNT_WORK/attach.plist" device) || return 1
  if [ "$candidate" != "$DEVICE" ]; then
    echo "attach did not produce a uniquely owned new device; refusing verification" >&2
    return 1
  fi
  MNT=$(mount_info "$MOUNT_WORK/attach.plist" mount) || return 1
  actual=$(python3 "$SCRIPT_DIR/mount_receipt.py" owned-mount \
    "$MOUNT_WORK/after.plist" "$dmg" "$DEVICE") || return 1
  [ "$MNT" = "$actual" ] || { echo "mount receipt/snapshot mismatch" >&2; return 1; }
}

cleanup_mount() {
  [ -n "$MOUNT_WORK" ] || return 0
  if [ -n "$DEVICE" ]; then
    if ! hdiutil detach "$DEVICE" >"$MOUNT_WORK/detach.log" 2>&1; then
      MOUNT_UNCERTAIN=1
    else
      DEVICE=""
    fi
  fi
  if [ "$MOUNT_UNCERTAIN" = 1 ]; then
    echo "cleanup outcome uncertain; no device guessed or force-detached; receipts retained: $MOUNT_WORK" >&2
    return 1
  fi
  rm -f "$MOUNT_WORK/before.plist" "$MOUNT_WORK/before.stderr" \
    "$MOUNT_WORK/after.plist" "$MOUNT_WORK/after.stderr" \
    "$MOUNT_WORK/attach.plist" "$MOUNT_WORK/attach.stderr" "$MOUNT_WORK/detach.log"
  rmdir "$MOUNT_WORK" || return 1
  MOUNT_WORK=""
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

# 3. Use the system-managed read-only mount, with proved new-device ownership.
# Custom mount points on ownership-disabled external APFS may be rejected.
finish() {
  local status=$?
  cleanup_mount || status=1
  trap - EXIT
  exit "$status"
}
trap finish EXIT
if mount_bundle "$DMG"; then
  pass "DMG mounts read-only (new owned device)"
else
  fail "DMG mounts / owned-device proof"
  echo "cannot continue without a verified task-owned mount"
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
