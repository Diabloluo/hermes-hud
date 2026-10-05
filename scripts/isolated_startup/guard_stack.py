"""Integrated audit composition, not an OS sandbox and not a native launcher."""
import copy
import os
from pathlib import Path
import sys
import threading

from audit_adapter import OpenAuditAdapter, checkpoint_before_success
from boundary_policy import BoundaryRefused, state_valid

EVENT_ERRORS = {'network_boundary', 'sqlite_boundary', 'child_process_boundary', 'signal_boundary'}
EXEC_EVENTS = {'subprocess.Popen', 'os.system', 'os.fork', 'os.exec', 'os.posix_spawn'}
SIGNAL_EVENTS = {'os.kill', 'os.killpg'}


def stack_valid(row):
    return (type(row) is dict and set(row) == {'schema', 'file', 'other_denials', 'last_error'}
            and row['schema'] == 'hud_smoke_guard_stack_v1' and state_valid(row['file'])
            and type(row['other_denials']) is int and 0 <= row['other_denials'] < 2**31
            and (row['last_error'] is None and row['other_denials'] == 0 or
                 type(row['last_error']) is str and row['last_error'] in EVENT_ERRORS
                 and row['other_denials'] > 0))


def clean_state(row):
    return stack_valid(row) and row['file']['denied_count'] == row['other_denials'] == 0


class GuardStack:
    """One policy instance for one child; non-open denials are also sticky."""
    def __init__(self, policy, frames, home, port):
        if type(port) is not int or not 1024 <= port <= 65535 or port == 9119:
            raise BoundaryRefused('network_boundary')
        self._adapter = OpenAuditAdapter(policy, frames)
        self._home, self._port = Path(home), port
        self._lock, self._denials, self._last = threading.Lock(), 0, None
        self._installed = False

    def _deny(self, code):
        with self._lock:
            self._denials = min(self._denials + 1, 2**31-1)
            self._last = code
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
                self._deny('network_boundary')
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
                self._deny('sqlite_boundary')
        elif event in EXEC_EVENTS:
            self._deny('child_process_boundary')
        elif event in SIGNAL_EVENTS:
            self._deny('signal_boundary')

    def install(self, register=sys.addaudithook):
        if self._installed:
            self._deny('child_process_boundary')
        # Set first: if either registration fails this stack cannot be retried.
        self._installed = True
        register(self.legacy_audit)
        register(self._adapter)

    def state(self):
        with self._lock:
            return {'schema': 'hud_smoke_guard_stack_v1',
                    'file': self._adapter.policy.state(),
                    'other_denials': self._denials, 'last_error': self._last}

    def checkpoint(self):
        checkpoint_before_success(self._adapter)
        row = self.state()
        if not clean_state(row):
            raise BoundaryRefused('control') from None
        return copy.deepcopy(row)
