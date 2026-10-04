"""One fresh remote pair. No execution outside the reviewed workflow identity."""
import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import venv

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (HERE, Refused, atomic, read, require, digest, frozen, protocol,
                    schedule, live_identity, identity_matches, cleanup, deadline,
                    workflow_authority, endpoint, LABELS)
from identity_contract import (bind_parent, expected as expected_identity, diagnostic,
                               exception_code, valid as identity_valid)


def freeze_check(expected):
    require(digest(HERE/'FREEZE.json') == expected, 'review_freeze')
    record = read(HERE/'FREEZE.json')
    require(record == {'schema': 'hud_remote_tool_freeze_v1', 'files': frozen()}, 'tool_drift')
    return record['files']


def remote_gate(args):
    workflow_authority(os.environ, args.sha, args.grant)
    require(sys.platform == 'darwin' and sys.version_info[:2] == (3, 13), 'platform')
    require(Path(os.environ['GITHUB_WORKSPACE']).resolve() == HERE.parents[1], 'workspace')
    return freeze_check(args.freeze)


def setup(args):
    # Pinned workflow calls this on the setup-python interpreter, before installing
    # dependencies. Only this phase may reach PyPI, not the measured hosts.
    remote_gate(args)
    begun = time.monotonic()
    root = Path(os.environ['RUNNER_TEMP']).resolve()/'hud-finite-owned'
    root.mkdir()  # no reuse / no overwrite
    with (root/'AUTHORIZATION_CLAIM.json').open('x') as stream:
        json.dump({'grant': args.grant, 'sha': args.sha, 'run_id': os.environ['GITHUB_RUN_ID'],
                   'state': 'CONSUMED_ONCE_NO_RETRY', 'max_runs': 1}, stream)
    atomic(root/'setup.json', {'result': 'RUNNING', 'start': begun})
    try:
        # No user's environment/credentials are copied into this fresh venv.
        venv.EnvBuilder(with_pip=True).create(root/'venv')
        python = root/'venv/bin/python'
        remaining = 1800-(time.monotonic()-begun)
        require(remaining > 0, 'setup_budget')
        env = {'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'HOME': str(root),
               'TMPDIR': str(root), 'LANG': 'en_US.UTF-8', 'PIP_DISABLE_PIP_VERSION_CHECK': '1',
               'PYTHONDONTWRITEBYTECODE': '1'}
        subprocess.run([str(python), '-I', '-B', '-m', 'pip', 'install',
                        'hermes-agent==0.19.0', 'psutil==7.2.2', 'websockets==15.0.1'],
                       env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=remaining, check=True)
        require(time.monotonic()-begun < 1800, 'setup_budget')
        atomic(root/'setup.json', {'result': 'PASS', 'start': begun,
                                  'seconds': time.monotonic()-begun, 'grant': args.grant,
                                  'sha': args.sha, 'freeze': args.freeze})
    except BaseException:
        atomic(root/'setup.json', {'result': 'FAIL', 'error': 'setup_failed',
                                  'seconds': time.monotonic()-begun})
        raise Refused('setup_failed') from None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise Refused('redirect')


class Host:
    def __init__(self, arm, home, out, repo, port, binding=None):
        self.arm, self.home, self.out, self.port = arm, home, out, port
        self.proc, self.identity, self.token = None, None, None
        self.binding, self.identity_diagnostic = binding, None
        self.sequence = 0
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        self.argv = [sys.executable, '-I', '-B', str(HERE/'observer.py'), 'dashboard',
                     '--host', '127.0.0.1', '--port', str(port), '--no-open', '--skip-build']
        self.env = {'HOME': str(home/'fake-user'), 'HERMES_HOME': str(home),
                    'HERMES_BUNDLED_SKILLS_DIR': str(home/'bundled-skills'),
                    'HERMES_DISABLE_LAZY_INSTALLS': '1', 'PATH': '/usr/bin:/bin:/usr/sbin:/sbin',
                    'HERMES_GATEWAY_LOCK_DIR': str(home/'.host-locks'),
                    'PYTHONDONTWRITEBYTECODE': '1', 'LANG': 'en_US.UTF-8', 'TZ': 'UTC',
                    'TMPDIR': str(home/'tmp'), 'HUD_REMOTE_CHILD': '1', 'HUD_ARM': arm,
                    'HUD_OUT': str(out), 'HUD_REPO': str(repo), 'HUD_PORT': str(port)}

    def spawn(self):
        require(self.binding is not None and self.argv[0] == self.binding['launcher'], 'interpreter_binding')
        self.proc = subprocess.Popen(self.argv, cwd=self.home, env=self.env,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # Read-only startup settling, not another Popen. Birth is captured ONCE,
        # never refreshed to a different process. Only trusted parent argv0/exe
        # supply authority; the child's observed command is never adopted.
        until = time.monotonic()+2
        while True:
            code = self.proc.poll()
            if code is not None:
                self.identity_diagnostic = diagnostic('initial', exit_code=code)
                raise Refused('host_early_exit')
            try:
                actual = live_identity(self.proc)
            except BaseException as error:
                self.identity_diagnostic = diagnostic('initial', inspection_error=exception_code(error))
                raise Refused('identity_inspection') from None
            if self.identity is None and identity_valid(actual):
                self.identity = expected_identity(self.argv, self.home, self.proc.pid,
                                                  actual['birth'], self.binding)
            self.identity_diagnostic = diagnostic('initial', self.identity, actual)
            if identity_matches(self.identity, actual):
                break
            if time.monotonic() >= until:
                raise Refused('host_identity')
            time.sleep(.05)
        atomic(self.out/'identity.json', self.identity)

    def check_identity(self):
        code = self.proc.poll() if self.proc is not None else None
        if self.proc is None or code is not None:
            self.identity_diagnostic = diagnostic('loop', exit_code=code)
            raise Refused('host_early_exit')
        try:
            actual = live_identity(self.proc)
        except BaseException as error:
            self.identity_diagnostic = diagnostic('loop', inspection_error=exception_code(error))
            raise Refused('identity_inspection') from None
        self.identity_diagnostic = diagnostic('loop', self.identity, actual)
        require(identity_matches(self.identity, actual), 'host_identity')

    def check(self, p, pair_begin, arm_begin, operation=None):
        import psutil
        deadline(time.monotonic(), pair_begin, arm_begin, p)
        self.check_identity()
        require(not (self.out/'observer-failure.json').exists(), 'observer_failed')
        require(psutil.virtual_memory().available >= p['available_running_bytes']
                and psutil.disk_usage(self.out).free >= p['disk_running_bytes']
                and psutil.Process(self.proc.pid).memory_info().rss < p['process_ceiling_bytes'], 'resource')
        if (self.out/'latest.json').exists():
            latest = read(self.out/'latest.json')
            require(time.monotonic()-latest['at'] < (32 if operation is not None else 10)
                    and latest['phys_footprint'] < p['process_ceiling_bytes'], 'sampler_guard')
        if operation is not None:
            require(time.monotonic()-operation < p['checkpoint_seconds'], 'operation_budget')

    def request(self, route):
        headers = {} if not route else {'X-Hermes-Session-Token': self.token}
        req = urllib.request.Request(endpoint(self.port, route), headers=headers)
        with self.opener.open(req, timeout=10) as response:
            raw = response.read(8*1024*1024+1)
            require(response.status == 200 and len(raw) <= 8*1024*1024, 'http')
        if not route:
            match = re.search(rb'window\.__HERMES_SESSION_TOKEN__="([^"\r\n]+)"', raw)
            require(match is not None, 'session_token')
            self.token = match.group(1).decode('ascii')
        else:
            require(type(json.loads(raw)) is dict, 'http_schema')
        # Body/token discarded and never attached to a receipt, exception or artifact.

    async def phase_set(self, label, guard):
        self.sequence += 1
        atomic(self.out/'control.json', {'phase': label, 'sequence': self.sequence})
        until = time.monotonic()+10
        while time.monotonic() < until:
            guard()
            if (self.out/'phase-ack.json').exists():
                ack = read(self.out/'phase-ack.json')
                if ack['phase'] == label and ack['sequence'] == self.sequence:
                    return
            await asyncio.sleep(.05)
        raise Refused('phase_ack')


async def phase(host, label, seconds, load, guard):
    from websockets.asyncio.client import connect
    await host.phase_set(label, guard)
    begin = time.monotonic()
    counts = {'http': 0, 'ws': 0, 'handshakes': 0}
    async def socket_lane():
        guard()
        url = endpoint(host.port, 'events?locale=en').replace('http:', 'ws:')+'&token='+host.token
        async with connect(url, origin=f'http://127.0.0.1:{host.port}', proxy=None,
                           open_timeout=10, close_timeout=2, max_size=8*1024*1024) as ws:
            counts['handshakes'] += 1
            while time.monotonic()-begin < seconds:
                value = json.loads(await asyncio.wait_for(ws.recv(), 10))
                require(type(value) is dict and type(value.get('schema_version')) is int
                        and value['schema_version'] == 1, 'ws_schema')
                counts['ws'] += 1
    lane = asyncio.create_task(socket_lane()) if load else None
    tick = 0
    try:
        while time.monotonic()-begin < seconds:
            at = time.monotonic()
            guard()
            if lane and lane.done():
                await lane
                raise Refused('ws_early_exit')
            if load:
                for route in ('snapshot?locale='+('zh', 'en', 'fr', 'ar')[tick%4],
                              'timeline?limit=100', 'usage?days=30', 'skills?locale=en'):
                    guard()
                    await asyncio.to_thread(host.request, route)
                    counts['http'] += 1
                tick += 1
            await asyncio.sleep(max(.01, 2-(time.monotonic()-at)))
    finally:
        if lane:
            if not lane.done():
                lane.cancel()
            try:
                await lane
            except asyncio.CancelledError:
                pass
    require(not load or (counts['http'] >= 4 and counts['ws'] > 0 and counts['handshakes'] == 1), 'load')
    return {'label': label, 'seconds': seconds, 'start': begin, 'end': time.monotonic(), **counts}


async def operation(host, label, seq, guard, p):
    await host.phase_set('checkpoint', guard)
    begin = time.monotonic()
    atomic(host.out/'operation.json', {'label': label, 'sequence': seq, 'at': begin})
    done = None
    # Reserve the SAME full 30s in both arms, even if capture/sham finishes early.
    while time.monotonic()-begin < p['checkpoint_seconds']:
        guard(begin if done is None else None)
        path = host.out/'operation-done.json'
        if done is None and path.exists():
            row = read(path)
            if row['sequence'] == seq:
                require(type(row['sequence']) is int and 0 <= row['seconds'] < 30, 'operation_ack')
                done = time.monotonic()
        await asyncio.sleep(.1)
    require(done is not None and done-begin < 30, 'operation_budget')
    return {'sequence': seq, 'label': label, 'at': begin,
            'observed_seconds': done-begin, 'window_seconds': time.monotonic()-begin}


async def run_arm(root, arm, repo, epoch, p, begun, hashes, binding):
    import psutil
    from fixture import build, source_hashes, counts
    at = time.monotonic()
    directory = root/arm
    directory.mkdir()
    out, home = directory/'evidence', directory/'synthetic-home'
    out.mkdir()
    r = {'schema': 'hud_remote_arm_v2', 'arm': arm, 'result': 'RUNNING', 'error': None,
         'phases': [], 'operations': [], 'cleanup': None, 'fixture': None,
         'sources_end': None, 'counts_end': None, 'tool_end': None,
         'start': at, 'seconds': None, 'identity': None, 'identity_diagnostic': None}
    host = None
    try:
        require(psutil.virtual_memory().available >= p['available_start_bytes']
                and psutil.disk_usage(root).free >= p['disk_start_bytes'], 'start_resource')
        r['fixture'] = build(home, repo, epoch, p['fixture_counts'])
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        endpoint(port, '')
        atomic(out/'control.json', {'phase': 'startup', 'sequence': 0})
        require(bind_parent(root) == binding, 'interpreter_binding')
        host = Host(arm, home, out, repo, port, binding)
        host.spawn()
        r['identity'] = host.identity
        until = time.monotonic()+p['startup_seconds']
        def guard(operation=None):
            host.check(p, begun, at, operation)
        while time.monotonic() < until:
            guard()
            try:
                await asyncio.to_thread(host.request, '')
                if (out/'ready.json').exists():
                    require(read(out/'ready.json') == {'arm': arm, 'pid': host.proc.pid,
                                                       'trace_depth': 1}, 'observer_ready')
                    break
            except (OSError, Refused):
                pass
            await asyncio.sleep(.2)
        else:
            raise Refused('startup_budget')
        seq = 0
        for label, seconds, load in schedule(p):
            r['phases'].append(await phase(host, label, seconds, load, guard))
            atomic(out/'result.json', r)
            atomic(root/'progress.json', {'arm': arm, 'phase': label, 'at': time.monotonic()})
            if label in LABELS:
                seq += 1
                r['operations'].append(await operation(host, label, seq, guard, p))
        r['result'] = 'EXECUTION_COMPLETE_PENDING_ANALYSIS'
    except BaseException as error:
        # Enumerate only our own controlled Refused codes; unknown exceptions get no text.
        allowed = {'start_resource', 'fixture_counts', 'port', 'host_identity', 'observer_failed',
                   'resource', 'sampler_guard', 'operation_budget', 'pair_budget', 'arm_budget',
                   'phase_ack', 'http', 'http_schema', 'ws_schema', 'ws_early_exit', 'load',
                   'startup_budget', 'observer_ready', 'operation_ack', 'clock',
                   'host_early_exit', 'identity_inspection', 'interpreter_binding'}
        r['result'] = 'FAIL'
        r['error'] = str(error) if type(error) is Refused and str(error) in allowed else 'internal'
    finally:
        if host:
            r['identity'] = host.identity
            r['identity_diagnostic'] = host.identity_diagnostic
        if host and host.proc:
            r['cleanup'] = cleanup(host.proc, host.identity or {})
            if not (r['cleanup']['identity_matched'] is True and r['cleanup']['alive'] is False
                    and r['cleanup']['error'] is None):
                r['result'] = 'FAIL'
                r['error'] = r['error'] or 'cleanup_failed'
        for key, reader in (('sources_end', lambda: source_hashes(home)),
                            ('counts_end', lambda: counts(home)), ('tool_end', frozen)):
            try:
                r[key] = reader()
            except BaseException:
                r['result'], r['error'] = 'FAIL', r['error'] or 'final_readback'
        if r['fixture'] and (r['sources_end'] != r['fixture']['source_hashes']
                            or r['counts_end'] != p['fixture_counts']):
            r['result'], r['error'] = 'FAIL', r['error'] or 'source_changed'
        if r['tool_end'] != hashes:
            r['result'], r['error'] = 'FAIL', r['error'] or 'tool_drift'
        r['seconds'] = time.monotonic()-at
        atomic(out/'result.json', r)
    return r


async def pair(args):
    hashes = remote_gate(args)
    root = Path(os.environ['RUNNER_TEMP']).resolve()/'hud-finite-owned'
    claim, prepared = read(root/'AUTHORIZATION_CLAIM.json'), read(root/'setup.json')
    require(claim == {'grant': args.grant, 'sha': args.sha, 'run_id': os.environ['GITHUB_RUN_ID'],
                      'state': 'CONSUMED_ONCE_NO_RETRY', 'max_runs': 1}
            and prepared['result'] == 'PASS' and prepared['seconds'] < 1800
            and prepared['grant'] == args.grant and prepared['sha'] == args.sha
            and prepared['freeze'] == args.freeze, 'claim')
    with (root/'EXPERIMENT_CLAIM.json').open('x') as stream:
        stream.write('CONSUMED_ONCE_NO_RETRY\n')
    begun = time.monotonic()
    repo = HERE.parents[1]
    r = {'schema': 'hud_remote_pair_v2', 'sha': args.sha, 'candidate': protocol()['candidate'],
         'grant': args.grant, 'run_id': os.environ['GITHUB_RUN_ID'], 'result': 'RUNNING',
         'arms': [], 'tool_start': hashes, 'tool_end': None, 'seconds': None,
         'environment': {'python': sys.version.split()[0], 'platform': sys.platform,
             'distributions': {d.metadata['Name']: d.version for d in importlib.metadata.distributions()}},
         'memory_risk': 'WARN_NOT_ACCEPTED', 'public_release': 'BLOCK',
         'interpreter_binding': None, 'interpreter_binding_end': None}
    p = protocol()
    require(importlib.metadata.version('hermes-agent') == p['host_version'], 'host_version')
    # File name+content fingerprint of public Python modules only, no metadata/config/logs.
    def public_source_fingerprint():
        h = hashlib.sha256()
        count = 0
        for name in ('hermes_cli', 'fastapi', 'starlette', 'uvicorn', 'psutil', 'websockets'):
            spec = __import__('importlib').util.find_spec(name)
            require(spec is not None and spec.origin is not None, 'public_source')
            installed = Path(spec.origin).resolve().parent
            files = sorted(installed.rglob('*.py'))
            require(files and len(files) <= 10000, 'public_source')
            for path in files:
                h.update((name+'/'+str(path.relative_to(installed))).encode())
                h.update(bytes.fromhex(digest(path)))
            count += len(files)
        return {'count': count, 'sha256': h.hexdigest()}
    r['public_source_start'] = public_source_fingerprint()
    atomic(root/'result.json', r)
    r['interpreter_binding'] = bind_parent(root)
    atomic(root/'result.json', r)
    # The artifact is created only after both arms are sealed. No synthetic home uploads.
    epoch = int(time.time())-7200
    for arm in p['arms']:
        value = await run_arm(root, arm, repo, epoch, p, begun, hashes, r['interpreter_binding'])
        r['arms'].append({'arm': arm, 'result': value['result']})
        atomic(root/'result.json', r)
        if value['result'] == 'FAIL':
            break
    r['seconds'] = time.monotonic()-begun
    r['tool_end'] = frozen()
    r['public_source_end'] = public_source_fingerprint()
    r['interpreter_binding_end'] = bind_parent(root)
    r['result'] = ('EXECUTION_COMPLETE_PENDING_ANALYSIS' if len(r['arms']) == 2
                   and all(a['result'] != 'FAIL' for a in r['arms']) and r['seconds'] < 6000
                   and r['tool_end'] == hashes and r['public_source_start'] == r['public_source_end']
                   and r['interpreter_binding'] == r['interpreter_binding_end'] else 'FAIL')
    atomic(root/'result.json', r)
    return root


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('setup', 'pair'))
    for name in ('sha', 'grant', 'freeze'):
        parser.add_argument('--'+name, required=True)
    args = parser.parse_args()
    def interrupt(*_):
        raise Refused('interrupted')
    signal.signal(signal.SIGTERM, interrupt)
    signal.signal(signal.SIGINT, interrupt)
    try:
        if args.mode == 'setup':
            setup(args)
        else:
            root = asyncio.run(pair(args))
            require(read(root/'result.json')['result'] != 'FAIL', 'pair_failed')
    except BaseException:
        print('{"result":"FAIL","memory_risk":"WARN_NOT_ACCEPTED","public_release":"BLOCK"}')
        return 2
    print('{"result":"COMPLETE_PENDING_INDEPENDENT_ANALYSIS","memory_risk":"WARN_NOT_ACCEPTED","public_release":"BLOCK"}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
