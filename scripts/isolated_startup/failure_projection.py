"""Fixed safe projection; never executes a host or converts diagnostic evidence to PASS."""
import copy
from boundary_policy import BoundaryRefused, state_valid

STAGES = {'preload', 'policy', 'host_import', 'host_main', 'sampler', 'worker'}
ERRORS = {'file_boundary', 'network_boundary', 'sqlite_boundary', 'child_process_boundary',
          'control', 'mach_scalar', 'operation', 'duplicate_observer', 'internal'}


def make_failure(error, stage, policy):
    if type(stage) is not str or stage not in STAGES:
        raise BoundaryRefused('failure_schema')
    state = policy.state()
    if not state_valid(state):
        raise BoundaryRefused('failure_schema')
    # No exception repr, args, traceback filename or caller-supplied free text.
    code = 'file_boundary' if state['denied_count'] else 'internal'
    return {'schema': 'hud_startup_safe_failure_v1', 'error': code, 'stage': stage,
            'boundary': state, 'raw_persisted': False,
            'result': 'DIAGNOSTIC_ONLY_NOT_VERIFIED'}


def failure_valid(row):
    return (type(row) is dict and set(row) == {'schema', 'error', 'stage', 'boundary',
                                             'raw_persisted', 'result'}
            and row['schema'] == 'hud_startup_safe_failure_v1'
            and type(row['stage']) is str and row['stage'] in STAGES
            and type(row['error']) is str and row['error'] in {'internal', 'file_boundary'}
            and row['raw_persisted'] is False and row['result'] == 'DIAGNOSTIC_ONLY_NOT_VERIFIED'
            and state_valid(row['boundary'])
            and row['error'] == ('file_boundary' if row['boundary']['denied_count'] else 'internal'))


def analyze_failure(row):
    # Offline schema projection only. It cannot attest a real source or transport.
    return {'result': 'DIAGNOSTIC_ONLY_NOT_VERIFIED',
            'failure': copy.deepcopy(row) if failure_valid(row) else None,
            'memory_risk': 'WARN_NOT_ACCEPTED', 'public_release': 'BLOCK'}
