"""Additive host-phase write fence; NOT an installer policy or OS sandbox.

The existing full guard remains mandatory and is installed after this fence.
An exact, parent-verified import-path tuple is required; no directory fallback.
Read admission, native library loading, fd ownership, network and process rules
remain the full guard's responsibility. Python audit cannot contain all native
I/O; installation of this fence alone never establishes native readiness.
"""
import hashlib
import os
from pathlib import PurePosixPath
import re
import sys


class Refused(ValueError):
    def __init__(self):super().__init__('runtime_boundary')


def need(ok):
    if ok is not True:raise Refused() from None


def canonical(value):
    return (type(value) is str and value.startswith('/') and
            str(PurePosixPath(value))==value and '..' not in PurePosixPath(value).parts
            and all(32<=ord(c)<127 for c in value))


def within(path,root):return path==root or path.startswith(root+'/')


class HostBoundary:
    def __init__(self,root,import_paths,guard,*,selected_environment=None,resolve=os.path.realpath,register=sys.addaudithook):
        need(type(root) is str and re.fullmatch('/private/tmp/hermes-022-run-[a-f0-9]{32}',root) is not None)
        need(type(import_paths) is tuple and 1<=len(import_paths)<=128
             and len(set(import_paths))==len(import_paths)
             and all(canonical(p) and within(p,root) for p in import_paths))
        need(all(callable(getattr(guard,k,None)) for k in ('install','checkpoint'))
             and callable(resolve) and callable(register))
        self.root=root;self.paths=import_paths;self.guard=guard
        self.resolve=resolve;self.register=register;self.installed=False;self.failed=False
        # Protect ALL install metadata, not merely the selected generation:
        # facts changes could redirect the PM to unreviewed dependencies.
        self.protected=tuple(root+'/'+p for p in ('sdk','bootstrap','product','tool',
                            'home/.hermes/tools','home/.hermes/installs',
                            'home/.hermes/plugins','home/.hermes/config.yaml'))
        self.mutable=tuple(root+'/'+p for p in ('home','tmp','evidence'))
        self.state=None;self.leases=None;self.created_leases=set()
        if selected_environment is not None:
            key=hashlib.sha256((root+'/sdk').encode()).hexdigest()[:16]
            state=root+'/home/.hermes/installs/'+key
            need(type(selected_environment) is str and re.fullmatch(re.escape(state)+r'/environments/[a-f0-9]{32}/venv',selected_environment) is not None)
            self.state=state;self.leases=str(PurePosixPath(selected_environment).parent)+ '/.leases'

    def lease_event(self,event,args):
        """Only PM lock/lease metadata, never facts, code, config or recovery.

        A fresh run must have no stale lease or publication journal. Unknown
        leases are refused instead of enabling PM pruning. Audit admission is
        NOT proof that the subsequent syscall succeeded or that flock is held.
        """
        if self.state is None:return False
        if event=='os.mkdir' and type(args) is tuple and len(args)==3 and args[0] in (self.state,self.leases):
            self.path(args[0],args[2]);return True
        if event=='os.remove' and type(args) is tuple and len(args)==2 and args[0] in self.created_leases:
            self.path(args[0],args[1]);return True
        if event!='open' or type(args) is not tuple or len(args)!=3:return False
        path,mode,flags=args
        if type(path) is not str or mode is not None or type(flags) is not int:return False
        flags=flags & ~getattr(os,'O_CLOEXEC',0)
        if path==self.state+'/.install.lock' and flags==(os.O_CREAT|os.O_RDWR):
            self.path(path);return True
        if not path.startswith(self.leases+'/') or re.fullmatch('[a-f0-9]{32}',path[len(self.leases)+1:]) is None:return False
        self.path(path)
        if flags==(os.O_CREAT|os.O_EXCL|os.O_RDWR):
            if len(self.created_leases)>=8 or path in self.created_leases:self.deny()
            self.created_leases.add(path);return True
        return path in self.created_leases and flags==os.O_RDWR

    def deny(self):
        self.failed=True
        raise Refused() from None

    def path(self,value,dir_fd=None):
        # Integer fd/dir_fd writes are not path-proven here. No broad exception.
        if dir_fd not in (None,-1) or not canonical(value) or not within(value,self.root):self.deny()
        try:resolved=self.resolve(value)
        except BaseException:self.deny()
        if resolved!=value:self.deny()
        return value

    def writable(self,value,dir_fd=None):
        p=self.path(value,dir_fd)
        # Includes ancestors: cannot rename/remove/chmod HOME to replace the
        # protected tool tree, even though HOME itself is a mutable root.
        if (not any(within(p,r) for r in self.mutable) or
            any(within(p,r) or within(r,p) for r in self.protected)):self.deny()

    def event(self,event,args):
        # Sticky failure must not deny interpreter bookkeeping (for example
        # traceback frame access), otherwise even fixed FAIL sealing can be
        # interrupted. All covered filesystem operations still fail closed;
        # network/SQL/exec/signal hooks remain separately installed.
        if event not in ('open','os.rename','os.link','os.symlink','os.remove','os.rmdir',
                         'os.mkdir','os.chmod','os.chown','os.utime','os.truncate'):return
        if self.failed:self.deny()
        if self.lease_event(event,args):return
        if event=='open':
            if type(args) is not tuple or len(args)!=3:self.deny()
            path,mode,flags=args
            if type(flags) is not int or (mode is not None and type(mode) is not str):self.deny()
            writes=(flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))!=0
            writes=writes or (type(mode) is str and any(c in mode for c in 'wax+'))
            if writes:self.writable(path)
        elif event in ('os.rename','os.link'):
            if type(args) is not tuple or len(args)!=4:self.deny()
            # No hardlinks: they can make an admitted data file an alias.
            if event=='os.link':self.deny()
            self.writable(args[0],args[2]);self.writable(args[1],args[3])
        elif event=='os.symlink':self.deny()
        elif event in ('os.remove','os.rmdir'):
            if type(args) is not tuple or len(args)!=2:self.deny()
            self.writable(args[0],args[1])
        elif event in ('os.mkdir','os.chmod'):
            if type(args) is not tuple or len(args)!=3:self.deny()
            self.writable(args[0],args[2])
        elif event=='os.chown':
            if type(args) is not tuple or len(args)!=4:self.deny()
            self.writable(args[0],args[3])
        elif event=='os.utime':
            if type(args) is not tuple or len(args)!=4:self.deny()
            self.writable(args[0],args[3])
        elif event=='os.truncate':
            if type(args) is not tuple or len(args)!=2:self.deny()
            self.writable(args[0])
        # All other events still reach the mandatory legacy full guard.

    def install(self):
        need(not self.installed and not self.failed)
        self.installed=True
        try:
            self.register(self.event)
            self.guard.install()
            self.guard.checkpoint()
        except BaseException:self.deny()

    def checkpoint(self):
        if not self.installed or self.failed:self.deny()
        try:return self.guard.checkpoint()
        except BaseException:self.deny()

    def validate_paths(self,paths):
        if not self.installed or self.failed or type(paths) is not tuple or paths!=self.paths:self.deny()
        for p in paths:self.path(p)
        self.checkpoint()


if __name__=='__main__':raise SystemExit('NOT_A_NATIVE_ENTRY')
