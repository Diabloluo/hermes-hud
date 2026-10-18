"""Small retained-channel protocol. Never a native or release authorization."""
import hashlib
import json
import math
import re

MAX = 16384
ERRORS = frozenset(('bootstrap', 'source', 'guard', 'entry', 'server', 'control',
                    'deadline', 'exit', 'shutdown', 'terminal', 'close'))

class Refused(ValueError):
    def __init__(self): super().__init__('child_contract')

def require(value):
    if value is not True: raise Refused() from None

def encode(row):
    raw = (json.dumps(row, sort_keys=True, separators=(',', ':'), allow_nan=False)+'\n').encode()
    require(len(raw) <= MAX)
    return raw

def decode(raw):
    require(type(raw) is bytes and 0 < len(raw) <= MAX)
    def pairs(items):
        row = {}
        for key, value in items:
            require(key not in row); row[key] = value
        return row
    def constant(_): raise Refused()
    try: return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    except Exception: raise Refused() from None

def hex_value(value, length):
    return type(value) is str and re.fullmatch('[a-f0-9]{'+str(length)+'}', value) is not None

def identity(grant, source):
    require(hex_value(grant, 32) and hex_value(source, 64))

def ready(grant, source):
    identity(grant, source)
    return dict(schema='hermes_0222_child_ready_v1', grant=grant, source=source,
                guard_clean=True, server_started=True, scope='BOUND_SERVER_STARTUP_ONLY')

def stop(grant, source):
    identity(grant, source)
    return dict(schema='hermes_0222_child_stop_v1', grant=grant, source=source, action='stop', sequence=1)

def ack(grant, source):
    identity(grant, source)
    return dict(schema='hermes_0222_child_ack_v1', grant=grant, source=source, action='stop', sequence=1)

def payload(grant, source, *, code, error, startup, stopped, shutdown, unchanged, clean):
    identity(grant, source)
    require(code is None or type(code) is int and -255 <= code <= 255)
    require(error is None or type(error) is str and error in ERRORS)
    require(all(type(v) is bool for v in (startup, stopped, shutdown, unchanged, clean)))
    passed = error is None and type(code) is int and code == 0 and all((startup, stopped, shutdown, unchanged, clean))
    return dict(schema='hermes_0222_child_payload_v1', grant=grant, source=source,
                result='ENTRY_RETURNED_ZERO_NOT_ACCEPTANCE' if passed else 'FAIL',
                entry_exit_code=code, error=error, startup=startup, stop_received=stopped,
                shutdown_returned=shutdown, source_unchanged=unchanged, guard_clean=clean,
                channel_close='REQUIRES_PARENT_OBSERVED_EXIT_ZERO', memory='WARN_NOT_ACCEPTED', public_release='BLOCK')

def seal(row):
    return dict(schema='hermes_0222_child_terminal_v1', payload=row,
                payload_sha256=hashlib.sha256(encode(row)).hexdigest())

def read_terminal(row, grant, source):
    """Strict local record integrity, NOT proof of original process identity."""
    try:
        require(type(row) is dict and set(row)=={'schema','payload','payload_sha256'})
        require(row['schema']=='hermes_0222_child_terminal_v1' and type(row['payload']) is dict)
        p=row['payload']
        expected=payload(grant,source,code=p['entry_exit_code'],error=p['error'],startup=p['startup'],
                         stopped=p['stop_received'],shutdown=p['shutdown_returned'],
                         unchanged=p['source_unchanged'],clean=p['guard_clean'])
        require(encode(p)==encode(expected) and row==seal(expected))
        return expected
    except Exception: return None

def verify_terminal(row, grant, source, observed_exit):
    """The actual original Popen exit is required in addition to the child seal."""
    record=read_terminal(row,grant,source)
    return (record is not None and type(observed_exit) is int and observed_exit==0
            and record['result']=='ENTRY_RETURNED_ZERO_NOT_ACCEPTANCE')

def finite(value):
    return type(value) in (int,float) and math.isfinite(value)
