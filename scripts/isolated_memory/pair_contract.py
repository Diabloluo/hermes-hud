"""Pure fixed finite contracts; no IO, clock, native queries or authority creation."""
import math
import re
import statistics
from common import require
from lifecycle import SCOPE, SCHEMA, authority_valid
from guard_stack import clean_state, stack_valid

LABELS=('baseline','cooldown-1','cooldown-2','cooldown-3','cooldown-4')
METRICS=('rss_bytes','resident_size','phys_footprint','compressed','traced_current_bytes',
         'trace_metadata_bytes','threads','fds','snapshot_cache','db_cache','diagnostic_cache')
PHASES=(('warmup',60,True),('baseline',120,False))+tuple(
    x for n in range(1,5) for x in ((f'load-{n}',300,True),(f'cooldown-{n}',180,False)))+(('final',120,False),)
LIMITS=['RESTRICTED_SYNTHETIC_ENVIRONMENT_NOT_NATIVE_HOST_COMPATIBILITY',
 'RECORD_CONSISTENCY_NOT_OS_ATTESTATION','NOT_OS_CONTAINMENT','NOT_UI_ACCEPTANCE',
 'NO_ABSOLUTE_BETWEEN_ARM_MEMORY_COMPARISON','NO_GROWTH_ACCEPTANCE_BUDGET',
 'DESCRIPTIVE_FOUR_POINT_OLS_NOT_LEAK_OR_CAUSAL_PROOF','NONDETERMINISTIC_IO_DEADLINE',
 'FILENAME_PROVENANCE_ONLY_NOT_OWNERSHIP','HISTORICAL_MEMORY_STEP_NOT_ATTRIBUTED']
ERRORS={'prepared','authority','active','resource','claim','initialization','source','spawn',
 'identity','ready','http','ws','boundary','budget','finish','cleanup','seal','internal',
 'diagnostic','coverage','operation','phase','sample','checkpoint','setup_failed','interrupted'}
HEX=re.compile('[a-f0-9]{64}')
GRANT=re.compile('[a-f0-9]{32}')
def finite(x):return type(x) in (int,float) and math.isfinite(x)
def integer(x):return type(x) is int and 0<=x<2**63
def hash_valid(x):return type(x) is str and HEX.fullmatch(x) is not None
def sample_valid(x):
    return (type(x) is dict and set(x)=={'at','phase'}|set(METRICS) and finite(x['at'])
      and x['at']>=0 and type(x['phase']) is str
      and x['phase'] in {x[0] for x in PHASES}|{'startup','checkpoint'}
      and all(integer(x[k]) for k in METRICS))
def values_valid(x):
    if not (type(x) is dict and set(x)=={'trace_records','snapshot_bytes','delta_rows',
       'net_delta_bytes','top','interpretation'} and x['interpretation']=='filename_provenance_only_not_ownership'
       and all(integer(x[k]) for k in ('trace_records','snapshot_bytes','delta_rows'))
       and type(x['net_delta_bytes']) is int and abs(x['net_delta_bytes'])<2**63
       and type(x['top']) is list and len(x['top'])<=25):return False
    return (all(type(t) is dict and set(t)=={'file_sha256','line','bytes','blocks'}
      and hash_valid(t['file_sha256']) and all(integer(t[k]) for k in ('line','bytes','blocks'))
      for t in x['top']) and sum(t['bytes'] for t in x['top'])<=x['snapshot_bytes'])
def checkpoint_valid(x,arm,seq):
    return (type(x) is dict and set(x)=={'sequence','label','compare_to','snapshot_count','gc_count',
      'seconds','values','state'} and type(x['sequence']) is int and x['sequence']==seq
      and x['label']==LABELS[seq-1] and (x['compare_to'] is None if seq==1 else
        type(x['compare_to']) is int and x['compare_to']==1)
      and type(x['snapshot_count']) is int and x['snapshot_count']==int(arm=='snapshot')
      and type(x['gc_count']) is int and x['gc_count']==0
      and finite(x['seconds']) and 0<=x['seconds']<30 and clean_state(x['state'])
      and (x['values'] is None if arm=='sham' else values_valid(x['values'])))
def monotonic_states(states):
    if not states or not all(clean_state(s) for s in states):return False
    prior=(0,0,0,0)
    for s in states:
        current=(s['file']['missing']['cgroup'],s['file']['missing']['mountinfo'],
                 s['file']['config_missing'],s['launchctl_missing'])
        if any(b<a for a,b in zip(prior,current)):return False
        prior=current
    return True
def quality(rows,phase):
    require(type(rows) is list and all(sample_valid(x) for x in rows),'sample')
    require(all(b['at']>a['at'] for a,b in zip(rows,rows[1:])),'sample')
    subset=[x for x in rows if x['phase']==phase['label'] and phase['start']<=x['at']<=phase['end']]
    tail=[x for x in subset if x['at']>=phase['end']-min(60,phase['seconds'])]
    require(bool(subset and tail),'coverage')
    times=[phase['start']]+[x['at'] for x in subset]+[phase['end']]
    require(all(b>=a for a,b in zip(times,times[1:])),'sample')
    ratio=len(subset)/(phase['seconds']/2);tail_ratio=len(tail)/(min(60,phase['seconds'])/2)
    gap=max(b-a for a,b in zip(times,times[1:]))
    require(ratio>=.9 and tail_ratio>=.9 and gap<=10,'coverage')
    return {'phase':phase['label'],'coverage':ratio,'tail_coverage':tail_ratio,
            'maximum_gap_seconds':gap,'tail_count':len(tail)},{
             k:statistics.mean(x[k] for x in tail) for k in METRICS}
def slope(points):
    require(len(points)==4 and all(finite(x) and finite(y) for x,y in points),'coverage')
    xs,ys=zip(*points);mx,my=statistics.mean(xs),statistics.mean(ys)
    den=sum((x-mx)**2 for x in xs);require(den>0,'coverage')
    return sum((x-mx)*(y-my) for x,y in points)/den*3600
def error_code(error):
    from boundary_policy import BoundaryRefused
    if type(error) is BoundaryRefused and len(error.args)==1 and type(error.args[0]) is str and error.args[0] in ERRORS:return error.args[0]
    return 'internal'
