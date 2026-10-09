"""Build/test the hours-only patch on a stopped external lifecycle fixture."""
import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import re
import shutil
import socket
import time
from unittest.mock import patch

from tools.inspect_game import NativeInspector
from tools.prepare import always_open_library
from tools.persona_writes import isolated_writer
from tools.serve_external import source_stopped, protect_bridge_terminals
from server.gateway import create_app
from server.external_bootstrap import ExternalBootstrap
from aiohttp.test_utils import TestServer
from tests.integration_storage_bridge import ROOT,private_emulator,BRIDGE_LINES
from tests.integration_persona_writes import enable_writes
from tests.integration_external_creation import CreationHub
from tests.integration_external_local import browser_check
from tests.mariadb_fixture import LocalMariaDb
from tools.audit_archwizards import MAX_BOOT_ATTEMPTS
from tests.integration_provisioning import require,source_hashes

DATA_BASE=0o520000
MARKER_BASE=0o140


def rendered(text): return '\n'.join(line.expandtabs(8).rstrip() for line in text.splitlines()).strip()


def build(native,output):
    native.command('assign dsk: bcl:'); native.command('set tty no altmode')
    original=native.command('type mudlib.bcl').replace('\r','').split('\n',1)[1].rsplit('\n.',1)[0]
    desired=always_open_library(original.encode('ascii')).decode('ascii')
    native.command('r teco',b'\n*')
    edit=('ERmudlib.bcl\x1bEWx24lib.bcl\x1bY'
          'Nand timeok(low)=\x1b0L.UASand overload(low)=\x1b0LQA,.K'
          'I// Local 24/7 build: preserve HOURS data and the original load checks.\r'
          'and timeok(low)=demo\\/~overload(numbargs()->low, low1)\r\x1bEX\x1b\x1b')
    native.connection.write(edit.encode('ascii')); native.receive(b'\n.'); native.at_monitor=True
    actual=native.command('type x24lib.bcl').replace('\r','').split('\n',1)[1].rsplit('\n.',1)[0]
    require(rendered(actual)==rendered(desired),'Hours-only edit differs from generated patch')
    (output/'MUDLIB-always-open.BCL').write_text(desired)
    native.command('r bcpl',b'\n*')
    result=native.command('x24lib/o',b'\n*')
    (output/'compile.txt').write_text(result)
    require(not re.search(r'\([WE]\d+-\d+\)|undefined global|error',result,re.I),'Availability compilation failed')
    native.connection.write(b'\x1a'); native.receive(b'\n.'); native.at_monitor=True
    native.command('copy xhrs.exe=mud.exe')
    native.command('r link',b'\n*'); native.command(f'/set:.low.:{MARKER_BASE:o}',b'\n*')
    counters=native.command('roboot,mud0,mud1,mud2,mud3,mud4,mud5,mud6,mud7,mud8,x24lib,mboots,xlstate/counter',b'\n*')
    (output/'link-counters.txt').write_text(counters)
    values=re.findall(r'\.HIGH\.\s+([0-7]+)',counters)
    require(values and int(values[-1],8)<DATA_BASE,'Availability code overlaps DBASE')
    native.command(f'/set:.high.:{DATA_BASE:o}',b'\n*'); native.command('dbadat/g')
    native.command('ssave x24mud')
    native.command('run x24mud',b'MUD saved'); native.receive(b'\n.'); native.at_monitor=True
    native.command('protect mud.exe<055>')


def boot(directory,ports,hour='030000'):
    for attempt in range(MAX_BOOT_ATTEMPTS):
        machine=private_emulator(directory,ports,reuse=True)
        send=machine.child.send
        def clock(text): return send(hour+'\r' if text=='030000\r' else text)
        machine.child.send=clock
        try:
            machine.boot(); machine.child.send=send; machine.command('daytime'); return machine
        except Exception:
            machine.child.send=send; machine.stop()
            if attempt+1==MAX_BOOT_ATTEMPTS: raise


def shutdown(machine):
    machine.command('r opr','OPR>'); machine.child.send('set ksys now\r')
    machine.child.expect_exact('KSYS processing completed',timeout=120)


def run(output,source):
    output.mkdir(mode=0o700)
    require(source_stopped(source/'guest.dsk'),'Availability source must be stopped')
    directory=output/'machine'; directory.mkdir(mode=0o700)
    shutil.copyfile(source/'guest.dsk',directory/'guest.dsk')
    ports={}
    with ExitStack() as reservations:
        for line in BRIDGE_LINES:
            connection=reservations.enter_context(socket.socket()); connection.bind(('127.0.0.1',0))
            ports[line]=connection.getsockname()[1]
    report={'complete':False}; original=source_hashes(); machine=None
    try:
        machine=boot(directory,ports)
        protect_bridge_terminals(machine)
        with NativeInspector(machine.port) as native:
            build(native,output)
        shutdown(machine); machine.stop(); machine=None
        compiled=output/'compiled'; compiled.mkdir(mode=0o700)
        shutil.copyfile(directory/'guest.dsk',compiled/'guest.dsk')
        machine=boot(directory,ports,'151900')
        require('STOMPR' not in machine.command('systat'),'Initializer still active')
        with LocalMariaDb(output/'db',column_schema=True) as database:
            config=enable_writes(database,allow_create=True,allow_delete=True)
            with isolated_writer(config) as store,CreationHub(machine,ports,store,database) as hub:
                import asyncio
                async def check():
                    async with TestServer(create_app(upstream_port=machine.port,session_bootstrap=ExternalBootstrap())) as server:
                        await browser_check(str(server.make_url('/')).rstrip('/'),'Allday','labproof',True,output)
                asyncio.run(check())
                require(not hub.errors,'Out-of-hours bridge failed')
            report['out_of_hours_browser_save_password']=True
        shutdown(machine)
        require(source_hashes()==original,'Original source changed')
        report.update(complete=True,boot_time='Friday 15:19',source_unchanged=True)
        print('Always-open external fixture verified:',directory,flush=True)
    finally:
        (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
        if machine is not None: machine.stop()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'runtime'/f'external-always-open-{time.time_ns()}')
    parser.add_argument('--prepared-runtime',type=Path,default=ROOT/'runtime/external-lifecycle-green/machine-1')
    args=parser.parse_args(); run(args.output.resolve(),args.prepared_runtime.resolve())
