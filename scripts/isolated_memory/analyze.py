"""Independent pure aggregate analysis. No runner/native imports, DB/home/trace reopening."""
import hashlib
import json
from pathlib import Path
import sys
if __name__=='__main__':sys.path.insert(0,str(Path(__file__).resolve().parent))
from common import require,bounded,read,object_pairs
from pair_record import encode,publish
from pair_contract import (PHASES,LABELS,METRICS,LIMITS,ERRORS,finite,integer,hash_valid,
                          sample_valid,checkpoint_valid,quality,slope,monotonic_states,GRANT)
from lifecycle import cleanup_valid,child_valid,sources_valid,transport_valid
from identity_diagnostics import valid as diagnostic_valid,handle_valid
import resource_diagnostics as resources
import execution_diagnostics as execution

PAIR_KEYS={'schema','result','candidate','error','failure_diagnostic','grant','sha','run_id','execution_kind',
 'freeze_start','freeze_end','review','arms','seconds','limits','growth_acceptance_budget','memory_risk','public_release'}
ARM_KEYS={'arm','candidate','error','failure_diagnostic','seconds','resource','identity_diagnostic','cleanup','handle',
 'child','source_start','source_end','fixture','counts_end','phases','operations','samples','smoke'}
COUNTS={'sessions':5000,'messages':200000,'usage_rows':4900,'active_sessions':20,
 'ended_sessions':4980,'tool_messages':2000,'skill_records':1000}

def diagnostic_pair(error,value):
    return value is None if error is None else execution.valid(value)

def arm_valid(x,name):
    if not (type(x) is dict and set(x)==ARM_KEYS and x['arm']==name
       and x['candidate'] in ('PASS','FAIL') and (x['error'] is None or
       type(x['error']) is str and x['error'] in ERRORS)
       and diagnostic_pair(x['error'],x['failure_diagnostic'])
       and finite(x['seconds']) and x['seconds']>=0
       and (x['resource'] is None or resources.valid(x['resource']))
       and (x['identity_diagnostic'] is None or diagnostic_valid(x['identity_diagnostic']))
       and (x['cleanup'] is None or cleanup_valid(x['cleanup']))
       and handle_valid(x['handle']) and (x['child'] is None or child_valid(x['child']))
       and all(x[k] is None or sources_valid(x[k]) for k in ('source_start','source_end'))
       and (x['smoke'] is None or transport_valid(x['smoke']))
       and type(x['phases']) is list and len(x['phases'])<=len(PHASES)
       and type(x['operations']) is list and len(x['operations'])<=5
       and type(x['samples']) is list and len(x['samples'])<=1600
       and all(sample_valid(r) for r in x['samples'])):return False
    if not all(b['at']>a['at'] for a,b in zip(x['samples'],x['samples'][1:])):return False
    for row,(label,seconds,load) in zip(x['phases'],PHASES):
        if not (type(row) is dict and set(row)=={'label','seconds','start','end','http','ws','handshakes','state'}
          and row['label']==label and type(row['seconds']) is int and row['seconds']==seconds
          and finite(row['start']) and finite(row['end']) and 0<=row['start']<row['end']
          and all(integer(row[k]) for k in ('http','ws','handshakes'))
          and __import__('guard_stack').clean_state(row['state'])):return False
    for seq,op in enumerate(x['operations'],1):
        if not (type(op) is dict and set(op)=={'sequence','label','at','observed_seconds','window_seconds','checkpoint'}
          and type(op['sequence']) is int and op['sequence']==seq and op['label']==LABELS[seq-1]
          and all(finite(op[k]) for k in ('at','observed_seconds','window_seconds'))
          and op['at']>=0 and 0<=op['observed_seconds']<30 and 30<=op['window_seconds']<32
          and checkpoint_valid(op['checkpoint'],name,seq)):return False
    f=x['fixture']
    if f is not None:
        if not (type(f) is dict and set(f)=={'counts','schema_source_sha256','source_hashes',
            'query_only','native_ddl','timeline_total'} and f['counts']==COUNTS
            and all(type(n) is int for n in f['counts'].values()) and f['query_only'] is True
            and f['timeline_total'] is None and hash_valid(f['schema_source_sha256'])
            and f['native_ddl']=='fresh pinned distribution SCHEMA_SQL; required fields not patched'
            and type(f['source_hashes']) is dict and set(f['source_hashes'])=={'state.db','job-ledger/jobs.jsonl'}
            and all(hash_valid(h) for h in f['source_hashes'].values())):return False
    if x['counts_end'] is not None and not (type(x['counts_end']) is dict and x['counts_end']==COUNTS
        and all(type(v) is int for v in x['counts_end'].values())):return False
    return True

def pair_valid(x):
    if not (type(x) is dict and set(x)==PAIR_KEYS and x['schema']=='hud_finite_attribution_pair_v2'
       and x['result']=='PENDING_TERMINAL_SEAL' and x['candidate'] in ('PASS','FAIL')
       and (x['error'] is None or type(x['error']) is str and x['error'] in ERRORS)
       and diagnostic_pair(x['error'],x['failure_diagnostic'])
       and type(x['grant']) is str and GRANT.fullmatch(x['grant']) is not None
       and type(x['sha']) is str and __import__('re').fullmatch('[a-f0-9]{40}',x['sha']) is not None
       and type(x['run_id']) is str and x['run_id'].isascii() and x['run_id'].isdigit() and 1<=len(x['run_id'])<=20
       and x['execution_kind'] in ('MODEL','NATIVE') and hash_valid(x['freeze_start'])
       and (x['freeze_end'] is None or hash_valid(x['freeze_end'])) and hash_valid(x['review'])
       and finite(x['seconds']) and x['seconds']>=0 and x['limits']==LIMITS
       and x['growth_acceptance_budget'] is None and x['memory_risk']=='WARN_NOT_ACCEPTED'
       and x['public_release']=='BLOCK' and type(x['arms']) is list and len(x['arms'])<=2):return False
    return all(arm_valid(arm,name) for arm,name in zip(x['arms'],('sham','snapshot')))

def complete_arm(x):
    require(x['candidate']=='PASS' and x['error'] is None and 0<x['seconds']<3000
       and resources.passed(x['resource']) and x['identity_diagnostic'] is None
       and transport_valid(x['smoke']) and len(x['phases'])==len(PHASES)
       and len(x['operations'])==5 and x['fixture'] is not None and x['counts_end']==COUNTS
       and x['source_start']==x['source_end'] and sources_valid(x['source_start']),'finish')
    c=x['cleanup'];child=x['child']
    require(c is not None and c['identity_matched'] is True and c['alive'] is False
       and type(c['exit_code']) is int and c['exit_code']==0 and c['error'] is None
       and x['handle']=={'alive':False,'exit_code':0,'error':None}
       and child is not None and child['candidate']=='PASS' and child['commanded_exit'] is True
       and type(child['exit_code']) is int and child['exit_code']==0
       and child['source_end']==x['source_end'],'cleanup')
    phases=x['phases'];operations=x['operations'];means={};qualities=[];events=[];last=-1
    for row,(_,seconds,load) in zip(phases,PHASES):
        require(row['start']>=last and seconds<=row['end']-row['start']<=seconds+42,'phase')
        require((row['http']>=4 and row['ws']>0 and row['handshakes']==1) if load
                 else row['http']==row['ws']==row['handshakes']==0,'phase')
        q,m=quality(x['samples'],row);qualities.append(q);means[row['label']]=m
        events.append((row['end'],row['state']));last=row['end']
    for seq,op in enumerate(operations,1):
        index=next(i for i,r in enumerate(phases) if r['label']==LABELS[seq-1])
        require(op['at']>=phases[index]['end'] and op['at']+op['window_seconds']<=phases[index+1]['start'],'operation')
        events.append((op['at']+op['window_seconds'],op['checkpoint']['state']))
    require(monotonic_states([s for _,s in sorted(events,key=lambda e:e[0])]+[child['state']]),'boundary')
    trends={k:{'final_minus_baseline':means['final'][k]-means['baseline'][k],
       'cooldown_ols_per_hour':slope([(next(r['end'] for r in phases if r['label']==f'cooldown-{n}'),
        means[f'cooldown-{n}'][k]) for n in range(1,5)])} for k in METRICS}
    return {'arm':x['arm'],'failure_diagnostic':None,'seconds':x['seconds'],'coverage':qualities,'phase_tail_means':means,
      'within_arm_changes':trends,'operations':operations,'phases':phases,'samples':x['samples'],
      'resource':x['resource'],'cleanup':c,'handle':x['handle'],'child':child,'source_end':x['source_end'],
      'smoke':x['smoke'],'fixture':x['fixture']}

def analyze(payload,completion,freeze,review):
    result={'result':'DIAGNOSTIC_ONLY_NOT_VERIFIED','error':'evidence_invalid','failure_diagnostic':None,'arms':[],
        'memory_risk':'WARN_NOT_ACCEPTED','public_release':'BLOCK','growth_acceptance_budget':None,
        'absolute_between_arm_memory_comparison':'FORBIDDEN','ols_status':'INCOMPLETE_NO_SLOPE',
        'limits':LIMITS[:]}
    try:
        require(type(payload) is bytes and len(payload)<=2*1024*1024
          and type(completion) is dict and set(completion)=={'schema','payload_sha256','verdict',
            'freeze_sha256','review_sha256','seconds_at_seal'}
          and completion['schema']=='hud_memory_pair_completion_v2' and completion['verdict'] in ('PASS','FAIL')
          and hash_valid(freeze) and hash_valid(review) and completion['freeze_sha256']==freeze
          and completion['review_sha256']==review and completion['payload_sha256']==hashlib.sha256(payload).hexdigest()
          and finite(completion['seconds_at_seal']) and 0<=completion['seconds_at_seal']<6000,'seal')
        x=json.loads(payload,object_pairs_hook=object_pairs)
        require(pair_valid(x) and x['freeze_start']==freeze and x['review']==review
              and x['seconds']<=completion['seconds_at_seal'],'seal')
        if completion['verdict']=='FAIL':
            require(x['candidate']=='FAIL','seal')
            result.update(error='execution_failed',failure_diagnostic=x['failure_diagnostic'],arms=[{'arm':a['arm'],'error':a['error'],'failure_diagnostic':a['failure_diagnostic'],
             'samples':a['samples'],'resource':a['resource'],'cleanup':a['cleanup'],'handle':a['handle']}
             for a in x['arms']])
            return result
        require(x['candidate']=='PASS' and x['error'] is None and x['freeze_end']==freeze
            and 0<x['seconds']<6000 and len(x['arms'])==2,'finish')
        arms=[complete_arm(a) for a in x['arms']]
        require(arms[0]['fixture']==arms[1]['fixture'] and arms[0]['source_end']==arms[1]['source_end'],'source')
        result.update(result=('VERIFIED_REMOTE_SAME_TRACE_FINITE_PAIR_ONLY' if x['execution_kind']=='NATIVE'
            else 'VERIFIED_OFFLINE_PAIR_MODEL_ONLY'),error=None,arms=arms,
            ols_status='DESCRIPTIVE_FOUR_COOLDOWN_POINTS_ONLY')
        return result
    except Exception:return result

def main(root,freeze,review):
    root=Path(root)
    require(root.is_absolute() and root.resolve()==root and root.name=='hud-finite-attribution-owned','seal')
    result={'result':'DIAGNOSTIC_ONLY_NOT_VERIFIED','error':'evidence_missing','failure_diagnostic':None,'arms':[],
        'memory_risk':'WARN_NOT_ACCEPTED','public_release':'BLOCK','growth_acceptance_budget':None,
        'absolute_between_arm_memory_comparison':'FORBIDDEN','ols_status':'INCOMPLETE_NO_SLOPE','limits':LIMITS[:]}
    try:result=analyze(bounded(root/'result.json',2*1024*1024),read(root/'completion.json'),freeze,review)
    except Exception:pass
    root.mkdir(exist_ok=True)
    artifact=root/'aggregate-artifact';artifact.mkdir(exist_ok=True)
    publish(artifact/'analysis.json',encode(result))
    return 0 if result['result']=='VERIFIED_REMOTE_SAME_TRACE_FINITE_PAIR_ONLY' else 2
if __name__=='__main__':
    try:raise SystemExit(main(*sys.argv[1:]))
    except SystemExit:raise
    except BaseException:raise SystemExit(2) from None
