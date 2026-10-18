"""Real post-install composition: inventory -> PM -> plugin -> assets -> host input.

No process/download, grant, claim, persistence or native-success declaration.
This consumes a completed installation, not a synthetic declaration that one
exists. Actual installer execution/containment is a separate required gate.
"""
from installed_closure import collect, record_consistency, selected_paths
from plugin_handoff import verify as verify_plugin
from web_preparation import inspect_web
from pm_handoff import BoundFiles, HOST_COMMIT, HUD_COMMIT, inspect_handoff
from child_runtime import SCOPE, canonical_json, digest, validate, validate_pth
from runtime_aliases import NAME as ALIASES, from_inventory, verify as verify_aliases


def prepare(root, environment, interpreter, grant, port, paths, bindings, now):
    """Produce bound child input bytes without creating authority to execute them.

    Import paths and provenance bindings must come from the reviewed staging
    plan. They are validated against the actual capture, never discovered by
    importing packages, executing .pth or reading a real user's installation.
    """
    observed = collect(root, environment, interpreter)
    files = observed['files']; reader = BoundFiles(root, files)
    alias_raw = reader.read(ALIASES)
    from pm_handoff import need
    need(alias_raw == canonical_json(from_inventory(root, environment, interpreter, observed)), 'binding')
    verify_aliases(root, environment, interpreter, files, alias_raw)
    state, site = selected_paths(root, environment)
    records = record_consistency(root, environment, files, reader.read)
    plugin = verify_plugin(root, files, reader)
    web = inspect_web(root)
    handoff = {'schema':'hermes_0222_installed_handoff_v2','host_commit':HOST_COMMIT,
        'hud_commit':HUD_COMMIT,'python':'3.14.7','platform':'darwin-x64',
        'facts':state+'/facts.json','environment':environment,'interpreter':interpreter,
        'entry':'tool/official_entry.py','files':files}
    handoff_raw = canonical_json(handoff)
    inspected = inspect_handoff(handoff_raw,digest(handoff_raw),root)
    config = {'schema':'hermes_0222_child_bootstrap_v1','scope':SCOPE,'grant':grant,
        'root':root,'role':'host','port':port,'source':digest(canonical_json(files)),
        'files':files,'paths':list(paths),'bindings':dict(bindings),
        'selected_environment':root+'/'+environment,'interpreter':root+'/'+interpreter,
        'host_commit':HOST_COMMIT,'hud_commit':HUD_COMMIT}
    verified = validate(config,root,now)
    validate_pth(config,verified,root)
    verified.verify_all()
    # Assets were independently read. They must also be identical to the
    # earlier whole-inventory observation, not a later changed web tree.
    byname = {r['path']:r for r in files}
    from pm_handoff import need
    for asset in web['files']:
        row = byname.get('sdk/hermes_cli/web_dist/'+asset['path'])
        need(row is not None and (row['bytes'],row['sha256']) == (asset['bytes'],asset['sha256']), 'binding')
    return {'schema':'hermes_0222_install_completion_v1',
        'result':'INSTALLED_BYTES_BOUND_NOT_NATIVE_ACCEPTANCE',
        'child_config_bytes':canonical_json(config),'handoff_bytes':handoff_raw,
        'inventory':observed,'records':records,'plugin':plugin,'web':web,
        'pm_handoff':inspected,'native_ready':False,
        'missing_gate':'REVIEWED_INSTALLER_BOUNDARY_AND_FRESH_AUTHORITY'}
