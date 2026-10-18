"""Parent-side retained ready/stop/terminal verification with actual handle exit."""
from child_protocol import require, ready, stop, ack, encode, verify_terminal, read_terminal
from host_session import run

class ChildChannel:
    def __init__(self,transport,grant,source):
        ready(grant,source)
        self.transport,self.grant,self.source=transport,grant,source
        self.used=False;self.ready_seen=False;self.stop_sent=False

    def ready(self):
        self.transport.verify_parent_namespace()
        row=self.transport.read('ready.json')
        if row is None:return False
        require(encode(row)==encode(ready(self.grant,self.source)))
        self.ready_seen=True;return True

    async def stop(self):
        require(not self.stop_sent)
        self.stop_sent=True
        self.transport.verify_parent_namespace()
        self.transport.write_once('command-1.json',stop(self.grant,self.source))

    def terminal(self,exit_code):
        require(self.ready_seen and self.stop_sent)
        self.transport.verify_parent_namespace()
        require(encode(self.transport.read('ack-1.json'))==encode(ack(self.grant,self.source)))
        return verify_terminal(self.transport.read('terminal.json'),self.grant,self.source,exit_code)

async def run_sealed(parent,channel,port,token,deadline,source_check,*,checks_factory=None):
    require(not channel.used);channel.used=True
    row=None;closed=False
    try:
        require(source_check()==channel.source)
        row=await run(parent,port,token,deadline,source_check,channel.stop,
                      checks_factory=checks_factory,child_ready=channel.ready)
        row['child_record']=None
        try:
            channel.transport.verify_parent_namespace()
            row['child_record']=read_terminal(channel.transport.read('terminal.json'),channel.grant,channel.source)
        except BaseException:pass
        if row['result']=='HTTP_WS_AND_EXIT_OBSERVED_NOT_ACCEPTANCE':
            try:
                require(channel.terminal(row['cleanup']['exit_code']))
                row['child_seal_verified']=True
            except BaseException:row['result']='FAIL';row['error']='child_terminal'
    except BaseException:
        row={'schema':'hermes_0222_sealed_session_v1','result':'FAIL','error':'child_channel',
             'child_seal_verified':False,'native_acceptance':False,'memory':'WARN_NOT_ACCEPTED','public_release':'BLOCK'}
    finally:
        try:channel.transport.close();closed=True
        except BaseException:pass
    if not closed:row['result']='FAIL';row['error']='channel_close'
    if row['result']=='HTTP_WS_AND_EXIT_OBSERVED_NOT_ACCEPTANCE':
        row['result']='SEALED_SHORT_SESSION_RECORD_ONLY'
    row['parent_channel_closed']=closed
    return row
