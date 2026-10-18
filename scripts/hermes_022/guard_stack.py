"""Integrated audit composition, not an OS sandbox and not a native launcher."""
import copy
import os
from pathlib import Path
import sys
import threading

from audit_adapter import OpenAuditAdapter, checkpoint_before_success
from boundary_policy import BoundaryRefused, state_valid
from optional_process import LAUNCHCTL_LIMIT, missing_allowed, project, denial_valid

EVENT_ERRORS = {'network_boundary', 'sqlite_boundary', 'child_process_boundary', 'signal_boundary'}
EXEC_EVENTS = {'subprocess.Popen', 'os.system', 'os.fork', 'os.exec', 'os.posix_spawn'}
SIGNAL_EVENTS = {'os.kill', 'os.killpg'}


def stack_valid(row):
    return (type(row) is dict and set(row) == {'schema', 'file', 'other_denials', 'last_error',
                                               'launchctl_missing', 'last_other_denial'}
            and row['schema'] == 'hud_memory_guard_stack_v1' and state_valid(row['file'])
            and type(row['launchctl_missing']) is int and 0 <= row['launchctl_missing'] <= LAUNCHCTL_LIMIT
            and type(row['other_denials']) is int and 0 <= row['other_denials'] < 2**31
            and (row['last_error'] is None and row['last_other_denial'] is None and row['other_denials'] == 0 or
                 type(row['last_error']) is str and row['last_error'] in EVENT_ERRORS
                 and row['other_denials'] > 0 and denial_valid(row['last_other_denial'])
                 and row['last_error'] == row['last_other_denial']['error']))


def clean_state(row):
    return stack_valid(row) and row['file']['denied_count'] == row['other_denials'] == 0


class GuardStack:
    """One policy instance for one child; non-open denials are also sticky."""
    def __init__(self, policy, frames, home, port, owner_uid=None, platform='other'):
        if type(port) is not int or not 1024 <= port <= 65535 or port == 9119:
            raise BoundaryRefused('network_boundary')
        self._adapter = OpenAuditAdapter(policy, frames)
        self._home, self._port = Path(home), port
        self._lock, self._denials, self._last = threading.Lock(), 0, None
        self._frames, self._uid, self._platform = frames, owner_uid, platform
        self._launchctl_missing, self._last_denial = 0, None
        self._installed = False

    def _caller(self):
        try:
            return self._frames.collect(sys._getframe(1))
        except Exception:
            return None  # No exception text, unbound pathname or raw argument.

    def _deny(self, code, event='unspecified', caller=None):
        with self._lock:
            self._denials = min(self._denials + 1, 2**31-1)
            self._last = code
            self._last_denial = project(code, event, caller)
        raise BoundaryRefused(code) from None

    def legacy_audit(self, event, args):
        # Deliberately excludes open. The adapter MUST be a separate audit hook:
        # a Python wrapper would make its immediate frame this file, not the
        # bound public source, and break the exact two missing-resource sites.
        if event in ('socket.bind', 'socket.connect'):
            try:
                a = args[1]
                ok = (type(a) is tuple and len(a) in (2, 4)
                      and a[0] in ('127.0.0.1', '::1') and type(a[1]) is int
                      and a[1] == self._port and a[1] != 9119)
            except Exception:
                ok = False
            if not ok:
                self._deny('network_boundary', event, self._caller())
        elif event == 'sqlite3.connect':
            try:
                raw = args[0]
                ok = type(raw) is str
                if ok:
                    raw = raw.split('?', 1)[0].removeprefix('file:')
                    ok = Path(raw).resolve().is_relative_to(self._home)
            except Exception:
                ok = False
            if not ok:
                self._deny('sqlite_boundary', event, self._caller())
        elif event in EXEC_EVENTS:
            caller = self._caller()
            with self._lock:
                if missing_allowed(event, args, caller, self._platform, self._uid, self._launchctl_missing):
                    self._launchctl_missing += 1
                    # Never return to Popen: no subprocess is authorized here.
                    raise FileNotFoundError('isolated_optional_diagnostic_unavailable') from None
            self._deny('child_process_boundary', event, caller)
        elif event in SIGNAL_EVENTS:
            self._deny('signal_boundary', event, self._caller())

    def install(self, register=sys.addaudithook):
        if self._installed:
            self._deny('child_process_boundary', 'duplicate_install', self._caller())
        # Set first: if either registration fails this stack cannot be retried.
        self._installed = True
        register(self.legacy_audit)
        register(self._adapter)

    def state(self):
        with self._lock:
            return {'schema': 'hud_memory_guard_stack_v1',
                    'file': self._adapter.policy.state(),
                    'other_denials': self._denials, 'last_error': self._last,
                    'launchctl_missing': self._launchctl_missing,
                    'last_other_denial': copy.deepcopy(self._last_denial)}

    def checkpoint(self):
        checkpoint_before_success(self._adapter)
        row = self.state()
        if not clean_state(row):
            raise BoundaryRefused('control') from None
        return copy.deepcopy(row)
