"""Fixed HTTP/WS observations; busy-state activation is NOT provided here.
No raw bodies or exception strings leave these projections. No authentication patch.
"""
import asyncio
from bounded_io import require,Refused,decode,port_valid,token_valid,native_connector,SilentLogger,MAX_BODY,close_socket

def native_exception_types():
    import websockets
    require(websockets.__version__=='15.0.1','binding')
    from websockets.exceptions import InvalidStatus,ConnectionClosed
    return InvalidStatus,ConnectionClosed

class PluginChecks:
    def __init__(self,port,budget,http,connector_factory=native_connector,exception_types=native_exception_types):
        require(port_valid(port) and http.port==port,'endpoint')
        self.port,self.budget,self.http=port,budget,http;self.connector_factory=connector_factory
        self.exception_types=exception_types;self.used=set();self.failed=False
    async def http_once(self,case,token=None):
        out={'schema':'plugin_http_observation_v1','case':case if case in ('auth_denied','auth_ok','busy') else 'unknown',
             'result':'FAIL','status':None,'bytes':0,'schema_seen':None,'error':None}
        try:
            require(not self.failed and case in ('auth_denied','auth_ok','busy'),'consumed')
            response=await self.http.get(case,token);status=response['status'];body=response['body']
            out.update(status=status,bytes=len(body))
            if case=='auth_denied':require(type(status) is int and status in (401,403),'protocol')
            elif case=='auth_ok':
                row=decode(body);require(status==200 and type(row) is dict
                    and type(row.get('api_schema_version')) is int and row['api_schema_version']==1,'protocol')
                out['schema_seen']=1
            else:require(status==503 and decode(body)=={'detail':'snapshot_unavailable'},'protocol')
            out['result']='EXPECTED_RESPONSE_ONLY'
        except BaseException:
            self.failed=True;out['error']='http'
        return out
    async def ws_once(self,case,token=None):
        out={'schema':'plugin_ws_observation_v1','case':case if case in ('auth_denied','auth_ok','busy') else 'unknown',
             'result':'FAIL','handshakes':0,'frames':0,'bytes':0,'http_status':None,'close_code':None,
             'schema_seen':None,'error':None,'cleanup_error':None}
        wire=None
        try:
            require(not self.failed and type(case) is str and case in ('auth_denied','auth_ok','busy') and case not in self.used,'consumed')
            require((token is None if case=='auth_denied' else token_valid(token)),'endpoint')
            self.used.add(case);invalid,closed=self.exception_types();connector=self.connector_factory()
            uri=f'ws://127.0.0.1:{self.port}/api/plugins/hermes-hud/events?locale=en'
            if token is not None:uri+='&token='+token
            left=self.budget.remaining()
            try:
                wire=await asyncio.wait_for(connector(uri,origin=f'http://127.0.0.1:{self.port}',proxy=None,
                    compression=None,open_timeout=left,close_timeout=2,max_size=MAX_BODY,max_queue=4,
                    ping_interval=None,user_agent_header=None,logger=SilentLogger()),left)
            except invalid as exc:
                self.budget.remaining();status=exc.response.status_code
                require(case=='auth_denied' and type(status) is int and status in (401,403),'protocol')
                out['http_status']=status
            if wire is not None:
                out['handshakes']=1;self.budget.remaining()
                try:
                    raw=await self.budget.wait(wire.recv)
                except closed as exc:
                    self.budget.remaining();code=exc.rcvd.code if exc.rcvd is not None else None
                    require(type(code) is int and code==(1008 if case=='auth_denied' else 1013 if case=='busy' else -1),'protocol')
                    out['close_code']=code
                else:
                    require(case=='auth_ok','protocol');row=decode(raw)
                    require(type(row) is dict and type(row.get('schema_version')) is int and row['schema_version']==1,'protocol')
                    out.update(frames=1,bytes=len(raw.encode() if type(raw) is str else raw),schema_seen=1)
            require((case=='auth_ok' and out['frames']==1) or (case=='busy' and out['close_code']==1013)
                    or (case=='auth_denied' and (out['http_status'] in (401,403) or out['close_code']==1008)),'protocol')
            out['result']='EXPECTED_RESPONSE_ONLY'
        except BaseException:
            self.failed=True;out['error']='websocket'
        finally:
            if wire is not None:
                if not await close_socket(wire,self.budget):self.failed=True;out['cleanup_error']='cleanup'
            if out['error'] is not None or out['cleanup_error'] is not None:out['result']='FAIL'
        return out
