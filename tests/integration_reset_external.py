"""Verify RESET permissions on a copied external lab, including launcher rerun."""
import argparse
import asyncio
import json
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from types import SimpleNamespace

from aiohttp import ClientSession

from server.external_bootstrap import ExternalBootstrap
from tests.integration_gateway_cleanup import Browser
from tests.integration_provisioning import require, source_hashes
from tests.integration_reset import chromium, command, PASSWORD
from tools.inspect_game import NativeInspector
from tools.persona_migrate import load_config
from tools.persona_protocol import pack_name
from tools.persona_writes import isolated_writer
from tools.reset_permissions import configure, protection, EXECUTABLE
from tools.serve_external import ROOT, DEFAULT_IMAGE


async def exercise(url, store, output):
    async with ClientSession() as client:
        async def create(name, wizard=False):
            player = Browser(await client.ws_connect(url + '/terminal'))
            await player.expect('By what name shall I call you?')
            await player.expect('*')
            await player.socket.send_str(name + '\r')
            if not wizard:
                await player.expect('What sex do you wish to be?')
                await player.expect('*')
                await player.socket.send_str('m')
            await player.expect('letters, please.')
            await player.expect('*')
            await player.socket.send_str(PASSWORD + '\r')
            await player.expect('Hello, ' + name)
            await player.expect('\n----*' if wizard else '\n*')
            return player

        roy = await create('Roy', True)
        plain = await create('Rplain')
        for player, wizard in ((roy, True), (plain, False)):
            require(' saved.' in await command(player, 'save', wizard, ' saved.'), 'External SAVE failed')
        # Original createprofile sets maint for an existing saved archwizard,
        # not a brand-new name on its first admission under MUDGUEST.
        await roy.socket.send_str('quit\r')
        await roy.closing()
        roy = Browser(await client.ws_connect(url + '/terminal'))
        await roy.login('Roy', PASSWORD, wizard=True)
        before = [await asyncio.to_thread(store.get, pack_name(name)) for name in ('roy', 'rplain')]
        require(all(record is not None for record in before), 'Saved records missing')
        result = await command(roy, 'reset', True, 'You are now in a superseded game.')
        (output / 'reset-response.txt').write_text(result)
        require('superseded game' in result and "can't get at" not in result, 'External RESET failed')
        after = [await asyncio.to_thread(store.get, pack_name(name)) for name in ('roy', 'rplain')]
        require(after == before, 'Reset changed saved database records')
        fresh = await create('Rfresh')
        who = await command(fresh, 'who', expected='Rfresh is playing')
        require('Rfresh is playing' in who and 'Roy' not in who and 'Rplain' not in who,
                'New external session did not enter reset world')
        for player in (roy, plain, fresh):
            await player.socket.close()
        (output / 'external-reset.json').write_text(json.dumps({
            'reset': result, 'new_world_who': who, 'saved_records_unchanged': True}, indent=2) + '\n')


def run(output):
    output.mkdir(mode=0o700)
    original = source_hashes()
    process = None
    report = {'complete': False}
    try:
        for attempt in range(2):
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', 0))
                port = probe.getsockname()[1]
            with (output / f'launcher-{attempt}.log').open('wb') as log:
                process = subprocess.Popen([sys.executable, '-m', 'tools.serve_external',
                    '--state-dir', str(output / 'state'), '--prepared-runtime', str(DEFAULT_IMAGE),
                    '--port', str(port)], stdout=log, stderr=log)
                ready = output / 'state/ready.json'
                deadline = time.monotonic() + 240
                while not ready.exists():
                    require(process.poll() is None, 'Launcher failed; see private log')
                    require(time.monotonic() < deadline, 'Launcher readiness timeout')
                    time.sleep(.1)
                info = json.loads(ready.read_text())
                with NativeInspector(info['upstream_port']) as native:
                    require(protection(native.command('directory ' + EXECUTABLE)) == '051',
                            'Launcher did not configure RESET permissions')
                    require(not configure(native), 'Permission rerun was not idempotent')
                if attempt == 0:
                    with isolated_writer(load_config(output / 'state/database.json')) as store:
                        asyncio.run(exercise(info['url'], store, output))
                report[f'chromium_{attempt}'] = asyncio.run(chromium(
                    SimpleNamespace(port=info['upstream_port']), output, ExternalBootstrap()))
                process.send_signal(signal.SIGTERM)
                require(process.wait(timeout=150) == 0, 'External launcher did not shut down cleanly')
                process = None
                require(not ready.exists(), 'Stale launcher readiness remained')
        require(original == source_hashes(), 'Original source changed')
        report.update(complete=True, source_unchanged=True, restart_verified=True, clean_shutdown=True)
    finally:
        if process is not None and process.poll() is None:
            process.send_signal(signal.SIGTERM)
            try:
                process.wait(timeout=150)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'runtime' / f'reset-external-{time.time_ns()}')
    run(parser.parse_args().output.resolve())
