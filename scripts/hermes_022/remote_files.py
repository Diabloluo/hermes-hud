"""Bounded file IO and exclusive owned writes used by the remote assembly."""
import hashlib
import os
import re
from pathlib import PurePosixPath
import stat
from remote_contract import need
from pm_handoff import file_stamp, relative

def read(path,limit=2*1024**2):
    need(type(path) is str and path.startswith('/') and os.path.realpath(path)==path)
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        before=os.fstat(fd);need(stat.S_ISREG(before.st_mode) and before.st_nlink==1 and 0<=before.st_size<=limit)
        data=b''
        while len(data)<before.st_size:
            part=os.read(fd,min(262144,before.st_size-len(data)));need(bool(part));data+=part
        need(os.read(fd,1)==b'' and file_stamp(before)==file_stamp(os.fstat(fd))==file_stamp(os.lstat(path)))
        return data
    finally: os.close(fd)

def write_new(root,name,data,mode=0o600):
    need(type(root) is str and re.fullmatch('/private/tmp/hermes-022-run-[a-f0-9]{32}',root) is not None
         and relative(name) and '\\' not in name and type(data) is bytes and len(data)<=512*1024**2
         and mode in (0o600,0o644,0o755))
    fds=[];out=None
    try:
        d=os.open('/',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW);fds.append(d)
        for part in PurePosixPath(root).parts[1:]:
            d=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=d);fds.append(d)
        info=os.fstat(d);need(info.st_uid==os.getuid() and stat.S_IMODE(info.st_mode)==0o700)
        parts=PurePosixPath(name).parts
        for part in parts[:-1]:
            try: os.mkdir(part,0o700,dir_fd=d)
            except FileExistsError: pass
            d=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=d);fds.append(d)
            s=os.fstat(d);need(s.st_uid==os.getuid())
        out=os.open(parts[-1],os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode,dir_fd=d)
        offset=0
        while offset<len(data):
            n=os.write(out,data[offset:offset+262144]);need(n>0);offset+=n
        os.fsync(out);need(os.fstat(out).st_size==len(data));os.fsync(d)
    finally:
        failed=False
        for fd in ([out] if out is not None else [])+list(reversed(fds)):
            try:os.close(fd)
            except BaseException:failed=True
        need(not failed)

def verify_rows(root,rows):
    need(type(root) is str and re.fullmatch('/private/tmp/hermes-022-run-[a-f0-9]{32}',root) is not None)
    need(type(rows) is list and 0<len(rows)<=8192)
    seen=set();total=0
    for row in rows:
        need(type(row) is dict and set(row)=={'path','bytes','sha256','kind'} and relative(row['path'])
             and row['path'].casefold() not in seen and type(row['bytes']) is int and row['bytes']>=0)
        seen.add(row['path'].casefold());total+=row['bytes'];need(total<=1024**3)
        raw=read(root+'/'+row['path'],512*1024**2)
        need(len(raw)==row['bytes'] and hashlib.sha256(raw).hexdigest()==row['sha256'])
    return True
