"""Child-only PM/Hermes call dispatch; not a standalone native executor.

The parent must supply the reviewed boundary and source verification objects,
fresh authorization/claim, owned process lifecycle, and startup stop channel.
No default boundary, CLI, installer spawning, or implicit native permission.
"""
import importlib
from pathlib import PurePosixPath
import re
import sys

PM_ARGS=("install","--without","agent-browser","--without","cua-driver")
ERRORS=frozenset(("input","environment","source_start","guard_install","path_install",
                  "entry_import","entry_call","entry_exit","source_end","guard_end"))


class Refused(ValueError):
    def __init__(self, code):super().__init__(code if code in ERRORS else "input")


def need(ok,code="input"):
    if ok is not True:raise Refused(code) from None


def layout(root):
    need(type(root) is str and re.fullmatch("/private/tmp/hermes-022-run-[a-f0-9]{32}",root) is not None)
    # HOME and the active Hermes home agree with the default home PM uses
    # for tools/partials/uv cache. No runtimeDir override or system store.
    home=root+"/home"
    return {"root":root,"home":home,"hermes_home":home+"/.hermes","sdk":root+"/sdk",
            "tmp":root+"/tmp","store":home+"/.hermes/tools"}


def environment(root, role, token=None):
    p=layout(root);need(role in ("install","host"))
    env={"HOME":p["home"],"HERMES_HOME":p["hermes_home"],"TMPDIR":p["tmp"],
         "PATH":"/usr/bin:/bin:/usr/sbin:/sbin","LANG":"en_US.UTF-8","LC_CTYPE":"en_US.UTF-8",
         "TZ":"UTC","PYTHONDONTWRITEBYTECODE":"1","PYTHONNOUSERSITE":"1",
         "XDG_CACHE_HOME":p["home"]+"/.cache","UV_CACHE_DIR":p["hermes_home"]+"/cache/uv"}
    if role=="host":
        need(type(token) is str and re.fullmatch("[A-Za-z0-9_-]{32,128}",token) is not None)
        env.update(HERMES_DISABLE_LAZY_INSTALLS="1",HERMES_DASHBOARD_SESSION_TOKEN=token)
    else:need(token is None)
    return env


def argv(root,role,port=None):
    layout(root);need(role in ("install","host"))
    entry=root+"/tool/official_entry.py"
    if role=="install":
        need(port is None)
        return [entry,"pm",*PM_ARGS]
    need(type(port) is int and 1024<=port<=65535 and port!=9119)
    return [entry,"dashboard","--host","127.0.0.1","--port",str(port),
            "--no-open","--skip-build","--isolated"]


def result_code(value):
    if value is None:return 0
    need(type(value) is int and -255<=value<=255,"entry_exit")
    return value


def dispatch(root,role,actual_env,boundary,source_check,*,port=None,token=None,
             importer=importlib.import_module,runtime=sys):
    """Import and call the official entry, with guards installed before imports.

    In a fresh authorized child the default importer is real importlib. Offline
    tests inject inert modules; they do not execute any PM or Hermes handler.
    The mandatory boundary is responsible for exact reads and all native I/O,
    not caller-provided success booleans. The returned row never claims PASS.
    """
    stage="input";error=None;cleanup=None;code=None;entered=False
    previous_path=None;previous_argv=None;bound_path=None;bound_argv=None;installed=False
    try:
        p=layout(root);expected_env=environment(root,role,token)
        expected_argv=argv(root,role,port)
        need(type(actual_env) is dict and actual_env==expected_env,"environment")
        need(callable(source_check) and all(callable(getattr(boundary,k,None))
             for k in ("install","checkpoint","validate_paths")))
        need(type(runtime.path) is list and type(runtime.argv) is list)
        # Do not accidentally import a previously loaded upstream module from
        # a different installation. Fresh native children satisfy this gate.
        need(not any(k=="pm" or k.startswith("pm.") or k=="hermes_cli" or k.startswith("hermes_cli.")
                     or k=="hermes_bootstrap" for k in runtime.modules))
        stage="source_start";before=source_check()
        need(type(before) is str and re.fullmatch("[a-f0-9]{64}",before) is not None,stage)
        stage="guard_install";boundary.install();boundary.checkpoint()
        stage="path_install"
        previous_path=runtime.path;previous_argv=runtime.argv
        # No inherited current-directory element and no path from PM facts is
        # added here. The boundary validates existing interpreter paths.
        need(all(type(s) is str and s and PurePosixPath(s).is_absolute() for s in previous_path),stage)
        bound_path=[p["sdk"],*[s for s in previous_path if s!=p["sdk"]]]
        boundary.validate_paths(tuple(bound_path))
        bound_argv=list(expected_argv);runtime.path=bound_path;runtime.argv=bound_argv;installed=True
        stage="entry_import";module=importer("pm.cli" if role=="install" else "hermes_cli.main")
        need(callable(getattr(module,"main",None)),stage)
        # Source/import/argv integrity is rechecked before the first handler.
        boundary.checkpoint();boundary.validate_paths(tuple(runtime.path))
        need(runtime.argv is bound_argv and runtime.argv==expected_argv,stage)
        stage="entry_call";entered=True
        try:
            value=module.main(list(PM_ARGS)) if role=="install" else module.main()
            code=result_code(value)
        except SystemExit as exc:code=result_code(exc.code)
        stage="entry_exit";need(code==0,stage)
        stage="source_end";need(source_check()==before,stage)
        stage="guard_end";boundary.checkpoint();boundary.validate_paths(tuple(runtime.path))
        need(runtime.argv is bound_argv and runtime.argv==expected_argv,stage)
    except BaseException as exc:
        error=exc.args[0] if type(exc) is Refused and exc.args[0] in ERRORS else stage
    finally:
        if installed:
            if runtime.path is bound_path:runtime.path=previous_path
            else:cleanup="path_replaced"
        if installed:
            if runtime.argv is bound_argv:runtime.argv=previous_argv
            else:cleanup=cleanup or "argv_replaced"
    return {"schema":"hermes_0222_official_call_v1","result":"CALL_RETURNED_ZERO_NOT_ACCEPTANCE" if error is None and cleanup is None else "FAIL",
            "error":error,"cleanup_error":cleanup,"entry_called":entered,"exit_code":code,
            "native_verified":False,"memory":"WARN_NOT_ACCEPTED","public_release":"BLOCK"}


if __name__=="__main__":
    # -I omits the script directory. Only this canonical owned tool directory
    # is inserted, never cwd, user site, or an ambient PYTHONPATH.
    import os
    own=os.path.abspath(__file__)
    if (os.path.realpath(own)!=own or re.fullmatch(
            r"/private/tmp/hermes-022-run-[a-f0-9]{32}/tool/official_entry.py",own) is None):
        raise SystemExit(2)
    sys.path.insert(0,os.path.dirname(own))
    from child_runtime import main
    raise SystemExit(main(own))
