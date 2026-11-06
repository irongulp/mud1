"""Native x86 AlmaLinux acceptance for opt-in external installation/cutover."""
import argparse
import asyncio
import io
import json
from pathlib import Path
import re
import subprocess
import time

from tests.deployment_http import fixture_client
from tests.integration_web import Browser
from tools.persona_protocol import MAX_NAME_LENGTH

ROOT=Path(__file__).resolve().parents[1]
MAX_SHUTDOWN_CYCLES=3
MAX_DIAGNOSTIC_IDLE_SECONDS=660


def native_fixture_name(report):
    name=report.get('player_name')
    if (report.get('complete') is not True or not isinstance(name,str)
            or not re.fullmatch(rf'[A-Za-z]{{1,{MAX_NAME_LENGTH}}}',name)):
        raise ValueError('Cutover requires a completed native acceptance report with its verified persona name')
    return name


def invoke(container,*command,log=None):
    if command and command[0]=='sudo': command=command[1:]
    result=subprocess.run(['docker','exec','-w','/checkout',container,*map(str,command)],capture_output=True,text=True,timeout=3600)
    text=re.sub(r'(?m)^(Richard|Roy|Brian|Ronan|Friday|Yawn|Debugger): [a-z0-9]{8} —',r'\1: [redacted] —',result.stdout+result.stderr)
    if log is not None: log.write_text(text)
    if result.returncode: raise AssertionError(text)
    return text


async def login(url,name,password,creating=False):
    async with fixture_client(url) as client:
        socket=await client.ws_connect(url+'/terminal'); transcript=io.StringIO(); player=Browser(socket,name,transcript)
        try:
            await player.expect('By what name shall I call you?'); await player.expect('*'); await player.send(name)
            if creating:
                await player.expect('What sex do you wish to be?'); await socket.send_str('m'); await player.expect('letters, please.')
            else: await player.expect("what's the password?")
            await player.expect('*'); await player.send(password)
            await player.expect(('Hello, ' if creating else 'Hello again, ')+name+'!'); await player.expect('\n*')
            if creating:
                await player.send('save'); await player.expect('saved.'); await player.expect('\n*')
            await player.send('score'); await player.expect('Score to date:'); await player.expect('\n*')
            await player.send('quit'); await player.expect('\n.')
            return transcript.getvalue().replace(password,'[redacted]')
        except Exception as error:
            # This fixture has one declared disposable password. Capture the
            # native admission result for diagnosis, never an operator password.
            raise AssertionError('Browser fixture failed: '+transcript.getvalue().replace(password,'[redacted]')) from error
        finally: await socket.close()


def enable_shutdown_diagnostics(container,warm_batch=False):
    dropin = ('[Service]\nExecStart=\n'
              'ExecStart=/opt/mud86/current/.venv/bin/python -u -m tools.batcon_service '
              '--state /var/lib/mud86 --simh ${SIMH_BIN}\n')
    if warm_batch: dropin+='Environment=MUD86_BATCON_WARMUP=1\nRestart=no\n'
    script = ('from pathlib import Path; '
              'p=Path("/etc/systemd/system/mud86-runtime.service.d/shutdown-diagnostics.conf"); '
              'p.parent.mkdir(parents=True,exist_ok=True); p.write_text('+repr(dropin)+')')
    invoke(container,'python3.12','-c',script)


def shutdown_cycles(container,url,name,password,count,observations,idle_seconds=0):
    if not 1 <= count <= MAX_SHUTDOWN_CYCLES: raise ValueError('Shutdown probe requires one to three cycles')
    if not 0 <= idle_seconds <= MAX_DIAGNOSTIC_IDLE_SECONDS: raise ValueError('Diagnostic idle bound exceeded')
    if idle_seconds: time.sleep(idle_seconds)
    for index in range(count):
        asyncio.run(login(url,name,password))
        invoke(container,'systemctl','stop','mud86-runtime.service')
        marker=json.loads(invoke(container,'python3.12','-c',
            'from pathlib import Path; print(Path("/var/lib/mud86/shutdown.json").read_text())'))
        observation=dict(cycle=index+1,clean=isinstance(marker,dict) and marker.get('clean') is True)
        observations.append(observation)
        if not observation['clean']: raise AssertionError('Native cycle shutdown was not clean; no restart allowed')
        if index+1<count: invoke(container,'mud86ctl','start')


def run(container,url,fresh,native_url=None,shutdown_diagnostics=False,cycles=0,warm_batch=False,idle_seconds=0):
    if not 0 <= idle_seconds <= MAX_DIAGNOSTIC_IDLE_SECONDS or (idle_seconds and not cycles):
        raise ValueError('Diagnostic idle requires bounded shutdown cycles')
    output=ROOT/'runtime'/('external-deployment-'+container); output.mkdir(mode=0o700,exist_ok=True)
    report={'complete':False,'fresh_external':fresh}
    try:
        if shutdown_diagnostics or warm_batch: enable_shutdown_diagnostics(container,warm_batch)
        name='Freshsql' if fresh else native_fixture_name(json.loads(
            (ROOT/'runtime'/('deployment-'+container)/'report.json').read_text()))
        if not fresh:
            asyncio.run(login(native_url or url,name,'testpass'))
            before=json.loads(invoke(container,'mud86ctl','persona',name,'--json'))
            assert before['personas'][0]['password_set'], 'Native cutover fixture was not saved'
        command=['bash','/checkout/setup.sh','--domain','mud.etimbo.com','--http-only','--image','/artifacts/mud86-runtime.tar.gz','--persona-storage','mariadb']
        invoke(container,*command,log=output/'install.log')
        (output/'login.log').write_text(asyncio.run(login(url,name,'testpass',fresh)))
        (output/'personas.log').write_text(invoke(container,'mud86ctl','personas','--json'))
        profile=json.loads(invoke(container,'sudo','mud86ctl','persona',name,'--json'))
        assert profile['backend']=='mariadb' and profile['personas'][0]['has_password']
        assert 'password_word' not in profile['personas'][0]
        access=json.loads(invoke(container,'mud86ctl','database-access'))
        assert access['host']=='127.0.0.1' and access['port']==3307 and access['user']=='mud86_editor'
        assert 'password' not in access
        (output/'editor.log').write_text(invoke(container,'/opt/mud86/current/.venv/bin/python',
                                              '-m','tests.deployed_database_editor',name))
        if cycles:
            report.update(diagnostic_only=True,batch_warmup=warm_batch,idle_seconds=idle_seconds,shutdown_cycles=[])
            shutdown_cycles(container,url,name,'testpass',cycles,report['shutdown_cycles'],idle_seconds)
            report.update(complete=True,architecture=invoke(container,'uname','-m').strip())
            return
        invoke(container,'systemctl','is-active','mud86-database','mud86-runtime','mud86-gateway')
        invoke(container,*command,log=output/'rerun.log')
        asyncio.run(login(url,name,'testpass'))
        invoke(container,'sudo','mud86ctl','backup',log=output/'backup.log')
        asyncio.run(login(url,name,'testpass'))
        invoke(container,'sudo','mud86ctl','restart'); asyncio.run(login(url,name,'testpass'))
        (output/'editor-restart.log').write_text(invoke(container,'/opt/mud86/current/.venv/bin/python',
                                                      '-m','tests.deployed_database_editor',name))
        report.update(complete=True,cutover_preserved_player=not fresh,installer_rerun=True,backup=True,restart=True,
                      tcp_editor=True,
                      architecture=invoke(container,'uname','-m').strip())
    finally: (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--container',default='mud86-install-test'); parser.add_argument('--url',default='http://127.0.0.1:38080')
    parser.add_argument('--fresh',action='store_true')
    parser.add_argument('--native-url',help='Loopback endpoint before cutover, including the mapped HTTPS port')
    parser.add_argument('--shutdown-diagnostics',action='store_true',help='Private guest-state capture on disposable CI runtime failures')
    parser.add_argument('--shutdown-cycles',type=int,choices=range(1,MAX_SHUTDOWN_CYCLES+1),default=0,help='Diagnostic-only stop/start cycles after first installation, not full acceptance')
    parser.add_argument('--warm-batch',action='store_true',help='Candidate native batch execution preflight before game admission')
    parser.add_argument('--idle-seconds',type=int,default=0,help='Bounded idle interval before diagnostic shutdown cycles')
    args=parser.parse_args(); run(args.container,args.url,args.fresh,args.native_url,args.shutdown_diagnostics,args.shutdown_cycles,args.warm_batch,args.idle_seconds)
