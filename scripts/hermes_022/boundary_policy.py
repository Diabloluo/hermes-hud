"""Private gate-less offline preparation; this module never opens files or starts a host."""
import hashlib
import copy
import os
from pathlib import PurePosixPath
import re
import threading

SOURCE_SHA = 'dacf56fbaf53871057044131922ba0040ce144d10c0ac19c843e091e2f4547b5'
CONFIG_SOURCE_SHA = '172b78ecb923048859ca177d96f5b010b44ec74bb1d13553577ff49bde1a071d'
# Synthetic-contract design cap, NOT a measured host requirement or retry grant.
CONFIG_PROBE_LIMIT = 64
MISSING_SITES = {'/proc/1/cgroup': ('cgroup', 1161),
                 '/proc/self/mountinfo': ('mountinfo', 1172)}
HEX = re.compile(r'^[0-9a-f]{64}$')
ACCESS = {'read', 'write', 'unknown'}
CLASSES = {'owned', 'public', 'linux_probe', 'outside', 'unknown'}


class BoundaryRefused(ValueError):
    """Not OSError: unknown denials must not become normal missing-file fallback."""


def valid_frames(row):
    if not (type(row) is dict and set(row) == {'frames', 'unknown_frames', 'truncated'}
            and type(row['frames']) is list and len(row['frames']) <= 4
            and type(row['unknown_frames']) is int and 0 <= row['unknown_frames'] <= 128
            and type(row['truncated']) is bool):
        return False
    for frame in row['frames']:
        if not (type(frame) is dict and set(frame) == {'source_sha256', 'line'}
                and type(frame['source_sha256']) is str and HEX.fullmatch(frame['source_sha256'])
                and type(frame['line']) is int and 0 < frame['line'] < 2**31):
            return False
    return not row['truncated'] or row['frames'] == []


class BoundFrames:
    def __init__(self, bindings):
        if not (type(bindings) is dict and len(bindings) <= 8 and all(
                type(k) is str and PurePosixPath(k).is_absolute() and type(v) is str
                and HEX.fullmatch(v) for k, v in bindings.items())):
            raise BoundaryRefused('source_binding')
        self._bindings = dict(bindings)

    def collect(self, frame):
        result = {'frames': [], 'unknown_frames': 0, 'truncated': False}
        count = 0
        while frame is not None and count < 128:
            digest = self._bindings.get(frame.f_code.co_filename)
            line = frame.f_lineno
            if digest is not None and type(line) is int and 0 < line < 2**31:
                if len(result['frames']) < 4:
                    result['frames'].append({'source_sha256': digest, 'line': line})
            else:
                result['unknown_frames'] += 1
            frame, count = frame.f_back, count+1
        if frame is not None:
            result['truncated'], result['frames'] = True, []
        return result

    def immediate(self, frame):
        if frame is None:
            return None
        digest = self._bindings.get(frame.f_code.co_filename)
        return {'source_sha256': digest, 'line': frame.f_lineno} if digest is not None else None


def bind_public_source(filename, data):
    # Caller supplies bytes obtained from the exact approved public source before
    # installing the audit hook. No open/import of the host occurs here.
    if not (type(filename) is str and PurePosixPath(filename).is_absolute()
            and type(data) is bytes and hashlib.sha256(data).hexdigest() == SOURCE_SHA):
        raise BoundaryRefused('source_binding')
    return BoundFrames({filename: SOURCE_SHA})


def access_class(mode, flags):
    modes = {'r', 'rb', 'rt', 'r+', 'r+b', 'rb+', 'r+t', 'rt+',
             'w', 'wb', 'wt', 'w+', 'w+b', 'wb+', 'w+t', 'wt+',
             'a', 'ab', 'at', 'a+', 'a+b', 'ab+', 'a+t', 'at+',
             'x', 'xb', 'xt', 'x+', 'x+b', 'xb+', 'x+t', 'xt+'}
    if (mode is not None and (type(mode) is not str or mode not in modes)) \
            or type(flags) is not int or not 0 <= flags < 2**31:
        return 'unknown'
    safe = getattr(os, 'O_CLOEXEC', 0) | getattr(os, 'O_NOFOLLOW', 0)
    writes = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND | os.O_EXCL
    if flags & ~(safe | writes):
        return 'unknown'
    if (mode is not None and any(c in mode for c in 'wax+')) or flags & (
            os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
        return 'write'
    # Keep unfamiliar modes/flags fail-closed, rather than assume read-only.
    return 'read' if mode in (None, 'r', 'rb', 'rt') and flags >= 0 and flags & ~safe == 0 else 'unknown'


def canonical_text(value):
    if type(value) is not str or not value.startswith('/') or value.startswith('//') or len(value) > 4096:
        return False
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        return False
    p = PurePosixPath(value)
    return str(p) == value and '..' not in p.parts


def within(path, root):
    return PurePosixPath(path).is_relative_to(PurePosixPath(root))


def state_valid(row):
    return (type(row) is dict and set(row) == {'schema', 'denied_count', 'missing', 'config_missing', 'last_denial', 'scope'}
            and row['schema'] == 'hud_startup_boundary_state_v2'
            and row['scope'] == 'RESTRICTED_SYNTHETIC_ENVIRONMENT_NOT_NATIVE_HOST_COMPATIBILITY'
            and type(row['denied_count']) is int and 0 <= row['denied_count'] < 2**31
            and type(row['missing']) is dict and set(row['missing']) == {'cgroup', 'mountinfo'}
            and all(type(v) is int and v in (0, 1) for v in row['missing'].values())
            and type(row['config_missing']) is int and 0 <= row['config_missing'] <= CONFIG_PROBE_LIMIT
            and (row['last_denial'] is None and row['denied_count'] == 0 or
                 row['denied_count'] > 0 and denial_valid(row['last_denial'])))


def denial_valid(row):
    return (type(row) is dict and set(row) == {'error', 'access_class', 'path_class', 'caller'}
            and row['error'] == 'file_boundary' and type(row['access_class']) is str
            and row['access_class'] in ACCESS and type(row['path_class']) is str
            and row['path_class'] in CLASSES and valid_frames(row['caller']))


class FilePolicy:
    def __init__(self, home, out, roots, platform):
        if not (canonical_text(home) and canonical_text(out) and type(roots) is tuple
                and 0 < len(roots) <= 8 and all(canonical_text(x) and x != '/' for x in roots)
                and home != '/' and out != '/' and type(platform) is str
                and platform in ('darwin', 'linux', 'other')):
            raise BoundaryRefused('policy_binding')
        self._home, self._out, self._roots, self._platform = home, out, roots, platform
        self._missing, self._denied, self._last = {'cgroup': 0, 'mountinfo': 0}, 0, None
        self._config_missing = 0
        self._lock = threading.Lock()

    def check(self, requested, canonical, mode, flags, caller, immediate):
        if not valid_frames(caller):
            # Do not put a malformed caller record in the safe output.
            caller = {'frames': [], 'unknown_frames': 0, 'truncated': True}
            canonical = None
        access = access_class(mode, flags)
        kind = 'unknown'
        if canonical_text(canonical):
            kind = ('owned' if within(canonical, self._home) or within(canonical, self._out)
                    else 'public' if any(within(canonical, root) for root in self._roots)
                    else 'linux_probe' if canonical in MISSING_SITES else 'outside')
        # Evaluate the exact missing-resource model before public/owned allowance.
        # No filesystem access, no path alias, no broad /proc prefix, no retry.
        entry = MISSING_SITES.get(requested) if type(requested) is str else None
        if entry is not None:
            key, line = entry
            if (canonical == requested and self._platform == 'darwin' and access == 'read'
                    and not caller['truncated'] and type(immediate) is dict
                    and set(immediate) == {'source_sha256', 'line'}
                    and type(immediate['line']) is int
                    and caller['frames'] and caller['frames'][0] == immediate):
                if immediate['source_sha256'] == SOURCE_SHA and immediate['line'] == line:
                    with self._lock:
                        if self._missing[key] == 0:
                            self._missing[key] = 1
                            raise FileNotFoundError('isolated_resource_unavailable') from None
                elif (key == 'cgroup' and immediate == {'source_sha256': CONFIG_SOURCE_SHA, 'line': 868}
                      and len(caller['frames']) >= 2
                      and caller['frames'][1] == {'source_sha256': CONFIG_SOURCE_SHA, 'line': 886}):
                    # This uncached public helper is called through _secure_file.
                    # Exact source, two-frame call chain and per-child finite cap;
                    # NO filesystem open, arbitrary path, alias or general OSError.
                    with self._lock:
                        if type(self._config_missing) is int and 0 <= self._config_missing < CONFIG_PROBE_LIMIT:
                            self._config_missing += 1
                            raise FileNotFoundError('isolated_resource_unavailable') from None
            kind = 'linux_probe'
        if entry is None and (kind == 'owned' and access != 'unknown'
                              or kind == 'public' and access == 'read'):
            return
        record = {'error': 'file_boundary', 'access_class': access, 'path_class': kind, 'caller': caller}
        with self._lock:
            self._denied = min(self._denied+1, 2**31-1)
            # Deep independent projection: subsequent caller mutations cannot inject raw.
            self._last = {'error': record['error'], 'access_class': access, 'path_class': kind,
                          'caller': {'frames': [dict(x) for x in caller['frames']],
                                     'unknown_frames': caller['unknown_frames'], 'truncated': caller['truncated']}}
        raise BoundaryRefused('file_boundary') from None

    def state(self):
        with self._lock:
            return {'schema': 'hud_startup_boundary_state_v2', 'denied_count': self._denied,
                    'missing': dict(self._missing), 'config_missing': self._config_missing,
                    'last_denial': copy.deepcopy(self._last),
                    'scope': 'RESTRICTED_SYNTHETIC_ENVIRONMENT_NOT_NATIVE_HOST_COMPATIBILITY'}

    def ensure_clean(self):
        with self._lock:
            if self._denied:
                raise BoundaryRefused('file_boundary') from None
