#!/bin/bash
# verify_release_bundle.sh — DR-3C release bundle verifier (pre-signing scope).
#
# Checks available WITHOUT a Developer ID identity:
#   filename · architecture = arm64 · bundle identifier · Desktop version ·
#   Observer Core icon present · no desktop-test-hooks · no test instrumentation
#   strings · DMG mounts · Applications symlink · SHA256 matches
#
# Future DR-4/DR-5 will extend: Developer ID signature, Hardened Runtime,
# notarization, stapling, Gatekeeper. Those checks are NOT faked here —
# they simply do not exist yet and are reported as SKIP.
set -u

DMG="${1:-}"
if [ -z "$DMG" ] || [ ! -f "$DMG" ]; then
  echo "usage: $0 <release.dmg>"
  echo "expected name: Hermes-HUD-Desktop-0.1.0-macOS-arm64.dmg"
  exit 2
fi

FAIL=0
say()  { printf '%-42s %s\n' "$1" "$2"; }
pass() { say "$1" "PASS"; }
fail() { say "$1" "FAIL"; FAIL=1; }
skip() { say "$1" "SKIP (DR-4/DR-5)"; }

# 1. canonical filename
case "$(basename "$DMG")" in
  Hermes-HUD-Desktop-0.1.0-macOS-arm64.dmg) pass "canonical filename" ;;
  *) fail "canonical filename (got: $(basename "$DMG"))" ;;
esac

# 2. SHA256
EXPECTED="${DMG}.sha256"
if [ -f "$EXPECTED" ]; then
  actual=$(shasum -a 256 "$DMG" | awk '{print $1}')
  want=$(awk '{print $1}' "$EXPECTED")
  if [ "$actual" = "$want" ]; then pass "SHA256 matches"; else fail "SHA256 mismatch"; fi
else
  skip "SHA256 (no .sha256 file provided)"
fi

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

# 5. bundle identifier
BID=$(/usr/libexec/PlistBuddy -c "Print :CFBundleIdentifier" "$PLIST" 2>/dev/null)
[ "$BID" = "com.diabloluo.hermes-hud-desktop" ] && pass "bundle identifier" || fail "bundle identifier (got: $BID)"

# 6. Desktop version
VER=$(/usr/libexec/PlistBuddy -c "Print :CFBundleShortVersionString" "$PLIST" 2>/dev/null)
[ "$VER" = "0.1.0" ] && pass "desktop version 0.1.0" || fail "desktop version (got: $VER)"

# 7. architecture
ARCH=$(lipo -info "$BIN" 2>/dev/null)
echo "$ARCH" | grep -q "arm64" && pass "architecture = arm64" || fail "architecture ($ARCH)"

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
codesign --verify --deep --strict "$APP" >/dev/null 2>&1 && pass "adhoc/legacy codesign" || true
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
