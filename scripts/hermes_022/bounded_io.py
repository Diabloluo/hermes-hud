"""Bounded loopback adapters. Inert on import; no entry point or permission.

Response bytes stay in RAM. Caller supplies an already-bound owned listener
check; a caller boolean is not independent proof of listener ownership.
"""
import asyncio
import json
import math
import re

MAX_BODY=1048576
ERRORS={'budget','identity','endpoint','consumed','http','websocket','protocol','binding','cleanup'}
class Refused(ValueError):
    def __init__(self,code):super().__init__(code if type(code) is str and code in ERRORS else 'protocol')
def require(ok,code):
    if ok is not True:raise Refused(code) from None
def finite(x):return type(x) in (int,float) and abs(x)<=2**63-1 and math.isfinite(x)
def port_valid(x):return type(x) is int and 1024<=x<=65535 and x!=9119
def token_valid(x):return type(x) is str and re.fullmatch('[A-Za-z0-9_-]{32,256}',x) is not None

def decode(raw):
    require(type(raw) in (str,bytes) and 0<len(raw)<=MAX_BODY,'protocol')
    def pairs(items):
        out={}
        for k,v in items:require(k not in out,'protocol');out[k]=v
        return out
    def constant(_):raise Refused('protocol')
    try:
        text=raw.decode('utf-8') if type(raw) is bytes else raw
        require(len(text.encode())<=MAX_BODY,'protocol')
        return json.loads(text,object_pairs_hook=pairs,parse_constant=constant)
    except Exception:raise Refused('protocol') from None

class Budget:
    def __init__(self,clock,deadline,identity_check):
        self.clock,self.deadline,self.identity_check=clock,deadline,identity_check;self.last=None
    def remaining(self,cap=10):
        now=self.clock()
        require(finite(now) and finite(self.deadline) and 0<=now<self.deadline
                and (self.last is None or now>=self.last),'budget');self.last=now
        require(self.identity_check() is True,'identity')
        after=self.clock()
        require(finite(after) and now<=after<self.deadline,'budget');self.last=after
        return min(cap,self.deadline-after)
    async def wait(self,factory,cap=10):
        # Factory avoids creating an unawaited coroutine if precheck refuses.
        left=self.remaining(cap);value=await asyncio.wait_for(factory(),left)
        self.remaining(cap);return value

async def native_stream(port):
    require(port_valid(port),'endpoint')
    return await asyncio.open_connection('127.0.0.1',port,limit=16384)

class LoopbackHTTP:
    def __init__(self,port,budget,opener=native_stream):
        require(port_valid(port),'endpoint');self.port=port;self.budget=budget;self.opener=opener
        self.consumed=set();self.failed=False;self.cleanup_error=None
    async def get(self,case,token=None):
        paths={'cdp_list':'/json/list','auth_denied':'/api/plugins/hermes-hud/settings',
               'auth_ok':'/api/plugins/hermes-hud/settings','busy':'/api/plugins/hermes-hud/snapshot?locale=en'}
        require(type(case) is str and case in paths and not self.failed and case not in self.consumed,'consumed')
        require((token is None if case in ('cdp_list','auth_denied') else token_valid(token)),'endpoint')
        self.consumed.add(case);reader=writer=None;result=None
        try:
            self.budget.remaining()
            # Retain writer immediately: a failing post-connect check still closes it.
            left=self.budget.remaining()
            reader,writer=await asyncio.wait_for(self.opener(self.port),left)
            self.budget.remaining()
            head=f'GET {paths[case]} HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\nConnection: close\r\nAccept-Encoding: identity\r\n'
            if token is not None:head+='X-Hermes-Session-Token: '+token+'\r\n'
            writer.write((head+'\r\n').encode('ascii'))
            await self.budget.wait(writer.drain)
            raw=await self.budget.wait(lambda:reader.readuntil(b'\r\n\r\n'))
            require(type(raw) is bytes and len(raw)<=16384 and raw.endswith(b'\r\n\r\n'),'http')
            lines=raw[:-4].split(b'\r\n');require(len(lines)<=65,'http')
            require(re.fullmatch(rb'HTTP/1\.[01] [1-5][0-9]{2}(?: [\x20-\x7e]*)?',lines[0]) is not None,'http')
            status=int(lines[0].split(b' ')[1]);require(not 300<=status<400,'http')
            headers={}
            for line in lines[1:]:
                require(b':' in line and not line.startswith((b' ',b'\t')),'http')
                k,v=line.split(b':',1);k=k.lower();v=v.strip(b' \t')
                require(re.fullmatch(rb'[a-z0-9!#$%&\x27*+.^_`|~-]+',k) is not None and k not in headers
                        and all(32<=c!=127 for c in v),'http');headers[k]=v
            require(b'transfer-encoding' not in headers and b'content-encoding' not in headers,'http')
            length=headers.get(b'content-length',b'')
            require(re.fullmatch(rb'0|[1-9][0-9]{0,6}',length) is not None and int(length)<=MAX_BODY,'http')
            body=await self.budget.wait(lambda:reader.readexactly(int(length)))
            require(type(body) is bytes and len(body)==int(length),'http')
            # A declared Connection: close allows detecting extra response bytes.
            extra=await self.budget.wait(lambda:reader.read(1),cap=2)
            require(extra==b'','http');result={'status':status,'body':body}
        except BaseException as exc:
            self.failed=True
            if isinstance(exc,asyncio.CancelledError):raise
            code=exc.args[0] if type(exc) is Refused else 'http'
            raise Refused(code) from None
        finally:
            if writer is not None:
                try:
                    writer.close()
                    await self.budget.wait(writer.wait_closed,cap=2)
                except BaseException:self.cleanup_error='cleanup';self.failed=True
        require(self.cleanup_error is None,'cleanup')
        return result

def target_url(raw,port):
    """Only the sole about:blank page, never an arbitrary advertised URL."""
    require(port_valid(port),'endpoint');rows=decode(raw)
    require(type(rows) is list and len(rows)==1,'endpoint');row=rows[0]
    require(type(row) is dict and row.get('type')=='page' and row.get('url')=='about:blank','endpoint')
    ident=row.get('id');require(type(ident) is str and re.fullmatch('[A-Za-z0-9_-]{1,128}',ident) is not None,'endpoint')
    url=f'ws://127.0.0.1:{port}/devtools/page/{ident}'
    require(row.get('webSocketDebuggerUrl')==url,'endpoint')
    return url

class SilentLogger:
    def isEnabledFor(self,*args):return False
    def debug(self,*args,**kw):pass
    def info(self,*args,**kw):pass
    def warning(self,*args,**kw):pass
    def error(self,*args,**kw):pass
    def exception(self,*args,**kw):pass

def no_redirect_class(base):
    class SingleConnect(base):
        # Returning the original exception prevents every redirect while allowing
        # the private API observer to classify an actual 401/403 handshake.
        def process_redirect(self,exc):return exc
    return SingleConnect

async def close_socket(wire,budget):
    """Close only the retained connection, even after a failed identity check.
    No process signal; no new connection. Expired cleanup stays a failure.
    """
    try:
        now=budget.clock()
        require(finite(now) and finite(budget.deadline) and 0<=now<budget.deadline
                and (budget.last is None or now>=budget.last),'budget')
        await asyncio.wait_for(wire.close(),min(2,budget.deadline-now))
        after=budget.clock();require(finite(after) and now<=after<budget.deadline,'budget')
        return True
    except BaseException:
        try:wire.transport.abort()
        except BaseException:pass
        return False

def native_connector():
    # Import only in future authorized execution, not during current tests.
    import websockets
    require(websockets.__version__=='15.0.1','binding')
    from websockets.asyncio.client import connect
    return no_redirect_class(connect)

class BrowserSocket:
    def __init__(self,port,budget,connector_factory=native_connector):
        require(port_valid(port),'endpoint');self.port=port;self.budget=budget
        self.connector_factory=connector_factory;self.used=False;self.connection=None;self.cleanup_error=None
    async def open(self,url):
        require(not self.used,'consumed')
        require(type(url) is str and re.fullmatch('ws://127\\.0\\.0\\.1:'+str(self.port)+'/devtools/page/[A-Za-z0-9_-]{1,128}',url) is not None,'endpoint')
        self.used=True
        try:
            connector=self.connector_factory();left=self.budget.remaining()
            self.connection=await asyncio.wait_for(connector(url,proxy=None,compression=None,
                open_timeout=left,close_timeout=2,max_size=MAX_BODY,max_queue=4,write_limit=32768,
                ping_interval=None,user_agent_header=None,logger=SilentLogger()),left)
            self.budget.remaining();return self.connection
        except BaseException as exc:
            if self.connection is not None:
                if not await close_socket(self.connection,self.budget):self.cleanup_error='cleanup'
            if isinstance(exc,asyncio.CancelledError):raise
            raise Refused('websocket') from None
