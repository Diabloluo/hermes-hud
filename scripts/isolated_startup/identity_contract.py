"""Exact owned identity and safe diagnostics; no child identity is adopted as authority."""
from pathlib import Path
import os
import sys

from common import require, number, digest, HEX

KEYS = {'pid', 'birth', 'cwd', 'argv', 'exe'}
STAGES = {'initial', 'loop', 'pre_term', 'pre_kill'}
INSPECTION_ERRORS = {'no_such_process', 'zombie_process', 'access_denied', 'inspection_other'}
BINDING_KEYS = {'schema', 'launcher', 'prefix', 'argv0', 'exe', 'launcher_sha256', 'exe_sha256'}
FAILURE_STAGES = {'preload', 'policy', 'host_import', 'host_main', 'sampler', 'worker'}
FAILURE_CODES = {'file_boundary', 'network_boundary', 'sqlite_boundary', 'child_process_boundary',
                 'control', 'mach_scalar', 'operation', 'duplicate_observer', 'internal'}


def failure_valid(row):
    if not (type(row) is dict and set(row) == {'schema', 'error', 'stage', 'site',
                                             'site_semantics', 'raw_persisted'}
            and row['schema'] == 'hud_remote_observer_failure_v2'
            and type(row['error']) is str and row['error'] in FAILURE_CODES
            and type(row['stage']) is str and row['stage'] in FAILURE_STAGES
            and row['site_semantics'] == 'filename_provenance_only_not_source_hash'
            and row['raw_persisted'] is False):
        return False
    site = row['site']
    return (site is None or type(site) is dict and set(site) == {'filename_sha256', 'line'}
            and type(site['filename_sha256']) is str and HEX.fullmatch(site['filename_sha256']) is not None
            and type(site['line']) is int and 0 < site['line'] < 2**31)


def text(value):
    return (type(value) is str and 0 < len(value) <= 4096
            and all(ord(c) >= 32 and ord(c) != 127 for c in value))


def valid(identity):
    return (type(identity) is dict and set(identity) == KEYS
            and type(identity['pid']) is int and identity['pid'] > 0
            and type(identity['birth']) is float and number(identity['birth']) and identity['birth'] > 0
            and text(identity['cwd']) and Path(identity['cwd']).is_absolute()
            and text(identity['exe']) and Path(identity['exe']).is_absolute()
            and type(identity['argv']) is list and 0 < len(identity['argv']) <= 32
            and all(text(v) for v in identity['argv']))


def matches(saved, actual):
    return valid(saved) and valid(actual) and saved == actual


def inspect(proc):
    import psutil
    obj = psutil.Process(proc.pid)
    return {'pid': proc.pid, 'birth': obj.create_time(), 'cwd': obj.cwd(),
            'argv': obj.cmdline(), 'exe': str(Path(obj.exe()).resolve())}


def exception_code(error):
    import psutil
    for cls, code in ((psutil.ZombieProcess, 'zombie_process'),
                      (psutil.NoSuchProcess, 'no_such_process'),
                      (psutil.AccessDenied, 'access_denied')):
        if isinstance(error, cls):
            return code
    return 'inspection_other'


def diagnostic(stage, saved=None, actual=None, exit_code=None, inspection_error=None):
    require(stage in STAGES and (exit_code is None or type(exit_code) is int)
            and inspection_error in INSPECTION_ERRORS | {None}, 'identity_diagnostic')
    checks = {key: None for key in sorted(KEYS)}
    if valid(saved) and valid(actual):
        checks = {key: saved[key] == actual[key] for key in sorted(KEYS)}
    return {'stage': stage, 'checks': checks, 'exit_code': exit_code,
            'inspection_error': inspection_error}


def diagnostic_valid(row):
    return (type(row) is dict and set(row) == {'stage', 'checks', 'exit_code', 'inspection_error'}
            and type(row['stage']) is str and row['stage'] in STAGES
            and type(row['checks']) is dict and set(row['checks']) == KEYS
            and all(v is None or type(v) is bool for v in row['checks'].values())
            and (row['exit_code'] is None or type(row['exit_code']) is int and abs(row['exit_code']) < 10000)
            and (row['inspection_error'] is None or type(row['inspection_error']) is str
                 and row['inspection_error'] in INSPECTION_ERRORS))


def diagnostic_matched(row):
    return (diagnostic_valid(row) and row['exit_code'] is None and row['inspection_error'] is None
            and all(v is True for v in row['checks'].values()))


def binding_valid(binding, root):
    return (type(binding) is dict and set(binding) == BINDING_KEYS
            and binding['schema'] == 'hud_remote_interpreter_v3'
            and binding['launcher'] == str(root/'venv/bin/python')
            and binding['prefix'] == str(root/'venv')
            and all(text(binding[k]) and Path(binding[k]).is_absolute() for k in ('argv0', 'exe'))
            and all(type(binding[k]) is str and HEX.fullmatch(binding[k]) is not None
                    for k in ('launcher_sha256', 'exe_sha256')))


def bind_parent(root):
    # Only the trusted current controller process is inspected here, before Popen.
    # sys.executable retains the venv launcher. OS argv0 may name Python.app.
    actual = inspect(type('Self', (), {'pid': os.getpid()})())
    require(valid(actual) and actual['argv'][1:] == sys.orig_argv[1:]
            and sys.orig_argv[1:3] == ['-I', '-B'], 'interpreter_binding')
    result = {'schema': 'hud_remote_interpreter_v3', 'launcher': sys.executable,
              'prefix': str(Path(sys.prefix).resolve()), 'argv0': actual['argv'][0],
              'exe': actual['exe'], 'launcher_sha256': digest(Path(sys.executable).resolve()),
              'exe_sha256': digest(Path(actual['exe']).resolve())}
    require(binding_valid(result, root), 'interpreter_binding')
    return result


def revalidate_binding(binding, root):
    """Rehash only the prebound public launcher/image; never inspect a child."""
    require(binding_valid(binding, root), 'interpreter_binding')
    launcher, image = Path(binding['launcher']), Path(binding['exe'])
    require(Path(binding['prefix']).resolve() == root/'venv'
            and image.resolve() == image
            and digest(launcher.resolve()) == binding['launcher_sha256']
            and digest(image) == binding['exe_sha256'], 'interpreter_binding')
    return True


def direct_launch(launch_argv, home, binding, root):
    """One direct image exec, with parent-bound argv0 and venv launcher hint.

    Removes the wrapper handoff rather than accepting intermediate child images.
    This is a launch contract, not proof that this CI Python honors the hint.
    """
    require(binding_valid(binding, root) and type(launch_argv) is list
            and len(launch_argv) == 11 and all(text(v) for v in launch_argv)
            and launch_argv[0] == binding['launcher']
            and launch_argv[1:3] == ['-I', '-B']
            and launch_argv[3] == str(Path(__file__).resolve().parent/'observer_smoke.py')
            and launch_argv[4:8] == ['dashboard', '--host', '127.0.0.1', '--port']
            and launch_argv[8].isascii() and launch_argv[8].isdecimal()
            and str(int(launch_argv[8])) == launch_argv[8]
            and 1024 <= int(launch_argv[8]) <= 65535 and int(launch_argv[8]) != 9119
            and launch_argv[9:] == ['--no-open', '--skip-build']
            and home == root/'run/synthetic-home', 'interpreter_binding')
    return {'argv': [binding['argv0']] + launch_argv[1:],
            'executable': binding['exe'], 'venv_launcher': binding['launcher']}


def child_context(root, executable, prefix, orig_argv, isolated, no_bytecode):
    """Fail before host imports if direct-image exec loses its owned venv."""
    return (type(executable) is str and executable == str(root/'venv/bin/python')
            and prefix == str(root/'venv') and type(orig_argv) is list
            and len(orig_argv) == 11 and orig_argv[1:3] == ['-I', '-B']
            and type(isolated) is int and isolated == 1 and no_bytecode is True)


def expected(launch_argv, home, pid, birth, binding):
    require(type(launch_argv) is list and len(launch_argv) == 11
            and launch_argv[0] == binding['launcher'], 'interpreter_binding')
    result = {'pid': pid, 'birth': birth, 'cwd': str(home),
              'argv': [binding['argv0']] + launch_argv[1:], 'exe': binding['exe']}
    require(valid(result), 'host_identity')
    return result
