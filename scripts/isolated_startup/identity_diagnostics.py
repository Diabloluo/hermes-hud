"""Bounded scalar diagnostics. No file, PID, network, DB or signal operations."""
import copy
import identity_contract as identity

SITES = {'initial_poll', 'initial_inspect', 'initial_schema', 'initial_birth',
         'initial_expected', 'initial_match', 'loop_poll', 'loop_inspect', 'loop_match',
         'pre_term_inspect', 'pre_term_match', 'pre_kill_inspect', 'pre_kill_match'}
STAGES = {'prepared', 'authority', 'active', 'resource', 'claim', 'initialization',
          'source', 'spawn', 'expected', 'identity', 'ready', 'http', 'ws', 'transport',
          'finish', 'check_ready', 'ack_ready', 'check_http', 'ack_http', 'check_ws',
          'ack_ws', 'check_finish', 'ack_finish', 'cleanup', 'child_terminal',
          'source_end', 'acceptance', 'diagnostic'}
FIELDS = {'site', 'checks', 'exit_code', 'inspection_error', 'birth_window'}
HANDLE_FIELDS = {'alive', 'exit_code', 'error'}


def code_valid(code):
    return code is None or type(code) is int and abs(code) < 10000


def valid(value):
    return (type(value) is dict and set(value) == FIELDS
            and type(value['site']) is str and value['site'] in SITES
            and type(value['checks']) is dict and set(value['checks']) == identity.KEYS
            and all(v is None or type(v) is bool for v in value['checks'].values())
            and code_valid(value['exit_code'])
            and (value['inspection_error'] is None or type(value['inspection_error']) is str
                 and value['inspection_error'] in identity.INSPECTION_ERRORS)
            and (value['birth_window'] is None or type(value['birth_window']) is bool))


def project(site, saved=None, actual=None, exit_code=None, inspection_error=None,
            birth_window=None):
    checks = {key: None for key in sorted(identity.KEYS)}
    if identity.valid(saved) and identity.valid(actual):
        checks = {key: saved[key] == actual[key] for key in sorted(identity.KEYS)}
    value = {'site': site, 'checks': checks,
             'exit_code': exit_code if code_valid(exit_code) else None,
             'inspection_error': inspection_error, 'birth_window': birth_window}
    if not valid(value):
        raise ValueError('diagnostic') from None
    return value


def snapshot(value):
    if value is not None and not valid(value):
        raise ValueError('diagnostic') from None
    return copy.deepcopy(value)


def handle_valid(value):
    return (type(value) is dict and set(value) == HANDLE_FIELDS
            and (value['alive'] is None or type(value['alive']) is bool)
            and code_valid(value['exit_code'])
            and (value['error'] is None or type(value['error']) is str
                 and value['error'] in ('poll_other', 'poll_invalid'))
            and (value['alive'] is not None or value['exit_code'] is None)
            and (value['alive'] is None or value['alive'] == (value['exit_code'] is None))
            and (value['error'] is None or value['alive'] is None and value['exit_code'] is None))


def observe_handle(proc):
    # Only the original Popen handle. No inspect/reattach/signal/wait, and never
    # grants identity authority or overwrites transport/cleanup exit status.
    out = {'alive': None, 'exit_code': None, 'error': None}
    if proc is None:
        return out
    try:
        code = proc.poll()  # Exactly one additional diagnostic observation.
    except BaseException:
        return dict(out, error='poll_other')
    if not code_valid(code):
        return dict(out, error='poll_invalid')
    return dict(out, alive=code is None, exit_code=code)
