"""Pure bounded missing-query contract and safe non-open projection; NO process IO."""
import copy
from boundary_policy import valid_frames

COLLECTORS_SHA = 'bc19bab73822ed4e24657dfb442621b1e0b01243c4a83fb26714175d2460902b'
# DESIGN cap for a finite synthetic child, not an observed requirement.
LAUNCHCTL_LIMIT = 16
LABELS = {'socket.bind':'socket_bind', 'socket.connect':'socket_connect',
          'sqlite3.connect':'sqlite_connect', 'subprocess.Popen':'subprocess_popen',
          'os.system':'os_system', 'os.fork':'os_fork', 'os.exec':'os_exec',
          'os.posix_spawn':'os_posix_spawn', 'os.kill':'os_kill', 'os.killpg':'os_killpg',
          'duplicate_install':'duplicate_install'}
BY_ERROR = {'network_boundary':{'socket_bind','socket_connect','unspecified'},
            'sqlite_boundary':{'sqlite_connect','unspecified'},
            'child_process_boundary':{'subprocess_popen','os_system','os_fork','os_exec',
                                      'os_posix_spawn','duplicate_install','unspecified'},
            'signal_boundary':{'os_kill','os_killpg','unspecified'}}

def safe_caller(value):
    return copy.deepcopy(value) if valid_frames(value) else {
        'frames':[], 'unknown_frames':0, 'truncated':True}

def project(error, event, caller):
    label=LABELS.get(event,'unspecified') if type(event) is str else 'unspecified'
    if label not in BY_ERROR[error]:label='unspecified'
    return {'error':error, 'event':label, 'caller':safe_caller(caller)}

def denial_valid(row):
    return (type(row) is dict and set(row)=={'error','event','caller'}
            and type(row['error']) is str and row['error'] in BY_ERROR
            and type(row['event']) is str and row['event'] in BY_ERROR[row['error']]
            and valid_frames(row['caller']))

def missing_allowed(event, args, caller, platform, owner_uid, used):
    return (type(event) is str and event=='subprocess.Popen'
            and type(platform) is str and platform=='darwin'
            and type(owner_uid) is int and 0<=owner_uid<2**31
            and type(used) is int and 0<=used<LAUNCHCTL_LIMIT
            and type(args) is tuple and len(args)==4
            and type(args[0]) is str and args[0]=='launchctl'
            and type(args[1]) is list and len(args[1])==3
            and all(type(v) is str for v in args[1])
            and args[1]==['launchctl','print',f'gui/{owner_uid}']
            and args[2] is None and args[3] is None
            and valid_frames(caller) and not caller['truncated']
            and len(caller['frames'])>=2
            and caller['frames'][:2]==[{'source_sha256':COLLECTORS_SHA,'line':933},
                                     {'source_sha256':COLLECTORS_SHA,'line':397}])
