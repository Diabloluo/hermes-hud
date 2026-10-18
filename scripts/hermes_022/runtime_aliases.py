"""Bounded installed-link metadata. No symlink becomes a content-read root.

Only links inside one owned PM tool package may resolve to captured files or
directories in that same package. Metadata is bound through one regular JSON
input and rechecked before/after host execution. No installed tree is rewritten.
"""
import hashlib
import json
import os
from pathlib import PurePosixPath
import stat
import re
from pm_handoff import need, relative, file_stamp, decode

NAME = 'tool/installed-aliases.json'
SCHEMA = 'hermes_0222_installed_aliases_v2'
MAX_LINKS = 512
MAX_DIRS = 16384
PREFIX = ('home', '.hermes', 'tools')


def package(path):
    need(relative(path) and '\\' not in path, 'path')
    parts = PurePosixPath(path).parts
    need(len(parts) > 4 and parts[:3] == PREFIX, 'path')
    return parts[:4]


def normalize(path, link):
    anchor = package(path)
    need(type(link) is str and 0 < len(link) <= 2048
         and not link.startswith('/') and '\\' not in link
         and all(32 <= ord(c) < 127 for c in link), 'path')
    parts = list(PurePosixPath(path).parent.parts)
    for item in link.split('/'):
        if item in ('', '.'): continue
        if item == '..':
            need(len(parts) > len(anchor), 'path'); parts.pop()
        else: parts.append(item)
    need(tuple(parts[:4]) == anchor, 'path')
    return '/'.join(parts)


def resolve(path, links):
    target = normalize(path, links[path]); anchor = package(path); visited = {path}
    for _ in range(32):
        parts = PurePosixPath(target).parts; expanded = False
        for end in range(5, len(parts)+1):
            name = '/'.join(parts[:end])
            if name not in links: continue
            need(name not in visited and package(name) == anchor, 'path')
            visited.add(name)
            target = normalize(name, links[name])
            if end < len(parts): target += '/' + '/'.join(parts[end:])
            need(tuple(PurePosixPath(target).parts[:4]) == anchor, 'path')
            expanded = True; break
        if not expanded: return target
    need(False, 'path')


def manifest(root, environment, interpreter, files, links, directories, interpreter_links):
    """Pure graph validation, not link traversal or namespace containment."""
    need(type(root) is str and re.fullmatch('/private/tmp/hermes-022-run-[a-f0-9]{32}',root) is not None, 'path')
    key=hashlib.sha256((root+'/sdk').encode()).hexdigest()[:16]
    need(type(environment) is str and re.fullmatch('home/\\.hermes/installs/'+key+
         '/environments/[a-f0-9]{32}/venv',environment) is not None, 'path')
    package(interpreter)
    need(type(links) is list and len(links) <= MAX_LINKS and type(directories) is list
         and len(directories) <= MAX_DIRS and type(interpreter_links) is list
         and len(interpreter_links) <= 3, 'schema')
    byfile = {r['path'] for r in files}; dirs = set()
    for d in directories:
        need(relative(d) and '\\' not in d and
             (d == 'home/.hermes/tools' or PurePosixPath(d).parts[:3] == PREFIX)
             and d.casefold() not in {n.casefold() for n in dirs}, 'path')
        dirs.add(d)
    graph = {}
    for link in links:
        need(type(link) is dict and set(link) == {'path', 'link'}, 'schema')
        name = link['path']; package(name); normalize(name, link['link'])
        need(name.casefold() not in {n.casefold() for n in byfile|dirs}
             and name.casefold() not in {n.casefold() for n in graph}, 'path')
        graph[name] = link['link']
    rows = []
    for name in sorted(graph):
        target = resolve(name, graph)
        need(target in byfile or target in dirs, 'binding')
        kind = 'file' if target in byfile else 'directory'
        if kind == 'directory':
            need(not name.startswith(target+'/'), 'path')
        rows.append({'path': name, 'link': graph[name], 'target': target, 'kind': kind})
    aliases = []; graph = {}; names = ('python','python3','python3.14')
    allowed = {environment+'/bin/'+n for n in names}
    for a in interpreter_links:
        need(type(a) is dict and set(a) == {'path', 'link'} and a['path'] in allowed
             and a['path'] not in graph and type(a['link']) is str
             and a['link'] in (*names,root+'/'+interpreter) and interpreter in byfile, 'path')
        graph[a['path']] = a['link']
    for name, link in sorted(graph.items()):
        cursor = name; seen = set()
        for _ in range(3):
            need(cursor in graph and cursor not in seen, 'path'); seen.add(cursor)
            if graph[cursor] == root+'/'+interpreter:break
            cursor = environment+'/bin/'+graph[cursor]
        else:need(False, 'path')
        aliases.append({'path':name,'link':link,'target':interpreter})
    return {'schema': SCHEMA, 'tool_links': rows, 'directories': sorted(dirs),
            'interpreter_aliases': sorted(aliases, key=lambda a:a['path'])}


def from_inventory(root, environment, interpreter, inventory):
    return manifest(root, environment, interpreter, inventory['files'], inventory['tool_links'],
                    inventory['tool_directories'], inventory['interpreter_links'])


def _metadata(root, name, leaf_kind):
    """Exact metadata only; no open of a directory or link target content."""
    need(relative(name), 'path')
    path = root
    for index, part in enumerate(PurePosixPath(name).parts):
        path += '/'+part; s = os.lstat(path)
        last = index == len(PurePosixPath(name).parts)-1
        if not last or leaf_kind == 'directory': need(stat.S_ISDIR(s.st_mode), 'path')
        elif leaf_kind == 'file': need(stat.S_ISREG(s.st_mode) and s.st_nlink == 1, 'file')
        else: need(stat.S_ISLNK(s.st_mode), 'path')
    return s


def verify(root, environment, interpreter, files, raw):
    """Validate fixed JSON and exact link metadata; never grant content access."""
    row = decode(raw)
    need(type(row) is dict and set(row) == {'schema','tool_links','directories','interpreter_aliases'}
         and row['schema'] == SCHEMA and type(row['tool_links']) is list, 'schema')
    links = []
    for a in row['tool_links']:
        need(type(a) is dict and set(a) == {'path','link','target','kind'}, 'schema')
        links.append({'path':a['path'],'link':a['link']})
    need(type(row['interpreter_aliases']) is list, 'schema'); venv_links=[]
    for a in row['interpreter_aliases']:
        need(type(a) is dict and set(a)=={'path','link','target'}, 'schema')
        venv_links.append({'path':a['path'],'link':a['link']})
    expected = manifest(root, environment, interpreter, files, links, row['directories'], venv_links)
    need(row == expected, 'binding')
    canonical = (json.dumps(row,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
    need(raw == canonical, 'schema')
    for a in row['tool_links']:
        before = _metadata(root, a['path'], 'link')
        need(os.readlink(root+'/'+a['path']) == a['link'], 'binding')
        _metadata(root, a['target'], a['kind'])
        need(file_stamp(before) == file_stamp(_metadata(root, a['path'], 'link'))
             and os.readlink(root+'/'+a['path']) == a['link'], 'binding')
    for a in row['interpreter_aliases']:
        before = _metadata(root, a['path'], 'link')
        need(os.readlink(root+'/'+a['path']) == a['link'], 'binding')
        _metadata(root, a['target'], 'file')
        need(file_stamp(before) == file_stamp(_metadata(root, a['path'], 'link'))
             and os.readlink(root+'/'+a['path']) == a['link'], 'binding')
    return len(links)+len(row['interpreter_aliases'])
