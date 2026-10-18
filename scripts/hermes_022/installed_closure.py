"""Post-install inventory of new owned files; never installs or imports a package.

This is a byte/path closure, not an authentication of what an installer produced.
Native dependency provenance must still be bound to the reviewed install inputs.
Only the selected generation is traversed, not caches, user homes or old installs.
"""
import base64
import csv
import hashlib
import io
import os
from pathlib import PurePosixPath
import re
import stat

from pm_handoff import BoundFiles, Refused, file_stamp, need, relative
from runtime_aliases import from_inventory

MAX_FILES = 8192
MAX_BYTES = 1024**3
MAX_NODES = 16384
TEXT = frozenset(('.py', '.pth', '.json', '.toml', '.yaml', '.yml', '.txt',
                  '.cfg', '.ini', '.js', '.mjs', '.cjs', '.css', '.html', '.csv', '.lock'))
TEXT_NAMES = frozenset(('METADATA', 'RECORD', 'WHEEL', 'INSTALLER', 'REQUESTED', 'entry_points.txt'))


def close_all(handles):
    failed = False
    for handle in reversed(handles):
        try: os.close(handle)
        except BaseException: failed = True
    need(not failed, 'file')


def selected_paths(root, environment):
    need(type(root) is str and re.fullmatch('/private/tmp/hermes-022-run-[a-f0-9]{32}', root) is not None, 'path')
    key = hashlib.sha256((root + '/sdk').encode()).hexdigest()[:16]
    state = 'home/.hermes/installs/' + key
    need(type(environment) is str and re.fullmatch(re.escape(state) + r'/environments/[a-f0-9]{32}/venv', environment) is not None, 'path')
    return state, environment + '/lib/python3.14/site-packages'


def collect(root, environment, interpreter):
    """Capture fixed owned subtrees through retained no-follow directory handles.

    SDK build dependencies and bytecode caches are not runtime input roots. Their
    names are recorded as exclusions, never opened. No limit is automatically
    enlarged when an actual installation exceeds it. A failed scan returns no
    partial catalogue, and does not remove anything.
    """
    state, site = selected_paths(root, environment)
    need(type(interpreter) is str and relative(interpreter) and '\\' not in interpreter and
         interpreter.startswith('home/.hermes/tools/') and interpreter.endswith('/bin/python3.14'), 'path')
    trees = ('sdk', 'tool', 'product', 'home/.hermes/tools', site,
             environment+'/bin', 'home/.hermes/plugins/hermes-hud')
    singles = (state + '/facts.json', environment + '/pyvenv.cfg', 'home/.hermes/config.yaml')
    exclude = frozenset(('sdk/node_modules', 'sdk/web/node_modules', 'sdk/.git', 'product/.git'))
    rows = []; excluded = []; aliases = []; interpreter_links = []; tool_links = []; tool_dirs = []; held = []; rootfd = None
    totals = {'bytes': 0, 'nodes': 0}; seen = set()
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW

    def component(name):
        need(type(name) is str and relative(name) and '/' not in name and '\\' not in name, 'path')

    def file(dfd, name, rel, before):
        need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1, 'file')
        kind = 'text' if PurePosixPath(name).suffix in TEXT or name in TEXT_NAMES else 'binary'
        limit = 2*1024**2 if kind == 'text' else 512*1024**2
        need(0 <= before.st_size <= limit and len(rows) < MAX_FILES and
             totals['bytes'] + before.st_size <= MAX_BYTES, 'file')
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dfd)
        try:
            need(file_stamp(before) == file_stamp(os.fstat(fd)), 'file')
            size = 0; digest = hashlib.sha256()
            while True:
                block = os.read(fd, min(262144, before.st_size-size+1))
                if not block: break
                size += len(block); need(size <= before.st_size, 'file'); digest.update(block)
            need(size == before.st_size and file_stamp(before) == file_stamp(os.fstat(fd)) ==
                 file_stamp(os.stat(name, dir_fd=dfd, follow_symlinks=False)), 'file')
        finally:
            os.close(fd)
        totals['bytes'] += size
        rows.append({'path': rel, 'kind': kind, 'bytes': size, 'sha256': digest.hexdigest()})

    def walk(dfd, prefix, depth):
        need(depth <= 24, 'path'); before = os.fstat(dfd); names = []
        if prefix == 'home/.hermes/tools' or prefix.startswith('home/.hermes/tools/'):
            tool_dirs.append(prefix)
        with os.scandir(dfd) as entries:
            for entry in entries:
                names.append(entry.name)
                need(len(names) <= MAX_NODES and totals['nodes'] + len(names) <= MAX_NODES, 'file')
        totals['nodes'] += len(names)
        need(len({n.casefold() for n in names}) == len(names), 'path')
        for name in sorted(names):
            component(name); rel = prefix + '/' + name
            need(rel.casefold() not in seen, 'path'); seen.add(rel.casefold())
            info = os.stat(name, dir_fd=dfd, follow_symlinks=False)
            # uv's three exact names are metadata only. Capture raw link text;
            # the complete three-node graph must end at the pinned owned image.
            if stat.S_ISLNK(info.st_mode) and prefix == environment+'/bin' and name in ('python', 'python3', 'python3.14'):
                target = os.readlink(name, dir_fd=dfd)
                need(file_stamp(info) ==
                     file_stamp(os.stat(name, dir_fd=dfd, follow_symlinks=False)), 'path')
                interpreter_links.append({'path':rel,'link':target}); continue
            # Tool links are bounded metadata only. Do not open or recursively
            # walk them. Their entire graph is validated after physical files
            # and directories have been captured with no-follow descriptors.
            if stat.S_ISLNK(info.st_mode) and rel.startswith('home/.hermes/tools/'):
                target = os.readlink(name, dir_fd=dfd)
                need(file_stamp(info) == file_stamp(os.stat(name, dir_fd=dfd, follow_symlinks=False)), 'file')
                tool_links.append({'path': rel, 'link': target})
                need(len(tool_links) <= 512, 'file'); continue
            # Even an excluded directory cannot be a symlink to elsewhere.
            need(stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode), 'file')
            if rel in exclude or name == '__pycache__':
                need(stat.S_ISDIR(info.st_mode), 'file'); excluded.append(rel); continue
            if stat.S_ISDIR(info.st_mode):
                child = os.open(name, flags, dir_fd=dfd)
                try:
                    need(file_stamp(info) == file_stamp(os.fstat(child)), 'file')
                    walk(child, rel, depth+1)
                    need(file_stamp(info) == file_stamp(os.fstat(child)) ==
                         file_stamp(os.stat(name, dir_fd=dfd, follow_symlinks=False)), 'file')
                finally: os.close(child)
            else: file(dfd, name, rel, info)
        need(file_stamp(before) == file_stamp(os.fstat(dfd)), 'file')

    def descend(parts):
        fd = rootfd; owned = []
        try:
            for name in parts:
                component(name); fd = os.open(name, flags, dir_fd=fd); owned.append(fd)
            return fd, owned
        except BaseException:
            close_all(owned)
            raise

    try:
        fd = os.open('/', flags); held.append(fd)
        for part in PurePosixPath(root).parts[1:]:
            fd = os.open(part, flags, dir_fd=fd); held.append(fd)
        rootfd = fd
        info = os.fstat(rootfd)
        need(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700, 'path')
        for name in trees:
            dfd, owned = descend(PurePosixPath(name).parts)
            try: walk(dfd, name, 0)
            finally: close_all(owned)
        for name in singles:
            parts = PurePosixPath(name).parts; dfd, owned = descend(parts[:-1])
            try: file(dfd, parts[-1], name, os.stat(parts[-1], dir_fd=dfd, follow_symlinks=False))
            finally: close_all(owned)
        rows.sort(key=lambda r: r['path'])
        need(interpreter in {r['path'] for r in rows}, 'binding')
        reader = BoundFiles(root, rows)
        reader.verify_all()  # separate traversal of each observed exact name
        result = {'schema': 'hermes_0222_observed_inventory_v1', 'files': rows,
                'excluded_directories': sorted(excluded), 'interpreter_aliases': aliases,
                'interpreter_links': interpreter_links,
                'tool_links': tool_links, 'tool_directories': sorted(tool_dirs),
                'total_bytes': totals['bytes'],
                'native_imports_verified': False, 'download_provenance_verified': False}
        bound=from_inventory(root, environment, interpreter, result)
        result['interpreter_aliases']=[{'path':a['path'],'target':a['target']} for a in bound['interpreter_aliases']]
        return result
    except Refused: raise
    except Exception: raise Refused('file') from None
    finally:
        close_all(held)


def _record_consistency(root, environment, files, read):
    """Check installed RECORD entries against observed bytes, without importing.

    Distribution RECORDs are installer output, not signatures. This validates
    consistency only. Paths may reach the selected venv's bin, but never escape
    that venv; those script bytes must be in the caller's explicit inventory.
    Empty hashes are admitted only for the RECORD itself. Unknown algorithms,
    unrecorded site files and editable source substitution fail closed.
    """
    _, site = selected_paths(root, environment)
    need(callable(read), 'schema')
    BoundFiles(root, files)
    byname = {r['path']: r for r in files}
    records = sorted(n for n in byname if n.startswith(site+'/') and
                     len(PurePosixPath(n[len(site)+1:]).parts) == 2 and
                     n.endswith('.dist-info/RECORD'))
    need(0 < len(records) <= 1024, 'schema'); covered = set(); entries = 0
    for record in records:
        raw = read(record); need(type(raw) is bytes and len(raw) <= 2*1024**2, 'file')
        need(hashlib.sha256(raw).hexdigest() == byname[record]['sha256'], 'binding')
        local = set()
        for columns in csv.reader(io.StringIO(raw.decode('utf-8')), strict=True):
            entries += 1; need(entries <= 32768 and len(columns) == 3, 'schema')
            name, checksum, size = columns
            need(name and len(name) <= 2048 and not name.startswith('/') and '\\' not in name and
                 all(32 <= ord(c) < 127 for c in name), 'path')
            parts = site.split('/')
            for part in name.split('/'):
                need(part not in ('', '.'), 'path')
                if part == '..':
                    need(len(parts) > len(environment.split('/')), 'path'); parts.pop()
                else: parts.append(part)
            target = '/'.join(parts)
            need(target in byname and target.casefold() not in local, 'binding')
            local.add(target.casefold()); covered.add(target)
            if checksum == '' and size == '':
                need(target == record, 'binding'); continue
            need(re.fullmatch(r'0|[1-9][0-9]{0,9}', size) is not None and
                 int(size) == byname[target]['bytes'], 'binding')
            need(checksum.startswith('sha256='), 'binding')
            encoded = checksum[len('sha256='):]
            expected = base64.urlsafe_b64encode(bytes.fromhex(byname[target]['sha256'])).rstrip(b'=').decode()
            need(encoded == expected, 'binding')
        need(record in covered, 'binding')
    # uv's two locally generated bootstrap files are separately source-bound by
    # validate_pth; they do not originate from a wheel RECORD.
    local_uv = {site+'/_virtualenv.py', site+'/_virtualenv.pth'}
    need({n for n in byname if n.startswith(site+'/')} <= covered | local_uv, 'binding')
    return {'schema': 'hermes_0222_record_consistency_v1', 'distributions': len(records),
            'entries': entries, 'covered_files': len(covered),
            'scope': 'INSTALLED_SELF_RECORD_CONSISTENCY_NOT_DOWNLOAD_AUTHENTICITY'}


def record_consistency(root, environment, files, read):
    try:
        return _record_consistency(root, environment, files, read)
    except Refused: raise
    except Exception: raise Refused('file') from None
