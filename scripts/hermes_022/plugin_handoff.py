"""Bind the released HUD to the default in-process plugin path, never host mode.

Pure projection/verification. It neither copies files nor edits a user config.
The caller must stage the returned entries exclusively in a new synthetic home.
"""
from pm_handoff import BoundFiles, decode, need, relative, RELEASE_JS_SHA

PLUGIN = 'home/.hermes/plugins/hermes-hud/'
CONFIG = b'plugins:\n  isolation: in_process\n  enabled:\n    - hermes-hud\n  disabled: []\n'


def projection(files, read):
    """Return exact plugin bytes from the source-bound released product tree.

    No import, pip install, auto-enable command, project-plugin opt-in, symlink,
    or plugin-host spawn. Dependencies outside dashboard must be separately
    inventoried; copying this tree is not proof they are sufficient.
    """
    need(type(files) is list and 1 <= len(files) <= 8192 and callable(read), 'schema')
    rows = {}
    for row in files:
        need(type(row) is dict and set(row) == {'path','kind','bytes','sha256'}, 'schema')
        name = row['path']
        need(relative(name) and '\\' not in name and name.casefold() not in rows, 'path')
        rows[name.casefold()] = row
    selected = [r for r in files if r['path'].startswith('product/dashboard/')]
    need(4 <= len(selected) <= 512, 'schema')
    import hashlib
    result = []
    for row in selected:
        need(type(row['bytes']) is int and 0 <= row['bytes'] <= 2*1024**2, 'schema')
        raw = read(row['path'])
        need(type(raw) is bytes and len(raw) == row['bytes'] and hashlib.sha256(raw).hexdigest() == row['sha256'], 'binding')
        result.append({'path': PLUGIN+row['path'][len('product/'):], 'data': raw,
                       'sha256': row['sha256'], 'bytes': row['bytes']})
    manifest = next((r for r in result if r['path']==PLUGIN+'dashboard/manifest.json'), None)
    need(manifest is not None, 'binding'); data = decode(manifest['data'])
    need(type(data) is dict and data.get('name') == 'hermes-hud' and data.get('version') == '1.2.1'
         and data.get('entry') == 'dist/index.js' and data.get('css') == 'dist/style.css'
         and data.get('api') == 'plugin_api.py', 'binding')
    byname = {r['path']:r for r in result}
    for field in ('entry','css','api'): need(PLUGIN+'dashboard/'+data[field] in byname, 'binding')
    need(byname[PLUGIN+'dashboard/dist/index.js']['sha256'] == RELEASE_JS_SHA, 'binding')
    return result


def verify(root, files, reader):
    """Both original release and staged user-plugin copies remain byte bound."""
    BoundFiles(root, files)
    rows = {r['path']:r for r in files}
    # Source kind must allow a bounded bytes read; assets are classified text
    # by the inventory. Unsupported binaries fail rather than bypass the reader.
    expected = projection(files, reader.read)
    plugin_names = {r['path'] for r in files if r['path'].startswith(PLUGIN)}
    need(plugin_names == {r['path'] for r in expected}, 'binding')
    for row in expected:
        actual = rows[row['path']]
        need((actual['bytes'],actual['sha256']) == (row['bytes'],row['sha256']), 'binding')
        need(reader.read(row['path']) == row['data'], 'binding')
    need('home/.hermes/config.yaml' in rows and reader.read('home/.hermes/config.yaml') == CONFIG, 'binding')
    return {'schema':'hermes_0222_plugin_handoff_v1','plugin':'hermes-hud','version':'1.2.1',
            'isolation':'in_process','plugin_subprocesses':0,'copied_files':len(expected),
            'scope':'STAGED_FILE_BINDING_NOT_DISCOVERY_HTTP_OR_WS_VERIFICATION'}
