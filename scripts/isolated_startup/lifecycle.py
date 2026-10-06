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

HEX = re.compile(r'^[0-9a-f]{64}$')
GRANT = re.compile(r'^[0-9a-f]{32}$')
SCHEMA = 'hud_short_startup_backend_v3'
SCOPE = 'one_owned_direct_interpreter_startup_300s_http1_ws1_no_retry_no_risk_acceptance'
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
            return {'schema': 'hud_short_child_terminal_v1', 'candidate': 'PASS',
                    'source_end': copy.deepcopy(source_end), 'state': state,
                    'commanded_exit': True, 'exit_code': 0}
        except BaseException:
            self._failed = True
            return {'schema': 'hud_short_child_terminal_v1', 'candidate': 'FAIL',
                    'source_end': None, 'state': self._stack.state(),
                    'commanded_exit': commanded_exit is True,
                    'exit_code': exit_code if type(exit_code) is int and abs(exit_code)<10000 else None}


def child_valid(row):
    return (type(row) is dict and set(row) == {'schema', 'candidate', 'source_end', 'state',
                                             'commanded_exit', 'exit_code'}
            and row['schema'] == 'hud_short_child_terminal_v1'
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


def execute_model_io(io, authority, freeze, review):
    """Models remain MODEL; NativeIO requires independent remote/freeze/grant gates.

    Claim contract: exclusive x-create, never delete on failure. init is after
    claim. HTTP/WS methods consume one call each; no retries. inspect is full
    parent-bound identity. token/raw transport must never enter acknowledgments.
    """
    started, proc, expected, stage = io.clock(), None, None, 'prepared'
    failure_site='prepared'
    row = {'schema': SCHEMA, 'result': 'PENDING_TERMINAL_SEAL', 'candidate': 'FAIL',
           'error': None, 'cleanup_error': None, 'authority_id': None,
           'source_start': None, 'source_end': None, 'checkpoints': [],
           'http_calls': 0, 'ws_calls': 0, 'child': None, 'cleanup': None,
           'seconds': None, 'limits': LIMITS[:], 'memory_risk': 'WARN_NOT_ACCEPTED',
           'public_release': 'BLOCK', 'execution_kind':getattr(io,'execution_kind','MODEL'),
           'transport':None, 'failure_stage':None, 'identity_diagnostic':None,
           'cleanup_diagnostic':None, 'handle_observation':None}
    def budget(reserve=20):
        now = io.clock()
        require(finite(now) and finite(started) and 0<=now-started<300-reserve, 'budget')
    def checkpoint(label):
        nonlocal failure_site
        failure_site='check_'+label
        io.check(proc, expected)  # Full identity and running resources before every operation.
        failure_site='ack_'+label
        ack = io.acknowledge(label)
        require(type(ack) is dict and set(ack) == {'label', 'state'}
                and ack['label'] == label and clean_state(ack['state']), 'boundary')
        row['checkpoints'].append(copy.deepcopy(ack))
    try:
        require(row['execution_kind'] in ('MODEL','NATIVE'), 'prepared')
        require(io.prepared(freeze) is True, 'prepared')
        stage = 'authority'
        failure_site=stage
        require(authority_valid(authority, io.wall(), freeze, review), 'authority')
        stage = 'active'
        failure_site=stage
        require(io.no_active() is True, 'active')
        stage = 'resource'
        failure_site=stage
        require(io.resources() is True, 'resource')
        budget()
        stage = 'claim'
        failure_site=stage
        io.claim(authority['id'])
        row['authority_id'] = authority['id']
        stage = 'initialization'
        failure_site=stage
        io.initialize()
        stage = 'source'
        failure_site=stage
        source = io.sources()
        require(sources_valid(source), 'source')
        row['source_start'] = copy.deepcopy(source)
        budget()
        stage = 'spawn'
        failure_site=stage
        proc = io.spawn()
        # Retain the handle BEFORE binding. An exception while binding cannot
        # discard ownership; cleanup receives no authority and sends no signal.
        failure_site='expected'
        expected = io.expected(proc)
        stage = 'identity'
        failure_site=stage
        require(identity_valid(expected), 'identity')
        io.check(proc, expected)
        stage = 'ready'
        failure_site=stage
        io.ready(proc, expected)
        checkpoint('ready')
        budget()
        stage = 'http'
        failure_site=stage
        row['http_calls'] = 1  # Attempts, including failures, never successes-only counters.
        io.http_once()
        checkpoint('http')
        budget()
        stage = 'ws'
        failure_site=stage
        row['ws_calls'] = 1
        io.ws_once()
        checkpoint('ws')
        if row['execution_kind']=='NATIVE':
            failure_site='transport'
            transport=io.transport()
            require(transport_valid(transport),'ws')
            row['transport']=copy.deepcopy(transport)
        budget()
        stage = 'finish'
        failure_site=stage
        checkpoint('finish')
        failure_site='finish';io.request_finish()
    except BaseException as error:
        row['failure_stage']=failure_site
        row['error'] = (error.args[0] if type(error) is BoundaryRefused and len(error.args)==1
                        and type(error.args[0]) is str and error.args[0] in ERRORS else stage)
    finally:
        if proc is not None:
            # Binding failure must not discard a prebound original-handle
            # cleanup seed. This does not authorize an unverified signal:
            # close_owned still requires an exact live five-field match.
            cleanup_expected=expected
            if not identity_valid(cleanup_expected):
                try:
                    getter=getattr(io,'cleanup_expected',None)
                    cleanup_expected=getter(proc) if callable(getter) else None
                except BaseException:
                    cleanup_expected=None
            inspections=[0]
            def cleanup_inspect(handle):
                inspections[0]+=1
                prefix='pre_term' if inspections[0]==1 else 'pre_kill'
                try:
                    actual=io.inspect(handle)
                except BaseException as error:
                    if row['cleanup_diagnostic'] is None:
                        row['cleanup_diagnostic']=diagnostics.project(prefix+'_inspect',
                            inspection_error=identity.exception_code(error))
                    raise
                if not identity_valid(cleanup_expected) or not identity_valid(actual) or actual!=cleanup_expected:
                    if row['cleanup_diagnostic'] is None:
                        row['cleanup_diagnostic']=diagnostics.project(prefix+'_match',cleanup_expected,actual)
                return actual
            row['cleanup'] = close_owned(proc, cleanup_expected, cleanup_inspect)
            if not (cleanup_valid(row['cleanup']) and row['cleanup']['identity_matched'] is True
                    and row['cleanup']['alive'] is False and row['cleanup']['error'] is None):
                row['cleanup_error'] = 'cleanup'
                if row['failure_stage'] is None:row['failure_stage']='cleanup'
        row['handle_observation']=diagnostics.observe_handle(proc)
        try:
            getter=getattr(io,'identity_diagnostic',None)
            row['identity_diagnostic']=diagnostics.snapshot(getter() if callable(getter) else None)
        except BaseException:
            if row['error'] is None:row['error']='diagnostic'
            if row['failure_stage'] is None:row['failure_stage']='diagnostic'
        try:
            if proc is not None:
                failure_site='child_terminal'
                terminal = io.child_terminal()
                require(child_valid(terminal), 'finish')
                row['child'] = copy.deepcopy(terminal)
            if row['source_start'] is not None:
                failure_site='source_end'
                source = io.sources()
                require(sources_valid(source), 'source')
                row['source_end'] = copy.deepcopy(source)
                require(row['source_start'] == row['source_end'], 'source')
            if row['error'] is None and row['cleanup_error'] is None:
                failure_site='acceptance'
                child = row['child']
                require(child_valid(child) and child['candidate']=='PASS'
                        and clean_state(child['state']) and child['commanded_exit'] is True
                        and child['exit_code']==0 and child['source_end']==row['source_end'], 'finish')
                # Child records host-main status before final interpreter exit.
                # Safe cleanup alone (including KILL) is not startup acceptance.
                actual_exit = row['cleanup']['exit_code']
                require(type(actual_exit) is int and actual_exit == 0
                        and actual_exit == child['exit_code'], 'finish')
                require(all(row[k] is None for k in
                            ('failure_stage','identity_diagnostic','cleanup_diagnostic'))
                        and diagnostics.handle_valid(row['handle_observation'])
                        and row['handle_observation']=={'alive':False,'exit_code':0,'error':None}
                        and type(row['handle_observation']['exit_code']) is int, 'diagnostic')
                require(io.prepared(freeze) is True, 'prepared')
                budget(0)
                row['candidate'] = 'PASS'
        except BaseException as error:
            if row['error'] is None:
                if row['failure_stage'] is None:row['failure_stage']=failure_site
                row['error'] = error.args[0] if type(error) is BoundaryRefused and error.args[0] in ERRORS else 'seal'
            row['candidate'] = 'FAIL'
        now = io.clock()
        row['seconds'] = now-started if finite(now) and finite(started) and now>=started else None
    # Serialize provisional payload, then reread bytes and recheck freeze/budget
    # BEFORE separate completion publication. Missing completion is never PASS.
        payload = encode(row)
    try:
        io.publish_payload(payload)
        require(io.read_payload() == payload, 'seal')
        require(io.prepared(freeze) is True, 'prepared')
        budget(0)
        completion = {'schema': 'hud_short_completion_v3', 'payload_sha256': sha(payload),
                      'verdict': row['candidate'] if row['error'] is None
                                  and row['cleanup_error'] is None else 'FAIL',
                      'freeze_sha256': freeze, 'review_sha256': review,
                      'seconds_at_seal': io.clock()-started}
        require(finite(completion['seconds_at_seal']) and 0<=completion['seconds_at_seal']<300, 'budget')
        io.publish_completion(completion)
        return row, completion
    except BaseException:
        return row, None  # No authoritative PASS; no rewrite, retry, or claim removal.
