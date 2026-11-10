"""Mock complete mount/cleanup flows. Never touches a real image or device."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / "experiments/desktop-alpha/tools/verify_release_bundle.sh"
MOCK = r'''import os, pathlib, plistlib, sys
root=pathlib.Path(os.environ['MOCK_ROOT']); mode=os.environ['MOCK_MODE']
target=str(root/'candidate.dmg')
args=sys.argv[1:]
with (root/'calls').open('a') as f: f.write(' '.join(args)+'\n')
def image(device, path=target):
 return {'image-path':path,'system-entities':[{'dev-entry':device},
  {'dev-entry':device+'s1','mount-point':'/Volumes/驿览 · RelayGlance'}]}
def emit(data): sys.stdout.buffer.write(plistlib.dumps(data))
if args[0]=='info':
 after=(root/'attached').exists()
 if mode=='bad-before' and not after: print('bad plist'); sys.exit(0)
 if mode=='uncertain' and after: print('bad plist'); sys.exit(0)
 if mode=='existing': emit({'images':[image('/dev/disk42')]})
 elif mode=='reused': emit({'images':[image('/dev/disk42',target if after else str(root/'other.dmg'))]})
 elif after and mode!='failed-none': emit({'images':[image('/dev/disk99')]})
 else: emit({'images':[]})
elif args[0]=='attach':
 (root/'attached').touch()
 if mode in ('failed-partial','failed-none','uncertain'):
  print('simulated attach failure',file=sys.stderr); sys.exit(1)
 if mode=='bad-receipt': print('malformed receipt')
 else: emit(image('/dev/disk42' if mode=='reused' else '/dev/disk99'))
elif args[0]=='detach':
 if mode=='detach-failure': print('simulated detach failure',file=sys.stderr); sys.exit(1)
else: sys.exit(2)
'''
RUN = r'''VERIFY_SOURCE=1 source "$1"
mount_bundle "$2"; result=$?
cleanup_mount; cleanup=$?
printf 'RESULT=%s CLEANUP=%s\n' "$result" "$cleanup"
[ "$result" = 0 ] && [ "$cleanup" = 0 ]
'''


class MountOwnershipTests(unittest.TestCase):
    def scenario(self, mode):
        with tempfile.TemporaryDirectory(prefix="relayglance-mount-test-") as folder:
            root = Path(folder)
            (root / "candidate.dmg").write_bytes(b"fixture only, not an image")
            (root / "other.dmg").write_bytes(b"other fixture")
            (root / "bin").mkdir()
            (root / "tmp").mkdir()
            mock = root / "bin/hdiutil"
            mock.write_text(f"#!{sys.executable}\n" + MOCK)
            mock.chmod(0o755)
            env = os.environ.copy()
            env.update(PATH=str(root / "bin") + os.pathsep + env["PATH"],
                       MOCK_ROOT=str(root), MOCK_MODE=mode, TMPDIR=str(root / "tmp"))
            result = subprocess.run(["bash", "-c", RUN, "test", str(VERIFIER), str(root / "candidate.dmg")],
                                    env=env, capture_output=True, text=True, timeout=15)
            calls = (root / "calls").read_text().splitlines()
            dirs = list((root / "tmp").iterdir())
            retained = any((d / "attach.plist").exists() and (d / "attach.stderr").exists() for d in dirs)
            return result, calls, bool(dirs), retained

    def test_new_device_is_detached_once(self):
        result, calls, remains, _ = self.scenario("normal")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([c for c in calls if c.startswith("detach")], ["detach /dev/disk99"])
        self.assertFalse(remains)

    def test_existing_target_is_not_attached_or_detached(self):
        result, calls, remains, _ = self.scenario("existing")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(c.startswith(("attach", "detach")) for c in calls))
        self.assertFalse(remains)

    def test_reused_existing_device_is_never_detached(self):
        result, calls, remains, retained = self.scenario("reused")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(c.startswith("detach") for c in calls))
        self.assertTrue(remains and retained)
        self.assertIn("cleanup outcome uncertain", result.stderr)

    def test_bad_attach_receipt_cleans_only_proved_new_device(self):
        result, calls, remains, _ = self.scenario("bad-receipt")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual([c for c in calls if c.startswith("detach")], ["detach /dev/disk99"])
        self.assertFalse(remains)

    def test_failed_partial_attach_cleans_only_proved_new_device(self):
        result, calls, remains, _ = self.scenario("failed-partial")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual([c for c in calls if c.startswith("detach")], ["detach /dev/disk99"])
        self.assertFalse(remains)

    def test_failed_attach_without_device_never_detaches(self):
        result, calls, remains, _ = self.scenario("failed-none")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(c.startswith("detach") for c in calls))
        self.assertFalse(remains)

    def test_uncertain_outcome_preserves_receipts_without_guessing(self):
        result, calls, remains, retained = self.scenario("uncertain")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(c.startswith("detach") for c in calls))
        self.assertTrue(remains and retained)
        self.assertIn("cleanup outcome uncertain", result.stderr)

    def test_bad_initial_snapshot_prevents_attach(self):
        result, calls, remains, _ = self.scenario("bad-before")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(c.startswith(("attach", "detach")) for c in calls))
        self.assertFalse(remains)

    def test_detach_failure_preserves_receipts_and_does_not_force(self):
        result, calls, remains, retained = self.scenario("detach-failure")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual([c for c in calls if c.startswith("detach")], ["detach /dev/disk99"])
        self.assertTrue(remains and retained)
        self.assertIn("cleanup outcome uncertain", result.stderr)


if __name__ == "__main__":
    unittest.main()
