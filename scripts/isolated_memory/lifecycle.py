"""Finite lifecycle with model and separately gated remote-native IO."""
import copy
import hashlib
import json
import math
import re
import subprocess

from boundary_policy import BoundaryRefused
from guard_stack import clean_state, stack_valid
import identity_contract as identity
import identity_diagnostics as diagnostics
import resource_diagnostics as resources

HEX = re.compile(r'^[0-9a-f]{64}$')
GRANT = re.compile(r'^[0-9a-f]{32}$')
SCHEMA = 'hud_finite_attribution_pair_v2'
SCOPE = 'one_remote_same_trace_pair_async_v2_100min_no_retry_no_risk_acceptance'
CHECKPOINTS = ('ready', 'http', 'ws', 'finish')
ERRORS = {'prepared', 'authority', 'active', 'resource', 'claim', 'initialization',
          'source', 'spawn', 'identity', 'ready', 'http', 'ws', 'boundary', 'budget',
          'finish', 'cleanup', 'seal', 'internal', 'diagnostic'}
LIMITS = ['SELF_REPORTED_TRANSPORT_NOT_OS_ATTESTATION', 'RESTRICTED_SYNTHETIC_ENVIRONMENT',
          'NOT_OS_CONTAINMENT', 'NOT_UI_ACCEPTANCE', 'NOT_MEMORY_ACCEPTANCE',
          'RECORD_CONSISTENCY_NOT_OS_ATTESTATION', 'NONDETERMINISTIC_IO_DEADLINE']


def require(ok, code):
    if ok is not True:
        raise BoundaryRefused(code) from None


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def sha(data):
    require(type(data) is bytes, 'seal')
    return hashlib.sha256(data).hexdigest()


def encode(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)+'\n').encode()


def sources_valid(value):
    return (type(value) is dict and set(value) == {'candidate', 'public_source', 'fixture'}
            and all(type(v) is str and HEX.fullmatch(v) is not None for v in value.values()))


def transport_valid(value):
    return (type(value) is dict and set(value)=={'port','http_status','http_bytes','http_schema',
                                             'ws_frames','ws_bytes','ws_schema','handshakes'}
            and type(value['port']) is int and 1024<=value['port']<=65535 and value['port']!=9119
            and type(value['http_status']) is int and value['http_status']==200
            and type(value['http_bytes']) is int and 0<value['http_bytes']<=1048576
            and type(value['http_schema']) is int and value['http_schema']==1
            and type(value['ws_frames']) is int and value['ws_frames']==1
            and type(value['ws_bytes']) is int and 0<value['ws_bytes']<=1048576
            and type(value['ws_schema']) is int and value['ws_schema']==1
            and type(value['handshakes']) is int and value['handshakes']==1)


def authority_valid(row, now, freeze, review):
    return (type(row) is dict and set(row) == {'schema', 'id', 'scope', 'freeze_sha256',
                'review_sha256', 'issued', 'expires', 'max_runs', 'owner_confirmed'}
            and row['schema'] == SCHEMA and type(row['id']) is str
            and GRANT.fullmatch(row['id']) is not None and row['scope'] == SCOPE
            and type(freeze) is str and HEX.fullmatch(freeze) is not None
            and type(review) is str and HEX.fullmatch(review) is not None
            and row['freeze_sha256'] == freeze and row['review_sha256'] == review
            and finite(now) and finite(row['issued']) and finite(row['expires'])
            and row['issued'] <= now < row['expires'] and 0 < row['expires']-row['issued'] <= 3600
            and type(row['max_runs']) is int and row['max_runs'] == 1
            and row['owner_confirmed'] is True)


class ChildLifecycle:
    """The host integration keeps THIS object for all acknowledgments and exit."""
    def __init__(self, stack, source_start):
        require(sources_valid(source_start), 'source')
        self._stack, self._sources = stack, copy.deepcopy(source_start)
        self._next, self._failed = 0, False

    def acknowledge(self, label):
        try:
            require(self._next < len(CHECKPOINTS) and label == CHECKPOINTS[self._next], 'boundary')
            state = self._stack.checkpoint()
            self._next += 1
            return {'label': label, 'state': state}
        except BaseException:
            self._failed = True
            raise

    def terminal(self, source_end, commanded_exit, exit_code):
        # A swallowed denial or a premature/natural exit must not seal success.
        try:
            require(not self._failed and self._next == len(CHECKPOINTS), 'finish')
            require(commanded_exit is True and type(exit_code) is int and exit_code == 0, 'finish')
            require(sources_valid(source_end) and source_end == self._sources, 'source')
            state = self._stack.checkpoint()  # AFTER the host has finished, not only pre-TERM.
            return {'schema': 'hud_memory_child_terminal_v1', 'candidate': 'PASS',
                    'source_end': copy.deepcopy(source_end), 'state': state,
                    'commanded_exit': True, 'exit_code': 0}
        except BaseException:
            self._failed = True
            return {'schema': 'hud_memory_child_terminal_v1', 'candidate': 'FAIL',
                    'source_end': None, 'state': self._stack.state(),
                    'commanded_exit': commanded_exit is True,
                    'exit_code': exit_code if type(exit_code) is int and abs(exit_code)<10000 else None}


def child_valid(row):
    return (type(row) is dict and set(row) == {'schema', 'candidate', 'source_end', 'state',
                                             'commanded_exit', 'exit_code'}
            and row['schema'] == 'hud_memory_child_terminal_v1'
            and row['candidate'] in ('PASS', 'FAIL') and type(row['commanded_exit']) is bool
            and stack_valid(row['state'])
            and (row['exit_code'] is None or type(row['exit_code']) is int and abs(row['exit_code'])<10000)
            and (row['source_end'] is None or sources_valid(row['source_end'])))


def cleanup_valid(row):
    return (type(row) is dict and set(row) == {'identity_matched', 'alive', 'exit_code', 'error'}
            and type(row['identity_matched']) is bool
            and (row['alive'] is None or type(row['alive']) is bool)
            and (row['exit_code'] is None or type(row['exit_code']) is int and abs(row['exit_code'])<10000)
            and row['error'] in (None, 'identity', 'cleanup', 'unexpected_exit')
            and (row['alive'] is None or row['alive'] == (row['exit_code'] is None)))


def identity_valid(row):
    return (type(row) is dict and set(row) == {'pid', 'birth', 'cwd', 'argv', 'exe'}
            and type(row['pid']) is int and row['pid']>0 and finite(row['birth']) and row['birth']>0
            and all(type(row[k]) is str and row[k].startswith('/') and len(row[k])<=4096
                    and all(32<=ord(c)!=127 for c in row[k]) for k in ('cwd', 'exe'))
            and type(row['argv']) is list and 0<len(row['argv'])<=32
            and all(type(x) is str and 0<len(x)<=4096 and all(32<=ord(c)!=127 for c in x)
                    for x in row['argv']))


def close_owned(proc, expected, inspect):
    """Original handle poll; full identity before each signal. No PID-only cleanup."""
    out = {'identity_matched': False, 'alive': None, 'exit_code': None, 'error': None}
    try:
        code = proc.poll()
        if code is not None:
            require(type(code) is int and abs(code)<10000, 'cleanup')
            return dict(out, alive=False, exit_code=code, error='unexpected_exit')
        actual = inspect(proc)
        if not identity_valid(expected) or not identity_valid(actual) or actual != expected:
            return dict(out, error='identity')
        out['identity_matched'] = True
        proc.terminate()
        try:
            code = proc.wait(timeout=15)
        except (TimeoutError, subprocess.TimeoutExpired):
            code = proc.poll()
            if code is None:
                actual = inspect(proc)
                if not identity_valid(actual) or actual != expected:
                    return dict(out, error='identity')
                proc.kill()
                code = proc.wait(timeout=5)
        require(type(code) is int and abs(code)<10000, 'cleanup')
        return dict(out, alive=False, exit_code=code)
    except BaseException:
        return dict(out, error='cleanup')
