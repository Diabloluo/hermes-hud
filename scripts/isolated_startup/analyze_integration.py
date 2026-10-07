"""Independent bytes/schema analyzer; no runner import or file/DB/host access."""
import hashlib
import json
import math
import re
from pathlib import Path
import sys

if __name__=='__main__':sys.path.insert(0,str(Path(__file__).resolve().parent))

from guard_stack import stack_valid, clean_state
import identity_diagnostics as diagnostics

HEX = re.compile(r'^[0-9a-f]{64}$')
GRANT = re.compile(r'^[0-9a-f]{32}$')
LABELS = ('ready', 'http', 'ws', 'finish')
ERRORS = {'prepared', 'authority', 'active', 'resource', 'claim', 'initialization',
          'source', 'spawn', 'identity', 'ready', 'http', 'ws', 'boundary', 'budget',
          'finish', 'cleanup', 'seal', 'internal', 'diagnostic'}
LIMITS = ['SELF_REPORTED_TRANSPORT_NOT_OS_ATTESTATION', 'RESTRICTED_SYNTHETIC_ENVIRONMENT',
          'NOT_OS_CONTAINMENT', 'NOT_UI_ACCEPTANCE', 'NOT_MEMORY_ACCEPTANCE',
          'RECORD_CONSISTENCY_NOT_OS_ATTESTATION', 'NONDETERMINISTIC_IO_DEADLINE']
KEYS = {'schema', 'result', 'candidate', 'error', 'cleanup_error', 'authority_id',
        'source_start', 'source_end', 'checkpoints', 'http_calls', 'ws_calls',
        'child', 'cleanup', 'seconds', 'limits', 'memory_risk', 'public_release','execution_kind','transport',
        'failure_stage','identity_diagnostic','cleanup_diagnostic','handle_observation'}


def finite(x):
    return type(x) in (int, float) and math.isfinite(x)


def sources(x):
    return (type(x) is dict and set(x)=={'candidate', 'public_source', 'fixture'}
            and all(type(v) is str and HEX.fullmatch(v) is not None for v in x.values()))


def cleanup(x):
    return (type(x) is dict and set(x)=={'identity_matched', 'alive', 'exit_code', 'error'}
            and type(x['identity_matched']) is bool
            and (x['alive'] is None or type(x['alive']) is bool)
            and (x['exit_code'] is None or type(x['exit_code']) is int and abs(x['exit_code'])<10000)
            and x['error'] in (None, 'identity', 'cleanup', 'unexpected_exit')
            and (x['alive'] is None or x['alive']==(x['exit_code'] is None)))


def child(x):
    return (type(x) is dict and set(x)=={'schema', 'candidate', 'source_end', 'state',
                                       'commanded_exit', 'exit_code'}
            and x['schema']=='hud_short_child_terminal_v2' and x['candidate'] in ('PASS','FAIL')
            and (x['source_end'] is None or sources(x['source_end'])) and stack_valid(x['state'])
            and type(x['commanded_exit']) is bool
            and (x['exit_code'] is None or type(x['exit_code']) is int and abs(x['exit_code'])<10000))


def valid(x):
    if not (type(x) is dict and set(x)==KEYS and x['schema']=='hud_short_startup_backend_v4'
            and (x['failure_stage'] is None or type(x['failure_stage']) is str
                 and x['failure_stage'] in diagnostics.STAGES)
            and all(x[k] is None or diagnostics.valid(x[k])
                    for k in ('identity_diagnostic','cleanup_diagnostic'))
            and diagnostics.handle_valid(x['handle_observation'])
            and x['execution_kind'] in ('MODEL','NATIVE')
            and (x['transport'] is None or transport_valid(x['transport']))
            and x['result']=='PENDING_TERMINAL_SEAL' and x['candidate'] in ('PASS','FAIL')
            and (x['error'] is None or type(x['error']) is str and x['error'] in ERRORS)
            and x['cleanup_error'] in (None,'cleanup')
            and (x['authority_id'] is None or type(x['authority_id']) is str and GRANT.fullmatch(x['authority_id']))
            and all(x[k] is None or sources(x[k]) for k in ('source_start','source_end'))
            and type(x['http_calls']) is int and x['http_calls'] in (0,1)
            and type(x['ws_calls']) is int and x['ws_calls'] in (0,1)
            and (x['child'] is None or child(x['child'])) and (x['cleanup'] is None or cleanup(x['cleanup']))
            and (x['seconds'] is None or finite(x['seconds']) and x['seconds']>=0)
            and x['limits']==LIMITS and x['memory_risk']=='WARN_NOT_ACCEPTED' and x['public_release']=='BLOCK'
            and type(x['checkpoints']) is list and len(x['checkpoints'])<=4):
        return False
    for expected, ack in zip(LABELS, x['checkpoints']):
        if not (type(ack) is dict and set(ack)=={'label','state'}
                and ack['label']==expected and clean_state(ack['state'])):
            return False
    # The two one-shot missing-model counters belong to the same policy object;
    # a clean but reconstructed/stale object cannot silently reset either one.
    prior = {'cgroup':0, 'mountinfo':0}
    config_prior = 0
    states = [ack['state'] for ack in x['checkpoints']]
    if x['child'] is not None:
        states.append(x['child']['state'])
    for state in states:
        current=state['file']['missing']
        config_current = state['file']['config_missing']
        if any(current[key]<prior[key] for key in prior) or config_current < config_prior:
            return False
        prior=current
        config_prior=config_current
    return True


def pass_conditions(x):
    if not valid(x) or x['candidate']!='PASS' or x['error'] is not None or x['cleanup_error'] is not None:
        return False
    if (any(x[k] is not None for k in ('failure_stage','identity_diagnostic','cleanup_diagnostic'))
            or x['handle_observation']!={'alive':False,'exit_code':0,'error':None}
            or type(x['handle_observation']['exit_code']) is not int):
        return False
    c, end = x['child'], x['cleanup']
    return ((x['execution_kind']=='MODEL' and x['transport'] is None or
             x['execution_kind']=='NATIVE' and transport_valid(x['transport']))
            and x['authority_id'] is not None and sources(x['source_start'])
            and x['source_start']==x['source_end'] and len(x['checkpoints'])==4
            and x['http_calls']==x['ws_calls']==1 and finite(x['seconds']) and 0<=x['seconds']<300
            and c is not None and c['candidate']=='PASS' and c['commanded_exit'] is True
            and c['exit_code']==0 and c['source_end']==x['source_end'] and clean_state(c['state'])
            and end is not None and end['identity_matched'] is True and end['alive'] is False
            and type(end['exit_code']) is int and end['exit_code']==0
            and end['exit_code']==c['exit_code'] and end['error'] is None)


def transport_valid(x):
    return (type(x) is dict and set(x)=={'port','http_status','http_bytes','http_schema',
                                       'ws_frames','ws_bytes','ws_schema','handshakes'}
            and type(x['port']) is int and 1024<=x['port']<=65535 and x['port']!=9119
            and all(type(x[k]) is int and x[k]==v for k,v in
                    (('http_status',200),('http_schema',1),('ws_schema',1),('ws_frames',1),('handshakes',1)))
            and all(type(x[k]) is int and 0<x[k]<=1048576 for k in ('http_bytes','ws_bytes')))


def strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate')
        result[key] = value
    return result


def analyze(payload, completion, freeze, review):
    result = {'result':'DIAGNOSTIC_ONLY_NOT_VERIFIED', 'error':'evidence_invalid',
              'evidence':None, 'memory_risk':'WARN_NOT_ACCEPTED', 'public_release':'BLOCK',
              'native_execution':'NOT_VERIFIED'}
    try:
        if not (type(payload) is bytes and len(payload)<=65536 and type(completion) is dict
                and set(completion)=={'schema','payload_sha256','verdict','freeze_sha256','review_sha256','seconds_at_seal'}
                and completion['schema']=='hud_short_completion_v4'
                and completion['verdict'] in ('PASS','FAIL')
                and type(freeze) is str and HEX.fullmatch(freeze) is not None
                and type(review) is str and HEX.fullmatch(review) is not None
                and completion['freeze_sha256']==freeze and completion['review_sha256']==review
                and completion['payload_sha256']==hashlib.sha256(payload).hexdigest()
                and finite(completion['seconds_at_seal']) and 0<=completion['seconds_at_seal']<300):
            return result
        x=json.loads(payload, object_pairs_hook=strict_object)
        if not valid(x) or (x['seconds'] is not None and x['seconds']>completion['seconds_at_seal']):
            return result
        if completion['verdict']=='PASS':
            if not pass_conditions(x):
                return result
            result.update(result=('VERIFIED_OFFLINE_LIFECYCLE_MODEL_ONLY' if x['execution_kind']=='MODEL'
                                  else 'VERIFIED_THIS_REMOTE_SINGLE_SYNTHETIC_STARTUP_ONLY'),
                          error=None,evidence=x,
                          native_execution='NOT_VERIFIED' if x['execution_kind']=='MODEL' else 'FINITE_RECORDS_VERIFIED_ONLY')
        elif x['candidate']=='FAIL':
            result.update(error='execution_failed', evidence=x)
        return result
    except Exception:
        return result  # Never echo exception/raw input. BaseException is not hidden.


def main(root,freeze,review):
    # Exact final aggregate input only: never opens synthetic-home, DB, logs or
    # identity argv. Missing/broken seal emits bounded diagnostic-only artifact.
    from common import bounded,read,atomic,require
    root=Path(root)
    require(root.is_absolute() and root.resolve()==root and root.name=='hud-short-startup-owned','seal')
    artifact=root/'aggregate-artifact'
    result={'result':'DIAGNOSTIC_ONLY_NOT_VERIFIED','error':'evidence_missing','evidence':None,
            'memory_risk':'WARN_NOT_ACCEPTED','public_release':'BLOCK','native_execution':'NOT_VERIFIED'}
    try:result=analyze(bounded(root/'result.json',65536),read(root/'completion.json'),freeze,review)
    except Exception:pass
    artifact.mkdir(exist_ok=True)
    atomic(artifact/'analysis.json',result)
    return 0 if result['result']=='VERIFIED_THIS_REMOTE_SINGLE_SYNTHETIC_STARTUP_ONLY' else 2


if __name__=='__main__':
    try:raise SystemExit(main(*sys.argv[1:]))
    except SystemExit:raise
    except BaseException:raise SystemExit(2) from None
