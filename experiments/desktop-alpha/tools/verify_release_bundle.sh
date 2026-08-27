#!/bin/bash
# verify_release_bundle.sh — DR-3C release bundle verifier (unsigned scope).
#
# Checks:
#   canonical filename · SHA256SUMS.txt contract (REQUIRED, no SKIP) ·
#   exact architecture via `lipo -archs` (arm64 only) · bundle identifier ·
#   Desktop version · Observer Core icon · no desktop-test-hooks ·
#   no test instrumentation strings · DMG mounts · Applications symlink
#
# Future DR-4/DR-5 extend: Developer ID signature, Hardened Runtime,
# notarization, stapling, Gatekeeper — reported SKIP, never faked.
#
# Source mode: VERIFY_SOURCE=1 source this file to load only the check
# functions (used by test_verify_release_bundle.sh).
set -u

# ---------- A. SHA256SUMS.txt contract (canonical) ----------
# sha256_ok <dmg> <sums_file> <dmg_basename>
# returns: 0 = exact match · 1 = sums absent · 2 = entry absent · 3 = mismatch
sha256_ok() {
  local dmg="$1" sums="$2" base="$3"
  [ -f "$sums" ] || return 1
  grep -qF "  $base" "$sums" || return 2
  local want
  want=$(grep -F "  $base" "$sums" | awk '{print $1}' | head -1)
  [ "$(shasum -a 256 "$dmg" | awk '{print $1}')" = "$want" ] || return 3
  return 0
}

# ---------- B. Exact architecture (`lipo -archs`, mechanical) ----------
# arch_ok <lipo_output> — exactly "arm64" passes; anything else fails.
arch_ok() { [ "$1" = "arm64" ]; }

if [ "${VERIFY_SOURCE:-}" = "1" ]; then
  return 0 2>/dev/null || exit 0
fi

DMG="${1:-}"
if [ -z "$DMG" ] || [ ! -f "$DMG" ]; then
  echo "usage: $0 <release.dmg>"
  echo "expected: Hermes-HUD-Desktop-0.1.0-macOS-arm64.dmg"
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
case "$DMG_BASENAME" in
  Hermes-HUD-Desktop-0.1.0-macOS-arm64.dmg) pass "canonical filename" ;;
  *) fail "canonical filename (got: $DMG_BASENAME)" ;;
esac

# 2. SHA256SUMS.txt contract
rc=0
sha256_ok "$DMG" "$SUM_FILE" "$DMG_BASENAME"; rc=$?
case $rc in
  0) pass "SHA256SUMS.txt hash exact match" ;;
  1) fail "SHA256SUMS.txt present (absent)" ;;
  2) fail "SHA256SUMS.txt entry for $DMG_BASENAME (missing)" ;;
  3) fail "SHA256SUMS.txt hash mismatch" ;;
esac

# 3. mount DMG
MNT=$(mktemp -d /tmp/hud-verify.XXXXXX)
if hdiutil attach "$DMG" -nobrowse -mountpoint "$MNT" >/dev/null 2>&1; then
  pass "DMG mounts"
else
  fail "DMG mounts"
  echo "cannot continue without mounted DMG"
  exit 1
fi

# 4. Applications symlink
[ -L "$MNT/Applications" ] && pass "Applications symlink" || fail "Applications symlink"

APP="$MNT/Hermes HUD.app"
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

# 7. Desktop version
VER=$(/usr/libexec/PlistBuddy -c "Print :CFBundleShortVersionString" "$PLIST" 2>/dev/null)
[ "$VER" = "0.1.0" ] && pass "desktop version 0.1.0" || fail "desktop version (got: $VER)"

# 8. Observer Core icon
[ -f "$APP/Contents/Resources/icon.icns" ] && pass "Observer Core icon.icns" || fail "Observer Core icon.icns"

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

hdiutil detach "$MNT" >/dev/null 2>&1
rmdir "$MNT" 2>/dev/null

if [ "$FAIL" = "1" ]; then
  echo
  echo "RESULT: FAIL — NOT FOR DISTRIBUTION"
  exit 1
fi
echo
echo "RESULT: PASS (unsigned verification scope) — UNSIGNED / NOT FOR DISTRIBUTION"
exit 0
