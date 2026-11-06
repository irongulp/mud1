"""Native terminal admission across initializer intervals; never enters a persona."""
import argparse
import asyncio
from contextlib import redirect_stdout
import json
import logging
from pathlib import Path
import socket
import time
from unittest.mock import patch

from aiohttp import ClientSession, WSMsgType
from aiohttp.test_utils import TestServer

from server import gateway
from server.runtime import Runtime
from tools.deploy import install_image

ROOT=Path(__file__).resolve().parents[1]
ATTEMPT_OFFSETS=(0,10,20,45,65,85,105,125)
ADMISSION_TIMEOUT=20
CLEANUP_TIMEOUT=12
TRACE_BYTES=65536


class Trace:
    def __init__(self,limit=TRACE_BYTES):
        self.start=time.monotonic()
        self.limit=limit
        self.size=0
        self.truncated=False
        self.events=[]

    def record(self,direction,data):
        available=self.limit-self.size
        if len(data)>available: self.truncated=True
        data=data[:available]
        if data:
            self.events.append(dict(seconds=time.monotonic()-self.start,direction=direction,hex=data.hex()))
            self.size+=len(data)


async def admit_once(socket):
    async def receive():
        text=''
        while 'By what name shall I call you?' not in text:
            message=await socket.receive()
            if message.type!=WSMsgType.TEXT:
                raise RuntimeError('Browser closed before admission')
            text=(text+message.data)[-4096:]
    await asyncio.wait_for(receive(),ADMISSION_TIMEOUT)


async def exercise(runtime,report,trace):
    class ObservedWriter(gateway.SimhWriter):
        def write(self,data):
            trace.record('tx',data.encode('ascii'))
            return super().write(data)
    class ObservedClient(gateway.SimhClient):
        _writer_factory_encoding=ObservedWriter
        def data_received(self,data):
            trace.record('rx',data)
            return super().data_received(data)
    with patch.object(gateway,'SimhClient',ObservedClient):
        async with TestServer(gateway.create_app(upstream_port=runtime.port,maintenance_file=None)) as server,ClientSession() as client:
            start=time.monotonic()
            for offset in ATTEMPT_OFFSETS:
                await asyncio.sleep(max(0,start+offset-time.monotonic()))
                attempt=dict(offset=offset,admitted=False)
                report['attempts'].append(attempt)
                async with client.ws_connect(server.make_url('/terminal')) as websocket:
                    await admit_once(websocket)
                    attempt['admitted']=True
                deadline=time.monotonic()+CLEANUP_TIMEOUT
                while True:
                    async with client.get(server.make_url('/internal/maintenance')) as response:
                        state=await response.json()
                    if state['sessions']==0: break
                    if time.monotonic()>=deadline: raise TimeoutError('Gateway cleanup did not finish')
                    await asyncio.sleep(.1)


def run(output,archive,executable):
    output.mkdir(mode=0o700)
    state=output/'machine'
    state.mkdir(mode=0o700)
    install_image(archive,json.loads((ROOT/'deploy/runtime.json').read_text()),state/'game')
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0))
        port=listener.getsockname()[1]
    runtime=Runtime(state,executable,port=port)
    report=dict(complete=False,phase='boot',attempts=[],personas_created=0)
    trace=Trace()
    failure=None
    handler=logging.FileHandler(output/'gateway.log')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    level=gateway.LOG.level
    gateway.LOG.setLevel(logging.INFO)
    gateway.LOG.addHandler(handler)
    with (output/'console.log').open('x') as console,redirect_stdout(console):
        try:
            runtime.boot()
            runtime.command('systat')
            runtime.command('type sys:tty.ini')
            report['phase']='terminal-reuse'
            asyncio.run(exercise(runtime,report,trace))
            report['phase']='completed-admissions'
        except Exception as error:
            failure=error
            report['error_type']=type(error).__name__
        finally:
            # No terminal-reconfiguration, recovery login, or second admission
            # after failure. CTY remains separate from the failed DZ terminal.
            if runtime.booted:
                try: runtime.command('systat')
                except Exception as error: report['census_error_type']=type(error).__name__
            try: report['shutdown_clean']=runtime.stop()
            except Exception as error:
                report.update(shutdown_clean=False,shutdown_error_type=type(error).__name__)
            report['complete']=failure is None and report.get('shutdown_clean',False)
            report['trace_truncated']=trace.truncated
            (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
            # Fixture never sends names/passwords/game commands, only native
            # setup and cleanup. Do not reuse this capture for player sessions.
            (output/'admission-trace.json').write_text(json.dumps(trace.events,indent=2)+'\n')
            gateway.LOG.removeHandler(handler)
            gateway.LOG.setLevel(level)
            handler.close()
    if not report['complete']: raise RuntimeError('Native terminal reuse failed; inspect evidence')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--simh',type=Path,required=True)
    args=parser.parse_args()
    run(args.output.resolve(),args.archive.resolve(),args.simh.resolve())
