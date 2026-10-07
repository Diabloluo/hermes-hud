"""Minimal fixed-file helpers. Importing does not read files or start processes."""
import hashlib
import json
import math
from pathlib import Path
import re

from boundary_policy import BoundaryRefused

HEX=re.compile(r'^[0-9a-f]{64}$')


def require(ok,code):
    if ok is not True:raise BoundaryRefused(code) from None


def number(value):
    return type(value) in (int,float) and math.isfinite(value)


def bounded(path,maximum=2*1024*1024):
    path=Path(path)
    require(path.is_absolute() and path.resolve()==path and not path.is_symlink()
            and path.is_file() and path.stat().st_size<=maximum,'file_boundary')
    data=path.read_bytes()
    require(len(data)<=maximum,'file_boundary')
    return data


def digest(path):
    return hashlib.sha256(bounded(path,64*1024*1024)).hexdigest()


def object_pairs(pairs):
    out={}
    for key,value in pairs:
        require(key not in out,'control')
        out[key]=value
    return out


def read(path,maximum=65536):
    return json.loads(bounded(path,maximum),object_pairs_hook=object_pairs)


def atomic_bytes(path,data):
    path=Path(path)
    require(path.parent.resolve()==path.parent and not path.is_symlink()
            and type(data) is bytes and len(data)<=65536,'control')
    tmp=path.with_suffix(path.suffix+'.pending')
    with tmp.open('xb') as stream:stream.write(data)
    tmp.replace(path)


def atomic(path,row):
    atomic_bytes(path,(json.dumps(row,sort_keys=True,allow_nan=False)+'\n').encode())
