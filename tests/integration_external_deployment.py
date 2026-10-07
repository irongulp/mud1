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


def native_fixture_name(report):
    name=report.get('player_name')
    if (report.get('complete') is not True or not isinstance(name,str)
            or not re.fullmatch(rf'[A-Za-z]{{1,{MAX_NAME_LENGTH}}}',name)):
        raise ValueError('Cutover requires a completed native acceptance report with its verified persona name')
    return name


def invoke(container,*command):
    if command and command[0]=='sudo': command=command[1:]
    result=subprocess.run(['docker','exec','-w','/checkout',container,*map(str,command)],capture_output=True,text=True,timeout=3600)
    text=re.sub(r'(?m)^(Richard|Roy|Brian|Ronan|Friday|Yawn|Debugger): [a-z0-9]{8} —',r'\1: [redacted] —',result.stdout+result.stderr)
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


def run(container,url,fresh,native_url=None):
    output=ROOT/'runtime'/('external-deployment-'+container); output.mkdir(mode=0o700,exist_ok=True)
    report={'complete':False,'fresh_external':fresh}
    try:
        name='Freshsql' if fresh else native_fixture_name(json.loads(
            (ROOT/'runtime'/('deployment-'+container)/'report.json').read_text()))
        if not fresh:
            asyncio.run(login(native_url or url,name,'testpass'))
            before=json.loads(invoke(container,'mud86ctl','persona',name,'--json'))
            assert before['personas'][0]['password_set'], 'Native cutover fixture was not saved'
        command=['bash','/checkout/setup.sh','--domain','mud.etimbo.com','--http-only','--image','/artifacts/mud86-runtime.tar.gz','--persona-storage','mariadb']
        (output/'install.log').write_text(invoke(container,*command))
        (output/'login.log').write_text(asyncio.run(login(url,name,'testpass',fresh)))
        (output/'personas.log').write_text(invoke(container,'mud86ctl','personas','--json'))
        profile=json.loads(invoke(container,'sudo','mud86ctl','persona',name,'--json'))
        assert profile['backend']=='mariadb' and profile['personas'][0]['has_password']
        assert 'password_word' not in profile['personas'][0]
        invoke(container,'systemctl','is-active','mud86-database','mud86-runtime','mud86-gateway')
        (output/'rerun.log').write_text(invoke(container,*command))
        asyncio.run(login(url,name,'testpass'))
        (output/'backup.log').write_text(invoke(container,'sudo','mud86ctl','backup'))
        asyncio.run(login(url,name,'testpass'))
        invoke(container,'sudo','mud86ctl','restart'); asyncio.run(login(url,name,'testpass'))
        report.update(complete=True,cutover_preserved_player=not fresh,installer_rerun=True,backup=True,restart=True,
                      architecture=invoke(container,'uname','-m').strip())
    finally: (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--container',default='mud86-install-test'); parser.add_argument('--url',default='http://127.0.0.1:38080')
    parser.add_argument('--fresh',action='store_true')
    parser.add_argument('--native-url',help='Loopback endpoint before cutover, including the mapped HTTPS port')
    args=parser.parse_args(); run(args.container,args.url,args.fresh,args.native_url)
