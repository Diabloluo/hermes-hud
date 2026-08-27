#!/bin/bash
# test_verify_release_bundle.sh — DR-3C verifier regression fixtures.
# Loads check functions via source mode; no DMG mounting needed.
set -u

SRC="$(dirname "$0")/verify_release_bundle.sh"
VERIFY_SOURCE=1
# shellcheck disable=SC1090
. "$SRC"

TMP=$(mktemp -d /tmp/dr3c-test.XXXXXX)
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

echo
echo "RESULT: $PASSED passed, $FAILED failed"
[ "$FAILED" = "0" ] && exit 0 || exit 1
