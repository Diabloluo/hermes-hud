"""Single isolated host, fixed control acknowledgments and post-exit terminal seal."""
import importlib.machinery
import json
import os
from pathlib import Path
import signal
import sys
import threading
import time

sys.path.insert(0,str(Path(__file__).resolve().parent))
from common import read,atomic,require,digest,bounded
from boundary_policy import FilePolicy,BoundFrames,SOURCE_SHA,CONFIG_SOURCE_SHA
from guard_stack import GuardStack,clean_state
from optional_process import COLLECTORS_SHA
from lifecycle import ChildLifecycle,sources_valid,GRANT
from source_contract import capture,manifest_valid
from identity_contract import child_context

HERE=Path(__file__).resolve().parent


def boot():
    # Strict standalone child scope; no real-home or production fallback.
    require(os.environ.get('HUD_SHORT_CHILD')=='1' and sys.platform=='darwin','authority')
    home,out,repo=(Path(os.environ[k]).resolve() for k in ('HERMES_HOME','HUD_OUT','HUD_REPO'))
    grant=os.environ['HUD_GRANT'];port=int(os.environ['HUD_PORT']);begun=float(os.environ['HUD_BEGIN'])
    require(GRANT.fullmatch(grant) is not None and Path.cwd()==home and home.name=='synthetic-home'
            and out==home.parent/'evidence' and home.parent.name=='run'
            and home.parent.parent.name=='hud-short-startup-owned'
            and 1024<=port<=65535 and port!=9119,'authority')
    require(child_context(home.parent.parent,sys.executable,str(Path(sys.prefix).resolve()),
                          sys.orig_argv,sys.flags.isolated,sys.dont_write_bytecode),'authority')
    # Dependency imports only, before the audit hook; no real-user env inherited.
    import psutil  # noqa: F401
    import urllib3  # noqa: F401  optional IPv6 capability preload, unchanged from old remote runner.
    from native_io import site_root
    site=site_root()
    manifest=read(HERE/'SOURCE_MANIFEST.json')
    require(manifest_valid(manifest),'source')
    from entry import freeze_check
    freeze_check(os.environ['HUD_FREEZE'])
    sources=read(out/'source-start.json')
    require(sources_valid(sources) and sources==capture(manifest,repo,site,home),'source')
    bindings={str(site/row['name']):row['sha256'] for row in manifest['public']}
    require(bindings[str(site/'hermes_constants.py')]==SOURCE_SHA,'source')
    require(bindings[str(site/'hermes_cli/config.py')]==CONFIG_SOURCE_SHA,'source')
    collector = next((row for row in manifest['candidate'] if row['name']=='dashboard/hud/collectors.py'), None)
    require(collector is not None and collector['sha256']==COLLECTORS_SHA,'source')
    bindings[str(repo/'dashboard/hud/collectors.py')]=COLLECTORS_SHA
    roots=(str(repo),str(HERE),str(Path(sys.prefix).resolve()),str(Path(sys.base_prefix).resolve()),
           '/System','/usr/lib','/Library/Developer')
    stack=GuardStack(FilePolicy(str(home),str(out),roots,'darwin'),BoundFrames(bindings),str(home),port,
                     owner_uid=os.getuid(), platform=sys.platform)
    child=ChildLifecycle(stack,sources)
    stopped=threading.Event();worker_error=threading.Event()
    original=importlib.machinery.SourceFileLoader.exec_module
    activated=False;thread=None
    def fail(stage):
        worker_error.set()
        # Fixed stage/schema + strictly validated guard state; no argv, env, raw path or exception.
        atomic(out/'observer-failure.json',{'schema':'hud_short_guard_failure_v1',
              'stage':stage,'state':stack.state(),'raw_persisted':False})
    def worker():
        next_sequence=1
        try:
            while not stopped.is_set():
                require(time.monotonic()-begun<280,'budget')
                if (out/'control.json').exists():
                    command=read(out/'control.json')
                    require(type(command) is dict and set(command)=={'id','label','sequence'}
                            and command['id']==grant and type(command['sequence']) is int
                            and command['label'] in ('http','ws','finish'),'boundary')
                    sequence=command['sequence']
                    if sequence==next_sequence:
                        require(command['label']==('http','ws','finish')[sequence-1],'boundary')
                        ack=child.acknowledge(command['label'])
                        atomic(out/'ack.json',{'id':grant,'sequence':sequence,'ack':ack})
                        next_sequence+=1
                    else:require(sequence==next_sequence-1,'boundary')
                time.sleep(.05)
        except BaseException:fail('worker')
    def loaded(loader,mod):
        nonlocal activated,thread
        value=original(loader,mod)
        if Path(loader.path).resolve()==repo/'dashboard/plugin_api.py':
            require(not activated,'boundary');activated=True
            atomic(out/'ready.json',child.acknowledge('ready'))
            thread=threading.Thread(target=worker,daemon=True);thread.start()
        return value
    code=2;stage='host_import'
    try:
        stack.install()  # Separate open hook, not wrapped by this legacy guard.
        importlib.machinery.SourceFileLoader.exec_module=loaded
        signal.signal(signal.SIGTERM,lambda *_:sys.exit(0))
        from hermes_cli.main import main
        stage='host_main'
        main()
        code=0
    except SystemExit as error:
        code=error.code if type(error.code) is int and abs(error.code)<10000 else 2
        if code!=0:fail(stage)
    except BaseException:
        fail(stage);code=2
    finally:
        stopped.set()
        if thread is not None:thread.join(timeout=2)
        importlib.machinery.SourceFileLoader.exec_module=original
        commanded=False
        try:
            row=read(out/'finish-request.json')
            commanded=(type(row) is dict and set(row)=={'id','commanded_exit'}
                       and row['id']==grant and row['commanded_exit'] is True)
            ended=capture(manifest,repo,site,home)
            require(not worker_error.is_set() and (thread is None or not thread.is_alive()),'finish')
            freeze_check(os.environ['HUD_FREEZE'])
            terminal=child.terminal(ended,commanded,code)
        except BaseException:
            terminal={'schema':'hud_short_child_terminal_v3','candidate':'FAIL','source_end':None,
                      'state':stack.state(),'commanded_exit':commanded,'exit_code':code}
        atomic(out/'child-terminal.json',terminal)
    return code if terminal['candidate']=='PASS' else 2


if __name__=='__main__':
    try:raise SystemExit(boot())
    except BaseException as error:
        # Startup failures before a policy exists do not fabricate a safe state.
        if type(error) is SystemExit:raise
        raise SystemExit(2) from None
