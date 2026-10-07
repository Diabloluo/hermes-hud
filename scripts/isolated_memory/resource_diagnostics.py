"""Bounded initial-resource scalars. Inert; queries only injected dependencies."""
import copy
SCHEMA = 'hud_initial_resource_diagnostic_v1'
MEMORY_MIN = 3 * 1024**3
DISK_MIN = 5 * 1024**3
MAX_BYTES = 2**63 - 1
KEYS = {'schema','memory_min_bytes','disk_min_bytes','dependency_status',
        'memory_status','disk_status','available_memory_bytes','free_disk_bytes','error'}
ERRORS = {'dependency_failed','permission_denied','os_error','query_error','invalid_scalar'}
STATES = {'SKIPPED','PASS','BELOW','ERROR'}
DIAGNOSTIC_ERRORS = {'unavailable','invalid','read_failed','outcome_mismatch'}

def scalar(value):
    return type(value) is int and 0 <= value <= MAX_BYTES

def exception_code(error):
    # Never exports class name, repr, message, pathname or traceback.
    if isinstance(error, PermissionError): return 'permission_denied'
    if isinstance(error, OSError): return 'os_error'
    return 'query_error'

def seed():
    return {'schema':SCHEMA,'memory_min_bytes':MEMORY_MIN,'disk_min_bytes':DISK_MIN,
            'dependency_status':'ERROR','memory_status':'SKIPPED','disk_status':'SKIPPED',
            'available_memory_bytes':None,'free_disk_bytes':None,'error':'dependency_failed'}

def collect(load_dependency, owned_root):
    """One load, one memory query, at most one disk query. No retry.
    Root is passed only to the existing query, never exported.
    BaseException is not swallowed; caller lifecycle stays fail-closed.
    """
    row = seed()
    try: dependency = load_dependency()
    except Exception: return row
    row['dependency_status'] = 'PASS'
    for kind,key,minimum,query in (
        ('memory','available_memory_bytes',MEMORY_MIN,lambda:dependency.virtual_memory().available),
        ('disk','free_disk_bytes',DISK_MIN,lambda:dependency.disk_usage(owned_root).free),
    ):
        try: value = query()
        except Exception as error:
            row[kind+'_status']='ERROR';row['error']=exception_code(error)
            return row
        if not scalar(value):
            row[kind+'_status']='ERROR';row['error']='invalid_scalar'
            return row
        row[key]=value
        row[kind+'_status']='PASS' if value>=minimum else 'BELOW'
        row['error']=None
        if row[kind+'_status']=='BELOW': return row
    return row

def measured(state,value,minimum):
    if state in ('SKIPPED','ERROR'): return value is None
    return scalar(value) and state==('PASS' if value>=minimum else 'BELOW')

def valid(row):
    if not (type(row) is dict and set(row)==KEYS and row['schema']==SCHEMA
        and type(row['memory_min_bytes']) is int and row['memory_min_bytes']==MEMORY_MIN
        and type(row['disk_min_bytes']) is int and row['disk_min_bytes']==DISK_MIN
        and type(row['dependency_status']) is str and row['dependency_status'] in {'PASS','ERROR'}
        and all(type(row[k]) is str and row[k] in STATES for k in ('memory_status','disk_status'))
        and (row['error'] is None or type(row['error']) is str and row['error'] in ERRORS)):
        return False
    m,d,error=row['memory_status'],row['disk_status'],row['error']
    if not (measured(m,row['available_memory_bytes'],MEMORY_MIN)
            and measured(d,row['free_disk_bytes'],DISK_MIN)): return False
    if row['dependency_status']=='ERROR':
        return m==d=='SKIPPED' and error=='dependency_failed'
    if m=='ERROR': return d=='SKIPPED' and error in ERRORS-{'dependency_failed'}
    if m=='BELOW': return d=='SKIPPED' and error is None
    if m!='PASS' or d=='SKIPPED': return False
    return (error in ERRORS-{'dependency_failed'} if d=='ERROR' else error is None)

def passed(row):
    return valid(row) and row['dependency_status']==row['memory_status']==row['disk_status']=='PASS'

def snapshot(row):
    if not valid(row): raise ValueError('resource_diagnostic_invalid') from None
    return copy.deepcopy(row)

def evidence_valid(kind,row,error):
    return ((row is None or valid(row))
        and (error is None or type(error) is str and error in DIAGNOSTIC_ERRORS)
        and not (kind=='NATIVE' and row is None and error is None))

def success_valid(kind,row,error):
    return error is None and (kind=='MODEL' and row is None or passed(row))
