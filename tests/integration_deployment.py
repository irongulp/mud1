"""Acceptance driver for the disposable systemd AlmaLinux Docker test machine.

The container is started explicitly as documented in docs/deployment.md.
Setup output is captured and credential lines redacted before being saved.
"""
import argparse
import asyncio
import io
import json
from pathlib import Path
import re
import secrets
import string
import subprocess
import time

from aiohttp import ClientSession
from tests.integration_web import Browser

ROOT = Path(__file__).resolve().parents[1]
PLAYER_NAME = 'Deploy' + ''.join(secrets.choice(string.ascii_lowercase) for _ in range(3))
SLEEP_SECONDS = 6
SLEEP_TOLERANCE = 1.5


def invoke(container, *command):
    result = subprocess.run(['docker', 'exec', '-w', '/checkout', container, *command],
                            capture_output=True, text=True, timeout=900)
    text = re.sub(r'(?m)^(Richard|Roy|Brian|Ronan|Friday|Yawn|Debugger): [a-z0-9]{8} —',
                  r'\1: [redacted] —', result.stdout + result.stderr)
    if result.returncode:
        raise AssertionError(text)
    return text


async def saved_player(url, creating):
    async with ClientSession(headers={'Host': 'mud.etimbo.com'}) as client:
        async with client.get(url) as response:
            assert response.status == 200
            assert 'xterm' in await response.text()
        socket = await client.ws_connect(url + '/terminal')
        player = Browser(socket, PLAYER_NAME, io.StringIO())
        try:
            await player.expect('By what name shall I call you?')
            await player.expect('*')
            await player.send(PLAYER_NAME)
            if creating:
                await player.expect('What sex do you wish to be?')
                await socket.send_str('m')
                await player.expect('letters, please.')
            else:
                await player.expect("This persona already exists - what's the password?")
            await player.expect('*')
            await player.send('testpass')
            await player.expect('Hello')
            await player.expect('\n*')
            if creating:
                await player.send('save')
                await player.expect('saved.')
                await player.expect('\n*')
            await player.send('who')
            assert PLAYER_NAME in await player.expect('\n*')
            await player.send('sleep')
            await player.expect('ZZZzzz...')
            started = time.monotonic()
            await player.expect('You wake up.')
            elapsed = time.monotonic() - started
            assert abs(elapsed - SLEEP_SECONDS) <= SLEEP_TOLERANCE, elapsed
            await player.expect('\n*')
            await player.send('quit')
            await player.expect('\n.')
            return elapsed
        finally:
            await socket.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--container', default='mud86-install-test')
    parser.add_argument('--url', default='http://127.0.0.1:38080')
    args = parser.parse_args()
    output = ROOT / 'runtime' / ('deployment-' + args.container)
    output.mkdir(mode=0o700, exist_ok=True)
    command = ['bash', '/checkout/setup.sh', '--domain', 'mud.etimbo.com', '--http-only',
               '--image', '/artifacts/mud86-runtime.tar.gz']
    print('AlmaLinux: install', flush=True)
    (output / 'install.log').write_text(invoke(args.container, *command))
    sleeps = [asyncio.run(saved_player(args.url, creating=True))]
    print('AlmaLinux: saved player created through Nginx/WebSocket; rerun setup', flush=True)
    before = invoke(args.container, 'sha256sum', '/var/lib/mud86/private/archwizard-credentials.json')
    (output / 'rerun.log').write_text(invoke(args.container, *command))
    assert invoke(args.container, 'sha256sum', '/var/lib/mud86/private/archwizard-credentials.json') == before
    sleeps.append(asyncio.run(saved_player(args.url, creating=False)))
    print('AlmaLinux: backup and restart', flush=True)
    (output / 'backup.log').write_text(invoke(args.container, 'sudo', 'mud86ctl', 'backup'))
    sleeps.append(asyncio.run(saved_player(args.url, creating=False)))
    (output / 'status.log').write_text(invoke(args.container, 'sudo', 'mud86ctl', 'status'))
    report = {'complete': True, 'platform': 'AlmaLinux 9 container, systemd',
              'architecture': invoke(args.container, 'uname', '-m').strip(),
              'sleep_wake_seconds': [round(value, 3) for value in sleeps],
              'checks': ['install', 'HTTP/WebSocket via Nginx', 'saved persona', 'setup rerun',
                         'credential preservation', 'clean shutdown backup', 'restart and persona re-entry'],
              'not_exercised': ['public ACME issuance', 'SELinux enforcing kernel', 'IONOS host reboot']}
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
