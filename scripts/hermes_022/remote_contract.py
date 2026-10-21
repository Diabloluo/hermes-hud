"""Remote-only whole-package authority. No grant creation, dispatch or SDK import."""
import hashlib
import json
import math
import re

REPO = 'Diabloluo/hermes-hud'
BRANCH = 'test/v2-isolated-memory-20261003'
SCOPE = 'one_remote_hermes_0222_exact_git_trust_v3_install1800_host300_no_retry_no_risk_acceptance'
STAGES = ('gate','claim','sources','bootstrap','pm_install','npm_ci','web_build',
          'handoff','host','aggregate')

class Refused(ValueError):
    def __init__(self): super().__init__('REMOTE_PACKAGE_REFUSED')

def need(ok):
    if ok is not True: raise Refused() from None

def sha(raw): return hashlib.sha256(raw).hexdigest()
def encode(row): return (json.dumps(row,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
def hexstr(s,n): return type(s) is str and re.fullmatch('[a-f0-9]{'+str(n)+'}',s) is not None
def finite(n): return type(n) in (int,float) and math.isfinite(n) and 0<=n<2**53

def platform_gate(env,system,machine,version):
    # These are runtime observations, NOT hardware/VM attestation.
    need(type(env) is dict and env.get('GITHUB_ACTIONS')=='true'
         and env.get('RUNNER_ENVIRONMENT')=='github-hosted'
         and env.get('RUNNER_OS')=='macOS' and env.get('RUNNER_ARCH')=='X64'
         and system=='darwin' and machine=='x86_64' and version.startswith('15.'))

def authorize(auth,acceptance,freeze,report,env,now):
    need(type(auth) is dict and set(auth)=={'schema','scope','grant','sha','freeze_sha256',
         'report_sha256','issued','expires','max_runs','owner_confirmed','repository','branch'})
    need(auth['schema']=='hermes_0222_remote_authorization_v3' and auth['scope']==SCOPE
         and hexstr(auth['grant'],32) and hexstr(auth['sha'],40)
         and auth['repository']==REPO and auth['branch']==BRANCH
         and type(auth['max_runs']) is int and auth['max_runs']==1 and auth['owner_confirmed'] is True)
    need(hexstr(freeze,64) and hexstr(report,64) and auth['freeze_sha256']==freeze
         and auth['report_sha256']==report)
    need(all(finite(v) for v in (now,auth['issued'],auth['expires']))
         and auth['issued']<=now<=auth['expires'] and 0<auth['expires']-auth['issued']<=3600)
    need(type(acceptance) is dict and acceptance=={'schema':'hermes_0222_remote_acceptance_v3',
         'scope':SCOPE,'safety':'PASS','sha':auth['sha'],'freeze_sha256':freeze,'report_sha256':report})
    need(type(env) is dict and env.get('GITHUB_REPOSITORY')==REPO
         and env.get('GITHUB_REF')=='refs/heads/'+BRANCH and env.get('GITHUB_SHA')==auth['sha']
         and env.get('GITHUB_EVENT_NAME')=='workflow_dispatch' and env.get('GITHUB_RUN_ATTEMPT')=='1'
         and type(env.get('GITHUB_RUN_ID')) is str and re.fullmatch('[1-9][0-9]{0,19}',env['GITHUB_RUN_ID']) is not None)
    return {'schema':'hermes_0222_remote_claim_v3','grant':auth['grant'],'sha':auth['sha'],
            'freeze_sha256':freeze,'report_sha256':report,'run_id':env['GITHUB_RUN_ID'],
            'state':'CONSUMED_ONCE_NO_RETRY_EVEN_IF_OUTCOME_UNKNOWN','scope':SCOPE}

def child_bindings(config_raw,report_raw,auth,start):
    """Derive only the host substage authorized by this whole-package grant.

    Review binds the generator, not unknowable pre-install dependency bytes.
    Config is generated after real inventory verification; no additional run.
    """
    from child_runtime import SCOPE as CHILD_SCOPE
    need(auth['scope']==SCOPE and auth['owner_confirmed'] is True and type(auth['max_runs']) is int
         and auth['max_runs']==1 and auth['report_sha256']==sha(report_raw)
         and finite(start) and auth['issued']<=start<auth['expires'])
    h=sha(config_raw);r=sha(report_raw)
    a={'schema':'hermes_0222_child_authorization_v1','scope':CHILD_SCOPE,'grant':auth['grant'],
       'config_sha256':h,'report_sha256':r,'issued':auth['issued'],'expires':auth['expires'],
       'max_runs':1,'owner_confirmed':True}
    accepted={'schema':'hermes_0222_child_acceptance_v1','scope':CHILD_SCOPE,'safety':'PASS',
              'config_sha256':h,'report_sha256':r}
    claim={'schema':'hermes_0222_parent_claim_v1','grant':auth['grant'],'config_sha256':h,
           'state':'CONSUMED_ONCE_NO_RETRY','started_wall':start,'deadline_wall':start+300}
    return a,accepted,claim

def aggregate(grant,stage,install,host,source_diagnostic=None):
    """Allowlisted projection only; never publish arbitrary lower-layer objects."""
    need(hexstr(grant,32) and stage in STAGES)
    commands=install if type(install) is list else []
    install_ok=(len(commands)==3 and [c.get('stage') for c in commands if type(c) is dict]
                ==['pm_install','npm_ci','web_build'] and all(type(c.get('exit_code')) is int
                and c['exit_code']==0 and c.get('error') is None and c.get('cleanup_error') is None for c in commands))
    h=host if type(host) is dict else {};c=h.get('cleanup');c=c if type(c) is dict else {}
    p=h.get('child_record');p=p if type(p) is dict else {}
    from child_protocol import payload
    child_ok=False
    try:
        expected=payload(grant,p['source'],code=p['entry_exit_code'],error=p['error'],startup=p['startup'],
             stopped=p['stop_received'],shutdown=p['shutdown_returned'],unchanged=p['source_unchanged'],clean=p['guard_clean'])
        child_ok=encode(p)==encode(expected) and p['result']=='ENTRY_RETURNED_ZERO_NOT_ACCEPTANCE'
    except Exception:pass
    host_ok=(child_ok and h.get('result')=='SEALED_SHORT_SESSION_RECORD_ONLY' and h.get('parent_channel_closed') is True
             and h.get('child_seal_verified') is True and h.get('source_unchanged') is True
             and type(c.get('exit_code')) is int and c['exit_code']==0 and c.get('result')=='EXIT_OBSERVED_NOT_ACCEPTANCE'
             and all(c.get(k) is None for k in ('error','cleanup_error','stop_error'))
             and all(type(h.get(k)) is dict and h[k].get('result')=='EXPECTED_RESPONSE_ONLY' for k in ('http','ws')))
    ok=stage=='aggregate' and install_ok and host_ok
    from source_selection import valid_diagnostic
    need(valid_diagnostic(source_diagnostic) if stage=='sources' else source_diagnostic is None)
    return {'schema':'hermes_0222_remote_safe_aggregate_v3','grant':grant,
            'result':'PASS' if ok else 'FAIL','scope':'VERIFIED_SINGLE_REMOTE_PROJECTED_SOURCE_SYNTHETIC_SESSION_RECORD_ONLY' if ok else 'DIAGNOSTIC_ONLY_NOT_VERIFIED',
            'source_projection':'PINNED_INSTALL_HOST_WEB_INPUTS_NOT_FULL_REPOSITORY','source_diagnostic':source_diagnostic,
            'stage':stage,'install_commands_zero':install_ok,'http_verified':ok,'ws_verified':ok,
            'host_exit_zero':type(c.get('exit_code')) is int and c['exit_code']==0,
            'child_seal_verified':h.get('child_seal_verified') is True,
            'source_unchanged':h.get('source_unchanged') is True,
            'memory':'WARN_NOT_ACCEPTED','public_release':'BLOCK','retry':False,
            'installer_tree_coverage':'REGISTERED_DESCENDANTS_ONLY','vm_teardown_verified':False,
            'raw_payload_exported':False,'hardware_attested':False,'browser_verified':False}

def validate_aggregate(row):
    template=aggregate('0'*32,'gate',[],None)
    need(type(row) is dict and set(row)==set(template) and hexstr(row['grant'],32)
         and row['stage'] in STAGES and row['result'] in ('PASS','FAIL'))
    variable={'grant','stage','result','scope','install_commands_zero','http_verified','ws_verified',
              'host_exit_zero','child_seal_verified','source_unchanged','source_diagnostic'}
    need(all(type(row[k]) is type(v) and row[k]==v for k,v in template.items() if k not in variable))
    flags=('install_commands_zero','http_verified','ws_verified','host_exit_zero','child_seal_verified','source_unchanged')
    need(all(type(row[k]) is bool for k in flags))
    need(row['scope']==('VERIFIED_SINGLE_REMOTE_PROJECTED_SOURCE_SYNTHETIC_SESSION_RECORD_ONLY' if row['result']=='PASS'
                       else 'DIAGNOSTIC_ONLY_NOT_VERIFIED'))
    from source_selection import valid_diagnostic
    need(valid_diagnostic(row['source_diagnostic']) if row['stage']=='sources' else row['source_diagnostic'] is None)
    if row['result']=='PASS':need(row['stage']=='aggregate' and all(row[k] for k in flags) and row['source_diagnostic'] is None)
    else:need(row['http_verified'] is False and row['ws_verified'] is False)
    return True
