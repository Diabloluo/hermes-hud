"""Exact runtime reads + existing file/network/SQL/process/signal guard + write fence.

Python audit is not OS containment. Native extension internals, interpreter
startup and metadata reads are not covered. There is no directory read fallback.
Unbound import bytecode for a bound .py is synthesized absent, never read.
"""
import importlib.util
import os
import sys
import threading
from boundary_policy import FilePolicy, BoundFrames, access_class, MISSING_SITES, canonical_text, valid_frames
from guard_stack import GuardStack
from runtime_fence import HostBoundary, within
from child_protocol import require

PLATFORM_SHA='fd760a3f044d6201aa5b543d0166de11f27e2da6a700839623ebd67ce1037d6a'
PLATFORM_SITES={'/proc/version':('version',(22,)), '/proc/1/cgroup':('cgroup',(42,49,58)),
                '/proc/self/mountinfo':('mountinfo',(42,68,63))}

class ExactPolicy:
    def __init__(self, root, files, platform):
        self.root=root
        self.exact=frozenset(root+'/'+r['path'] for r in files)
        self.protected=tuple(root+'/'+s for s in ('sdk','bootstrap','product','tool','home/.hermes/tools','home/.hermes/installs',
                                                  'home/.hermes/plugins','home/.hermes/config.yaml'))
        self.mutable=(root+'/home',root+'/tmp') # evidence is transport-owned, never a host content root
        self.base=FilePolicy(root+'/home',root+'/tmp',(root+'/sdk',),platform)
        self.caches=frozenset(importlib.util.cache_from_source(p) for p in self.exact if p.endswith('.py'))-self.exact
        self.lease_names=lambda:()
        self.platform=platform;self.probe_lock=threading.Lock()
        self.platform_missing={key:0 for key in ('version','cgroup','mountinfo')}

    def check(self,requested,canonical,mode,flags,caller,immediate):
        access=access_class(mode,flags)
        # A bounded source read uses NONBLOCK to avoid substituted special files.
        if type(flags) is int and flags & os.O_NONBLOCK and requested in self.exact:
            access=access_class(mode,flags & ~os.O_NONBLOCK)
        same=type(requested) is str and requested==canonical and canonical_text(canonical)
        if type(requested) is str and requested in PLATFORM_SITES:
            key,lines=PLATFORM_SITES[requested]
            expected=[{'source_sha256':PLATFORM_SHA,'line':n} for n in lines]
            if (same and self.platform=='darwin' and access=='read' and valid_frames(caller)
                    and caller['truncated'] is False and immediate==expected[0]
                    and caller['frames'][:len(expected)]==expected):
                with self.probe_lock:
                    if self.platform_missing[key]==0:
                        self.platform_missing[key]=1
                        raise FileNotFoundError('isolated_platform_resource_unavailable') from None
            # Do not fall back to the older constants/config probe contract.
            return self.base.check(None,None,mode,flags,caller,immediate)
        if (same and requested in self.lease_names() and mode is None and type(flags) is int
                and flags & ~getattr(os,'O_CLOEXEC',0) in (os.O_RDWR,os.O_CREAT|os.O_RDWR,os.O_CREAT|os.O_EXCL|os.O_RDWR)):
            return # only after HostBoundary's stricter first hook admitted this event
        if same and requested in self.exact and access=='read':return
        if same and requested in self.caches and access=='read':
            raise FileNotFoundError('bound_source_bytecode_not_admitted') from None
        if same and requested in MISSING_SITES:
            return self.base.check(requested,canonical,mode,flags,caller,immediate)
        if (same and any(within(requested,p) for p in self.mutable)
                and not any(within(requested,p) or within(p,requested) for p in self.protected)):
            return self.base.check(requested,canonical,mode,flags,caller,immediate)
        # Never delegate an unknown path to broad legacy sdk/home read roots.
        return self.base.check(None,None,mode,flags,caller,immediate)

    def state(self):return self.base.state()
    def ensure_clean(self):return self.base.ensure_clean()

class FullGuard:
    def __init__(self,root,files,paths,bindings,port,selected_environment,*,platform,owner_uid,
                 register=sys.addaudithook,resolve=os.path.realpath):
        self.policy=ExactPolicy(root,files,platform)
        self.stack=GuardStack(self.policy,BoundFrames(bindings),root+'/home',port,owner_uid,platform)
        self.register=register;self.failed=False;self.used=False;self.lock=threading.Lock()
        # HostBoundary installs its write fence, then this object's install.
        self.boundary=HostBoundary(root,paths,self,selected_environment=selected_environment,resolve=resolve,register=register)
        self.policy.lease_names=lambda:tuple(self.boundary.created_leases)+((self.boundary.state+'/.install.lock',) if self.boundary.state else ())

    def deny(self):
        with self.lock:self.failed=True
        require(False)

    def extra(self,event,args):
        # Remains sticky without poisoning non-I/O diagnostic slot writes.
        if event=='open' and (type(args) is not tuple or len(args)!=3 or type(args[0]) is int):self.deny()
        if event.startswith('ctypes.') or event in ('os.forkpty','os.startfile','os.startfile/2','pty.spawn'):
            self.deny()
        if event in ('socket.getaddrinfo','socket.gethostbyname','socket.gethostbyaddr','socket.sendto','socket.sendmsg'):
            self.deny()
        if event=='os.chdir':
            if type(args) is not tuple or len(args)!=1:self.deny()
            try:self.boundary.path(args[0])
            except BaseException:self.deny()
        if event=='sqlite3.connect':
            # Legacy SQL home check is retained, and immutable runtime/URI
            # aliases cannot acquire database writes through sqlite's C layer.
            try:
                require(type(args) is tuple and len(args)==1 and type(args[0]) is str)
                self.boundary.writable(args[0])
            except BaseException:self.deny()
        if event=='import' and len(args)>1 and args[1] is not None:
            if type(args[1]) is not str or args[1] not in self.policy.exact:self.deny()

    def install(self):
        if self.used:self.deny()
        self.used=True;self.register(self.extra);self.stack.install(self.register)

    def checkpoint(self):
        if not self.used or self.failed:self.deny()
        legacy=self.stack.checkpoint()
        with self.policy.probe_lock:missing=dict(self.policy.platform_missing)
        return {'schema':'hermes_0222_full_guard_v1','legacy':legacy,'platform_missing':missing,
                'scope':'PYTHON_AUDIT_RESTRICTED_SYNTHETIC_ONLY'}
