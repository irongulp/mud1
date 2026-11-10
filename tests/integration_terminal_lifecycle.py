"""Focused native terminal lifecycle; capture first failure while DZ line is held.

Only the test fixture extends failure teardown for a bounded read-only CTY
census/SIMH device report. No terminal payloads, passwords or memory are captured.
"""
import argparse
import asyncio
from contextlib import redirect_stdout
import json
import logging
from pathlib import Path
import socket
import time
from unittest.mock import patch

from aiohttp.test_utils import TestServer

from server import gateway
from server.runtime import Runtime
from tests.browser_smoke import main as browser_smoke
from tools.deploy import install_image

ROOT=Path(__file__).resolve().parents[1]
STATE_CAPTURE_SECONDS=10
BETWEEN_SESSIONS_SECONDS=30


class Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages=[]
    def emit(self,record):
        self.messages.append(dict(level=record.levelname,message=record.getMessage()))


def native_state(runtime,output,evidence):
    deadline=time.monotonic()+STATE_CAPTURE_SECONDS
    try:
        status=runtime.command('systat',timeout=max(0,deadline-time.monotonic()))
        (output/'failure-systat.txt').write_text(status)
        evidence['census_completed']=True
    except Exception as error:
        evidence['census_error_type']=type(error).__name__
    console=runtime.scope.console
    console.deadline=deadline
    try:
        console.halt()
        status=console.command('show dz')
        (output/'failure-dz.txt').write_text(status)
        evidence['device_report_completed']=True
    except Exception as error:
        evidence['device_error_type']=type(error).__name__
    finally:
        if console.at_prompt:
            try:
                console.resume()
            except Exception as error:
                evidence['resume_error_type']=type(error).__name__
                runtime.booted=False  # Never send guest commands to an uncertain SCP.
                runtime.control_prompt=None
        console.deadline=None


async def exercise(runtime,output,report):
    original_wake=gateway.wake_monitor
    original_logout=gateway.logout_guest
    records=Capture()
    old_level=gateway.LOG.level
    gateway.LOG.setLevel(logging.INFO)
    gateway.LOG.addHandler(records)

    async def capture(reader,writer,phase,progress):
        if 'failure_evidence' in report: return
        evidence=dict(phase=phase,progress=dict(progress),line_open_before=not writer.is_closing(),
                      response=gateway.terminal_response_facts(reader))
        report['failure_evidence']=evidence
        try:
            await asyncio.to_thread(native_state,runtime,output,evidence)
        except Exception as error:
            evidence['capture_error_type']=type(error).__name__
        evidence['line_open_after']=not writer.is_closing()

    async def observed_wake(reader,writer,*,progress=None):
        progress={} if progress is None else progress
        started=time.monotonic()
        try:
            return await original_wake(reader,writer,progress=progress)
        except asyncio.CancelledError:
            # Ordinary browser closure during admission is not a timeout.
            if time.monotonic()-started>=gateway.CONNECT_TIMEOUT:
                await capture(reader,writer,'admission-timeout',progress)
            raise
        except (OSError,EOFError,asyncio.IncompleteReadError):
            await capture(reader,writer,'admission-error',progress)
            raise

    async def observed_logout(reader,writer,**kwargs):
        result=await original_logout(reader,writer,**kwargs)
        if not result:
            await capture(reader,writer,'logout-failure',{})
        return result

    try:
        with patch.object(gateway,'wake_monitor',observed_wake),patch.object(gateway,'logout_guest',observed_logout):
            async with TestServer(gateway.create_app(upstream_port=runtime.port,maintenance_file=None)) as server:
                report['phase']='first-browser-sessions'
                await browser_smoke(str(server.make_url('')).rstrip('/'),screenshot=output/'first.png')
                if 'failure_evidence' in report: raise RuntimeError('First browser lifecycle failed')
                report['phase']='running-gap'
                await asyncio.sleep(BETWEEN_SESSIONS_SECONDS)
                report['phase']='reused-browser-sessions'
                await browser_smoke(str(server.make_url('')).rstrip('/'),screenshot=output/'second.png')
                if 'failure_evidence' in report: raise RuntimeError('Reused browser lifecycle failed')
        if any(row['level'] in ('WARNING','ERROR') for row in records.messages):
            raise RuntimeError('Gateway lifecycle warning retained')
    finally:
        gateway.LOG.removeHandler(records)
        gateway.LOG.setLevel(old_level)
        (output/'gateway.json').write_text(json.dumps(records.messages,indent=2)+'\n')


def run(output,archive,executable):
    output.mkdir(mode=0o700)
    state=output/'machine'
    state.mkdir(mode=0o700)
    install_image(archive,json.loads((ROOT/'deploy/runtime.json').read_text()),state/'game')
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0))
        port=listener.getsockname()[1]
    runtime=Runtime(state,executable,port=port,monitor_scope=True,batch_preflight=True)
    report=dict(complete=False,phase='boot',personas='disposable ordinary smoke fixtures')
    failed=False
    with (output/'console.log').open('x') as console,redirect_stdout(console):
        try:
            runtime.boot()
            runtime.command('type sys:tty.ini')
            asyncio.run(exercise(runtime,output,report))
            report['phase']='shutdown'
        except Exception as error:
            failed=True
            report['error_type']=type(error).__name__
        finally:
            try: report['shutdown_clean']=runtime.stop()
            except Exception as error:
                report.update(shutdown_clean=False,shutdown_error_type=type(error).__name__)
            report['complete']=not failed and report['shutdown_clean'] and 'failure_evidence' not in report
            (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    if not report['complete']: raise RuntimeError('Native terminal lifecycle failed; inspect retained evidence')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--simh',type=Path,required=True)
    args=parser.parse_args()
    run(args.output.resolve(),args.archive.resolve(),args.simh.resolve())
