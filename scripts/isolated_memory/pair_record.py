"""Owned aggregate-only bytes, bounded and atomically published. No raw logs."""
import json
from pathlib import Path
from common import require,bounded
MAXIMUM=2*1024*1024
def encode(x):return (json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
def publish(path,data):
    path=Path(path)
    require(type(data) is bytes and len(data)<=MAXIMUM and path.parent.resolve()==path.parent
            and not path.is_symlink(),'seal')
    tmp=path.with_suffix(path.suffix+'.pending')
    with tmp.open('xb') as f:f.write(data)
    tmp.replace(path)
def rows(path):
    data=bounded(path,MAXIMUM)
    result=[json.loads(x) for x in data.splitlines()]
    require(0<len(result)<=1600,'sample')
    return result
