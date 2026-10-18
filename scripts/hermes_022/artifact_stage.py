"""Pinned archive intake and fresh-directory materialization; no runtime launch.

Network methods are callable only explicitly. No CLI, retry, environment token,
shell extraction or automatic archive download. Tests use RAM archive bytes.
"""
import hashlib
import gzip
import io
import lzma
import os
from pathlib import PurePosixPath
import re
import stat
import tarfile
import time
import urllib.request
import urllib.parse

MAX_ARCHIVE = 128*1024**2
MAX_EXPANDED = 1024**3
MAX_FILE = 512*1024**2
MAX_MEMBERS = 8192
MAX_TAR = MAX_EXPANDED + 16*1024**2
ERRORS = frozenset(("binding","url","transport","budget","archive","path","limit","stage"))


class Refused(ValueError):
    def __init__(self, code):
        super().__init__(code if code in ERRORS else "binding")


def need(ok, code):
    if ok is not True:
        raise Refused(code) from None


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def relative(name):
    return (type(name) is str and 0<len(name)<=2048 and not name.startswith("/")
            and str(PurePosixPath(name))==name and name!="."
            and ".." not in PurePosixPath(name).parts
            and all(32<=ord(c)<127 for c in name) and "\\" not in name)


def https_url(url, hosts):
    try:
        u=urllib.parse.urlsplit(url)
        return (type(url) is str and url.isascii() and len(url)<=4096
                and not any(ord(c)<=32 or ord(c)==127 for c in url)
                and u.scheme=="https" and u.hostname in hosts and u.port in (None,443)
                and u.username is None and u.password is None and not u.fragment)
    except Exception:
        return False


class BoundRedirect(urllib.request.HTTPRedirectHandler):
    """TLS-only redirects within an explicitly bound public artifact host set."""
    def __init__(self, hosts): self.hosts=hosts;self.count=0
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.count+=1
        need(self.count<=3 and https_url(newurl,self.hosts),"url")
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def download(url, expected_sha, hosts, deadline, *, clock=time.monotonic, opener=None):
    """One open, no retries, capped RAM transport. Caller must authorize first.

    The monotonic deadline covers chunk processing; socket timeout bounds an
    individual blocked read. This is not a hard process-wide wall-clock kill.
    No credentials/proxy environment are inherited by the default opener.
    """
    try:
        need(type(hosts) is tuple and 0<len(hosts)<=8 and
             all(type(x) is str and re.fullmatch(r"[a-z0-9.-]+",x) for x in hosts),"url")
        need(https_url(url,hosts),"url")
        need(type(expected_sha) is str and re.fullmatch("[a-f0-9]{64}",expected_sha) is not None,"binding")
        need(type(deadline) in (float,int) and 0<deadline-clock()<=1800,"budget")
        if opener is None:
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),BoundRedirect(hosts))
        request=urllib.request.Request(url,headers={"Accept-Encoding":"identity","User-Agent":"HUD-022-pinned-intake"})
        with opener.open(request,timeout=min(20,deadline-clock())) as response:
            need(response.status==200 and https_url(response.geturl(),hosts),"transport")
            encoding=response.headers.get("Content-Encoding")
            need(encoding in (None,"identity"),"transport")
            length=response.headers.get("Content-Length")
            need(length is None or (type(length) is str and re.fullmatch("[0-9]{1,10}",length) is not None
                                   and 0<int(length)<=MAX_ARCHIVE),"limit")
            chunks=[];total=0
            while True:
                need(clock()<deadline,"budget")
                block=response.read(min(262144,MAX_ARCHIVE-total+1))
                need(type(block) is bytes,"transport")
                if not block:break
                total+=len(block);need(total<=MAX_ARCHIVE,"limit");chunks.append(block)
            need(clock()<deadline and (length is None or total==int(length)),"transport")
            raw=b"".join(chunks)
        need(total>0 and digest(raw)==expected_sha,"binding")
        return raw
    except Refused:
        raise
    except Exception:
        raise Refused("transport") from None


def unpack(raw, expected_sha, prefix):
    """Verify archive bytes, then flatten bounded internal links into file copies.

    No extract()/extractall(), no on-disk ZIP/TAR and no special-file creation.
    Symlink paths and hardlink paths are resolved only against archive entries;
    absolute, escaping, dangling, cyclic and directory links are rejected.
    The expanded-byte limit counts copied link payloads as well as originals.
    """
    try:
        need(type(raw) is bytes and 0<len(raw)<=MAX_ARCHIVE and digest(raw)==expected_sha,"binding")
        need(relative(prefix) and "/" not in prefix,"path")
        # Bound decompression before tarfile sees PAX/long-name headers. A
        # compressed extended header must not evade per-member limits.
        if raw.startswith(b'\xfd7zXZ\x00'):
            decoder=lzma.LZMADecompressor(format=lzma.FORMAT_XZ,memlimit=64*1024**2)
            decoded=decoder.decompress(raw,max_length=MAX_TAR+1)
            need(len(decoded)<=MAX_TAR,'limit')
            need(decoder.eof and not decoder.unused_data,'archive')
        else:
            need(raw.startswith(b'\x1f\x8b'),'archive')
            with gzip.GzipFile(fileobj=io.BytesIO(raw),mode="rb") as compressed:
                decoded=compressed.read(MAX_TAR+1)
        need(len(decoded)<=MAX_TAR,"limit")
        rows={};aliases=set();total=0
        with tarfile.open(fileobj=io.BytesIO(decoded),mode="r:") as archive:
            for member in archive:
                name=member.name.rstrip("/")
                need(relative(name) and (name==prefix or name.startswith(prefix+"/")),"path")
                need(name.casefold() not in aliases and len(rows)<MAX_MEMBERS,"archive")
                aliases.add(name.casefold())
                need(member.mode & 0o7000 == 0,"archive")
                # GitHub source tarballs may carry the commit in a global
                # PAX comment. Other extended headers require explicit work,
                # not automatic permission to alter paths or file shapes.
                need(not member.pax_headers or
                     (set(member.pax_headers)=={"comment"}
                      and re.fullmatch("[a-f0-9]{40}",member.pax_headers["comment"]) is not None
                      and prefix.endswith("-"+member.pax_headers["comment"])),"archive")
                need(member.isdir() or member.isfile() or member.issym() or member.islnk(),"archive")
                need(type(member.size) is int and 0<=member.size<=MAX_FILE,"limit")
                # Files cannot replace directory parents, regardless of tar order.
                row={"type":"directory" if member.isdir() else "file","mode":0o755 if member.mode&0o111 else 0o644}
                if member.isfile():
                    total+=member.size;need(total<=MAX_EXPANDED,"limit")
                    stream=archive.extractfile(member);need(stream is not None,"archive")
                    with stream: data=stream.read(member.size+1)
                    need(len(data)==member.size,"archive");row["data"]=data
                elif member.issym() or member.islnk():
                    target=member.linkname
                    need(type(target) is str and 0<len(target)<=2048 and not target.startswith("/")
                         and "\\" not in target and all(32<=ord(c)<127 for c in target),"path")
                    parts=list(PurePosixPath(name).parent.parts) if member.issym() else []
                    for component in target.split("/"):
                        if component in ("", "."):continue
                        if component=="..":
                            need(len(parts)>1,"path");parts.pop()
                        else:parts.append(component)
                    dest="/".join(parts)
                    need(dest.startswith(prefix+"/"),"path");row["target"]=dest
                else:
                    need(member.size==0,"archive")
                rows[name]=row
        need(rows and (prefix not in rows or rows[prefix]["type"]=="directory"),"archive")
        for name in rows:
            for parent in PurePosixPath(name).parents:
                if str(parent) in rows:need(rows[str(parent)]["type"]=="directory","path")
        result=[];expanded=0
        for name,row in rows.items():
            if row["type"]=="directory":continue
            visited={name};target=row
            while "target" in target:
                link=target["target"]
                need(link in rows and link not in visited and len(visited)<64,"archive")
                visited.add(link);target=rows[link]
            need(target["type"]=="file" and "data" in target,"archive")
            data=target["data"];expanded+=len(data);need(expanded<=MAX_EXPANDED,"limit")
            rel=name[len(prefix)+1:];need(relative(rel),"path")
            result.append({"path":rel,"data":data,"mode":target["mode"],"sha256":digest(data),
                           "materialized_link":len(visited)>1})
        need(bool(result),"archive")
        return result
    except Refused:
        raise
    except Exception:
        raise Refused("archive") from None


def stage(root, slot, files):
    """Create a new slot below an existing owned root via retained directory FDs.

    Failed or partially written slots are retained, never reused/overwritten or
    recursively removed. A caller must preserve failure and not continue launch.
    """
    dirs=[];fd=None
    try:
        need(type(root) is str and re.fullmatch("/private/tmp/hermes-022-run-[a-f0-9]{32}",root) is not None,"path")
        need(slot in ("sdk","bootstrap","product","tool"),"path")
        need(type(files) is list and 0<len(files)<=MAX_MEMBERS,"limit")
        names=set();total=0
        for row in files:
            need(type(row) is dict and set(row)=={"path","data","mode","sha256","materialized_link"},"binding")
            need(relative(row["path"]) and row["path"].casefold() not in names,"path")
            need(type(row["data"]) is bytes and len(row["data"])<=MAX_FILE
                 and digest(row["data"])==row["sha256"] and type(row["mode"]) is int
                 and row["mode"] in (0o644,0o755) and type(row["materialized_link"]) is bool,"binding")
            names.add(row["path"].casefold());total+=len(row["data"]);need(total<=MAX_EXPANDED,"limit")
        for row in files:
            need(all(str(parent).casefold() not in names for parent in PurePosixPath(row["path"]).parents),"path")
        current=os.open("/",os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW);dirs.append(current)
        for component in PurePosixPath(root).parts[1:]:
            current=os.open(component,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=current);dirs.append(current)
        root_stat=os.fstat(current)
        need(root_stat.st_uid==os.getuid() and stat.S_IMODE(root_stat.st_mode)==0o700,"stage")
        os.mkdir(slot,0o700,dir_fd=current)
        current=os.open(slot,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=current);dirs.append(current)
        bydir={".":current};result=[]
        for row in files:
            parts=PurePosixPath(row["path"]).parts;directory=current;prefix=[]
            for part in parts[:-1]:
                prefix.append(part);key="/".join(prefix)
                if key not in bydir:
                    os.mkdir(part,0o700,dir_fd=directory)
                    child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=directory)
                    dirs.append(child);bydir[key]=child
                directory=bydir[key]
            fd=os.open(parts[-1],os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=directory)
            view=memoryview(row["data"])
            while view:
                written=os.write(fd,view);need(written>0,"stage");view=view[written:]
            os.fsync(fd);os.fchmod(fd,row["mode"]);os.close(fd);fd=None
            result.append({"path":slot+"/"+row["path"],"bytes":len(row["data"]),"sha256":row["sha256"],
                           "materialized_link":row["materialized_link"]})
        return result
    except Refused:
        raise
    except Exception:
        raise Refused("stage") from None
    finally:
        failed=False
        for handle in ([fd] if fd is not None else [])+list(reversed(dirs)):
            try:os.close(handle)
            except Exception:failed=True
        if failed:raise Refused("stage") from None
