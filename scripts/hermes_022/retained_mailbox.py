"""Version-2 owned slots: prepare before guard, no open after preparation.

Not compatible with v1 absent-file commit markers. Parent alone stages all
empty slots after claim; child opens existing slots before installing its guard.
Exactly one writer per name is an assembly prerequisite, not a kernel sandbox.
Pinned parent/leaf checks do not prove the original ancestor namespace.
"""
import os
from pathlib import PurePosixPath
import re
import stat
from child_protocol import MAX, Refused, require, encode, decode

PARENT=frozenset(['session-payload.json','session-terminal.json']+
                 ['command-'+str(i)+'.json' for i in range(1,5)])
CHILD=frozenset(['ready.json','terminal.json']+['ack-'+str(i)+'.json' for i in range(1,5)])
NAMES=tuple(sorted(PARENT|CHILD))

def identity(s):return s.st_dev,s.st_ino
def stamp(s):return s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_nlink

class RetainedMailbox:
    def __init__(self,path,role,checkpoint,io=os):
        require(type(path) is str and re.fullmatch(
            '/private/tmp/hermes-022-run-[a-f0-9]{32}/evidence',path) is not None)
        require(role in ('parent','child'))
        self.path,self.role,self.checkpoint,self.io=path,role,checkpoint,io
        self.writes=PARENT if role=='parent' else CHILD
        self.owned=set();self.slots={};self.used=set();self.observed={}
        self.started=False;self.active=False;self.failed=False;self.closed=False
        self.close_errors=0;self.parent=None;self.parent_id=None;self.namespace=None

    def _close(self,fd):
        self.owned.remove(fd)
        try:self.io.close(fd)
        except BaseException:
            self.close_errors+=1;self.failed=True;raise Refused() from None

    def prepare(self,create=False):
        require(not self.started and not self.closed and not self.failed)
        self.started=True
        try:
            require(type(create) is bool and (not create or self.role=='parent'))
            flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW
            dirs=[];d=self.io.open('/',flags);self.owned.add(d);dirs.append(d)
            for part in PurePosixPath(self.path).parts[1:]:
                self.checkpoint();d=self.io.open(part,flags,dir_fd=d)
                self.owned.add(d);dirs.append(d)
            parent=self.io.fstat(d);require(stat.S_ISDIR(parent.st_mode))
            self.parent,self.parent_id=d,identity(parent)
            self.namespace=tuple(identity(self.io.fstat(fd)) for fd in dirs)
            for name in NAMES:
                pair=[]
                for leaf in (name,name+'.committed'):
                    self.checkpoint()
                    if create:
                        fd=self.io.open(leaf,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=d)
                        self.owned.add(fd);s=self.io.fstat(fd)
                        require(stat.S_ISREG(s.st_mode) and s.st_nlink==1 and s.st_size==0)
                        self.io.fsync(fd);self._close(fd)
                    mode=os.O_WRONLY if name in self.writes else os.O_RDONLY
                    fd=self.io.open(leaf,mode|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=d)
                    self.owned.add(fd);s=self.io.fstat(fd)
                    require(stat.S_ISREG(s.st_mode) and s.st_nlink==1 and
                            0<=s.st_size<=(1 if leaf.endswith('.committed') else MAX))
                    require(stamp(s)==stamp(self.io.stat(leaf,dir_fd=d,follow_symlinks=False)))
                    pair.append((fd,leaf,identity(s)))
                self.slots[name]=tuple(pair)
            if create:self.io.fsync(d)
            for fd in reversed(dirs[:-1]):self._close(fd)
            self.active=True;self.checkpoint();return self
        except BaseException:
            self.failed=True
            try:self.close()
            except BaseException:pass
            raise Refused() from None

    def verify_parent_namespace(self):
        # Parent only: the child must never traverse after installing its guard.
        # This is a bounded observation of named ancestors, not race-free OS containment.
        require(self.role=='parent' and self.active and not self.failed and not self.closed)
        dirs=[]
        try:
            self.checkpoint();flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW
            d=self.io.open('/',flags);self.owned.add(d);dirs.append(d)
            for part in PurePosixPath(self.path).parts[1:]:
                self.checkpoint();d=self.io.open(part,flags,dir_fd=d);self.owned.add(d);dirs.append(d)
            current=tuple(identity(self.io.fstat(fd)) for fd in dirs)
            require(current==self.namespace)
            for pair in self.slots.values():
                for slot in pair:self._check(slot)
            self.checkpoint()
        except BaseException:self.failed=True;raise Refused() from None
        finally:
            bad=False
            for fd in reversed(dirs):
                try:self._close(fd)
                except BaseException:bad=True
            if bad:raise Refused() from None
        return {'schema':'mailbox_parent_path_check_v1','ancestors':len(current),'slots':len(self.slots),
                'scope':'POINT_IN_TIME_PARENT_NAMESPACE_AND_LEAF_ONLY','native_verified':False}

    def _check(self,slot):
        require(self.active and not self.failed and not self.closed)
        self.checkpoint();fd,name,expected=slot
        p=self.io.fstat(self.parent);s=self.io.fstat(fd)
        leaf=self.io.stat(name,dir_fd=self.parent,follow_symlinks=False)
        require(stat.S_ISDIR(p.st_mode) and identity(p)==self.parent_id
                and stat.S_ISREG(s.st_mode) and stat.S_ISREG(leaf.st_mode)
                and s.st_nlink==1 and identity(s)==expected and stamp(s)==stamp(leaf))
        return s

    def write_once(self,name,row):
        try:
            require(type(name) is str and name in self.writes and name not in self.used)
            self.used.add(name) # consumes even encode, IO or fsync failure
            data=encode(row);payload,marker=self.slots[name]
            require(self._check(payload).st_size==0 and self._check(marker).st_size==0)
            offset=0
            while offset<len(data):
                self._check(payload);n=self.io.pwrite(payload[0],data[offset:],offset)
                require(type(n) is int and 0<n<=len(data)-offset);offset+=n
            self.io.fsync(payload[0]);require(self._check(payload).st_size==len(data))
            require(self._check(marker).st_size==0)
            require(self.io.pwrite(marker[0],b'1',0)==1)
            self.io.fsync(marker[0]);require(self._check(marker).st_size==1)
            self.checkpoint()
        except BaseException:self.failed=True;raise Refused() from None

    def read(self,name):
        try:
            require(type(name) is str and name in self.slots and name not in self.writes)
            payload,marker=self.slots[name];mark=self._check(marker)
            require(mark.st_size in (0,1))
            if mark.st_size==0:return None
            require(self.io.pread(marker[0],2,0)==b'1')
            before=self._check(payload);require(0<before.st_size<=MAX)
            data=b''
            while len(data)<before.st_size:
                self.checkpoint();chunk=self.io.pread(payload[0],min(4096,before.st_size-len(data)),len(data))
                require(type(chunk) is bytes and bool(chunk));data+=chunk
            require(self.io.pread(payload[0],1,len(data))==b''
                    and stamp(before)==stamp(self._check(payload))
                    and stamp(mark)==stamp(self._check(marker)))
            current=(stamp(before),stamp(mark),data)
            require(name not in self.observed or self.observed[name]==current)
            self.observed[name]=current;self.checkpoint();return decode(data)
        except BaseException:self.failed=True;raise Refused() from None

    def close(self):
        self.active=False;self.closed=True
        for fd in sorted(self.owned,reverse=True):
            try:self._close(fd)
            except BaseException:pass
        self.slots.clear();self.observed.clear()
        require(not self.owned and self.close_errors==0)

    def status(self):
        return {'schema':'retained_mailbox_v2','role':self.role,'failed':self.failed,
                'closed':self.closed,'owned_descriptors':len(self.owned),
                'close_errors':self.close_errors,'native_verified':False}
