"""Exercise ATTACH-question disconnects on a disposable original TOPS-10 disk."""
import argparse
import asyncio
import json
import logging
from pathlib import Path
import re
import time
from unittest.mock import patch

import pexpect

from aiohttp import ClientSession, WSMsgType
from aiohttp.test_utils import TestServer

from server.gateway import create_app, LOG
from tools.audit_archwizards import MAX_BOOT_ATTEMPTS
from tools.benchmark_idle import Emulator
from tools.provision_archwizards import NativePersonas
from tests.integration_provisioning import source_hashes, require

ROOT = Path(__file__).resolve().parents[1]
EXPECT_TIMEOUT = 30
JOB_REMOVAL_TIMEOUT = 10
JOB_POLL_INTERVAL = 0.25


def deployment_emulator(directory):
    # Select the deployment throttle before SIMH opens its DO script. Never
    # rewrite a running .ini or rely on pause/resume to reconfigure the guest.
    spawn = pexpect.spawn
    def start(executable, args, **kwargs):
        config = Path(args[0])
        config.write_text(config.read_text().replace('boot tu0\n', 'set throttle 5M\nboot tu0\n'))
        return spawn(executable, args, **kwargs)
    with patch('pexpect.spawn', start):
        return Emulator(directory, 'noidle', speed_factor=8)


class Browser:
    def __init__(self, socket):
        self.socket = socket
        self.buffer = ''

    async def expect(self, marker):
        async def receive():
            while marker not in self.buffer:
                message = await self.socket.receive()
                require(message.type == WSMsgType.TEXT, 'Browser closed before expected game response')
                self.buffer += message.data
            result, self.buffer = self.buffer.split(marker, 1)
            return result + marker
        return await asyncio.wait_for(receive(), EXPECT_TIMEOUT)

    async def login(self, name, password, wizard=False):
        await self.expect('By what name shall I call you?')
        await self.expect('*')
        await self.socket.send_str(name + '\r')
        await self.expect("This persona already exists - what's the password?")
        await self.expect('*')
        await self.socket.send_str(password + '\r')
        await self.expect('Hello')
        await self.expect('\n----*' if wizard else '\n*')

    async def closing(self):
        async def receive():
            while True:
                message = await self.socket.receive()
                if message.type != WSMsgType.TEXT:
                    require(message.type == WSMsgType.CLOSE, 'Unexpected browser failure')
                    return message.data
        return await asyncio.wait_for(receive(), EXPECT_TIMEOUT)


class Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages = []

    def emit(self, record):
        self.messages.append({'level': record.levelname, 'message': record.getMessage()})


def verify_persona_bytes(native):
    native.command('copy clnaft.pm=mud.?pm')
    native.command('r filcom', b'\n*')
    result = native.command('tty:=clnbef.pm,clnaft.pm/b', b'\n*')
    require('No differences encountered' in result, 'Cleanup changed persona file bytes')
    native.connection.write(b'\x1a')
    native.expect(b'\n.')


async def exercise(machine, native, output, report):
    before = await asyncio.to_thread(native.records)
    capture = Capture()
    level = LOG.level
    LOG.setLevel(logging.INFO)
    LOG.addHandler(capture)
    try:
        for trigger, name, style in (('ctrl-c', 'Ghosta', 'bbc40'),
                                     ('disconnect', 'Ghostb', 'original'),
                                     ('restart', 'Ghostc', 'vt220'),
                                     ('shutdown', 'Ghostd', 'original')):
            print('Native ATTACH question cleanup:', trigger, flush=True)
            start = len(capture.messages)
            await asyncio.to_thread(native.command, 'copy clnbef.pm=mud.?pm')
            async with TestServer(create_app(upstream_port=machine.port)) as server, ClientSession() as client:
                socket = await client.ws_connect(server.make_url('/terminal?style=' + style))
                browser = Browser(socket)
                await browser.login('Roy', 'cleanupx', wizard=True)
                await socket.send_str('attach ' + name.lower() + '\r')
                await browser.expect('Creating new persona:')
                await browser.expect('What sex do you wish to be?')
                await browser.expect('*')
                if trigger == 'ctrl-c':
                    await socket.send_str('\x03')
                    require(await browser.closing() == 1008, 'Browser Ctrl-C was not rejected')
                elif trigger == 'restart':
                    await socket.send_bytes(b'restart')
                    await browser.closing()
                elif trigger == 'shutdown':
                    closing = asyncio.create_task(browser.closing())
                    await asyncio.wait_for(server.close(), EXPECT_TIMEOUT)
                    await closing
                else:
                    await socket.close()
                await server.close()  # Also wait for server-side logout, not just TCP close.
            messages = capture.messages[start:]
            require(not any(row['level'] in ('WARNING', 'ERROR') for row in messages),
                    'Native cleanup emitted a warning; see gateway-log.json')
            require(any('Terminal logout complete:' in row['message'] for row in messages),
                    'Native logout was not confirmed')
            # SYSTAT emits the PPN without brackets. Logged-off can precede
            # the monitor finishing job removal; observe that bounded settling.
            snapshots = []
            deadline = time.monotonic() + JOB_REMOVAL_TIMEOUT
            while True:
                status = await asyncio.to_thread(native.command, 'systat')
                snapshots.append(status)
                remaining = re.search(r'MUDGUEST|\b2653\s*,\s*2653\b', status, re.I)
                if not remaining or time.monotonic() >= deadline:
                    break
                await asyncio.sleep(JOB_POLL_INTERVAL)
            (output / (trigger + '-systat.txt')).write_text('\n'.join(snapshots))
            require(not remaining, 'A MUDGUEST operating-system job remained after cleanup')
            after = await asyncio.to_thread(native.records)
            require(after == before, 'ATTACH interruption changed saved persona/password records')
            await asyncio.to_thread(verify_persona_bytes, native)
            # Fresh connection through a different width must accept an ordinary saved password.
            async with TestServer(create_app(upstream_port=machine.port)) as server, ClientSession() as client:
                socket = await client.ws_connect(server.make_url('/terminal?style=original'))
                browser = Browser(socket)
                await browser.login('Clncheck', 'checkpwd')
                await socket.send_str('quit\r')
                await browser.closing()
            after = await asyncio.to_thread(native.records)
            require(all(after[key]['password_word'] == row['password_word'] for key, row in before.items()),
                    'Saved password changed after re-entry')
            before = after
            report.setdefault('cases', {})[trigger] = 'native logout, no guest job, records preserved, saved re-entry'
    finally:
        LOG.removeHandler(capture)
        LOG.setLevel(level)
        (output / 'gateway-log.json').write_text(json.dumps(capture.messages, indent=2) + '\n')


def run(output):
    output.mkdir(mode=0o700)
    original = source_hashes()
    machine = None
    report = {'complete': False}
    try:
        for attempt in range(MAX_BOOT_ATTEMPTS):
            print('Cleanup private boot:', attempt + 1, flush=True)
            machine = deployment_emulator(output / f'machine-{attempt + 1}')
            try:
                machine.boot()
                break
            except Exception:
                machine.stop()
                machine = None
                if attempt + 1 == MAX_BOOT_ATTEMPTS:
                    raise
        report['profile'] = 'NOIDLE / 5M throttle / DZ SPEED=*8'
        with NativePersonas(machine.port) as native:
            native.create_and_save('Roy', 'cleanupx')
            native.create_and_save('Clncheck', 'checkpwd')
            asyncio.run(exercise(machine, native, output, report))
        require(original == source_hashes(), 'Original source changed')
        report.update(complete=True, source_unchanged=True)
        print(json.dumps(report, indent=2), flush=True)
    finally:
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        if machine is not None:
            machine.stop()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'runtime' / f'gateway-cleanup-{time.time_ns()}')
    run(parser.parse_args().output.resolve())
