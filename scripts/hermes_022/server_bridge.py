"""Official web_server lifecycle observer, not a substitute HTTP server.

Hooks only the bound module's build/start seams. Original startup, main_loop,
shutdown and auth all execute. A stop command sets the same Server.should_exit
used by Uvicorn. No product collector, auth or endpoint is patched.
"""
import asyncio
import inspect
from child_protocol import require, ready, stop, ack, finite, encode

class ServerBridge:
    def __init__(self, channel, grant, source, checkpoint, deadline, clock, sleep=asyncio.sleep):
        require(callable(checkpoint) and callable(clock) and callable(sleep) and finite(deadline))
        self.channel,self.grant,self.source=channel,grant,source
        self.checkpoint,self.deadline,self.clock,self.sleep=checkpoint,deadline,clock,sleep
        self.module=None;self.server=None;self.task=None;self.used=False
        self.startup=False;self.stopped=False;self.shutdown=False;self.error=None
        self.originals=None;self.wrappers=None;self.original_shutdown=None;self.wrapped_shutdown=None

    def check(self):
        require(self.error is None)
        if not self.clock()<self.deadline:
            self.error='deadline';require(False)
        self.checkpoint()

    def install(self,module,expected_path):
        require(not self.used);self.used=True
        require(getattr(module,'__file__',None)==expected_path)
        build=module._build_uvicorn_server;started=module._on_server_started
        require(callable(build) and callable(started))
        self.module=module;self.originals=(build,started)
        def wrapped_build(*args,**kwargs):
            self.check();require(self.server is None)
            config,server=build(*args,**kwargs)
            require(callable(server.shutdown) and inspect.iscoroutinefunction(server.shutdown))
            self.server=server;self.original_shutdown=server.shutdown
            async def wrapped_shutdown(*a,**k):
                require(not self.shutdown)
                try:
                    value=await self.original_shutdown(*a,**k)
                    self.checkpoint();self.shutdown=True;return value
                except BaseException:
                    self.error=self.error or 'shutdown';raise
            self.wrapped_shutdown=wrapped_shutdown;server.shutdown=wrapped_shutdown
            return config,server
        def wrapped_started(server,**kwargs):
            self.check();require(server is self.server and not self.startup and server.started is True)
            value=started(server,**kwargs) # all upstream post-bind effects remain guarded
            self.check();self.startup=True
            self.channel.write_once('ready.json',ready(self.grant,self.source))
            self.task=asyncio.get_running_loop().create_task(self.watch())
            return value
        self.wrappers=(wrapped_build,wrapped_started)
        module._build_uvicorn_server=wrapped_build;module._on_server_started=wrapped_started

    async def watch(self):
        try:
            while True:
                self.check()
                command=self.channel.read('command-1.json')
                if command is not None:
                    require(encode(command)==encode(stop(self.grant,self.source)))
                    self.checkpoint();self.stopped=True
                    self.channel.write_once('ack-1.json',ack(self.grant,self.source))
                    self.server.should_exit=True
                    return
                await self.sleep(min(.05,max(0,self.deadline-self.clock())))
        except BaseException:
            self.error=self.error or 'control'
            if self.server is not None:self.server.should_exit=True
            # Consume the task exception; a fixed failure survives even if the
            # upstream event-loop shutdown cancels this task.

    def finish(self):
        """Called only after the official synchronous main has returned."""
        error=self.error
        if not (self.startup and self.stopped and self.shutdown and self.task is not None
                and self.task.done() and not self.task.cancelled()):error=error or 'server'
        if self.task is not None and self.task.done() and not self.task.cancelled():
            try:self.task.result()
            except BaseException:error=error or 'control'
        try:
            require(self.module is not None and self.originals is not None and
                    (self.module._build_uvicorn_server,self.module._on_server_started)==self.wrappers)
            require(self.server is not None and self.server.shutdown is self.wrapped_shutdown)
            self.module._build_uvicorn_server,self.module._on_server_started=self.originals
            self.server.shutdown=self.original_shutdown
            self.checkpoint()
        except BaseException:error=error or 'guard'
        self.error=error
        return error
