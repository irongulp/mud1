"""Opt-in external RESET regression on copied disks and a private MariaDB.

Requires an explicit stopped external always-open fixture and active-tick-v1
SIMH binary. --build rebuilds the allowlist from this checkout before testing.
Neither a live game nor its database is touched.
"""
import argparse
import asyncio
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time
from unittest.mock import patch

from aiohttp.test_utils import TestServer
import pexpect

from server.external_bootstrap import ExternalBootstrap
from server.gateway import create_app
from tests.integration_external_admin import AdminHub
from tests.integration_external_availability import shutdown
from tests.integration_external_lifecycle import LifecycleGame
from tests.integration_external_login import Controller
from tests.integration_external_save import route
from tests.integration_persona_writes import enable_writes, revision
from tests.integration_provisioning import require, source_hashes
from tests.integration_storage_bridge import private_emulator
from tests.mariadb_fixture import LocalMariaDb
from tools.build_external_guest import compile_bcpl, rendered, transfer, DATA_BASE, MARKER_BASE
from tools.inspect_game import NativeInspector
from tools.persona_bootstrap import SeedIssuer
from tools.persona_protocol import pack_name
from tools.persona_writes import isolated_writer
from tools.prepare import prepare
from tools.reset_permissions import configure
from tools.serve_external import reserve_ports, source_stopped
from tools.simh_timer import verify

ROOT = Path(__file__).resolve().parents[1]
NAME, PASSWORD = 'Resetwiz', 'resetkey'
GAME_TIMEOUT = 30
OLD_ALLOWED = 'and chain.allowed(target)=seq(target,"mud") \\/ seq(target,"valley")'


def authorize(native):
    native.begin_copy('mud.wiz')
    native.send(NAME.lower())
    native.receive(b'\n')
    time.sleep(.1)
    native.connection.write(b'\x1a')
    native.receive(b'\n.')
    native.at_monitor = True
    native.command('protect mud.wiz<055>')
    configure(native)


def rebuild(native, output):
    generated = output / 'prepared'
    prepare(ROOT / 'source', ROOT / 'upstream/mud1', generated,
            always_open=True, external_lifecycle=True, chain_targets=('mud', 'valley'))
    library = (generated / 'MUDLIB.BCL').read_text()
    allowed = next(line for line in library.splitlines() if line.startswith('and chain.allowed('))
    native.command('assign dsk: bcl:')
    native.command('set tty no altmode')
    old = native.command('type x24lib.bcl').replace('\r', '').split('\n', 1)[1].rsplit('\n.', 1)[0]
    require(old.count(OLD_ALLOWED) == 1, 'Unexpected baseline allowlist')
    desired = old.replace(OLD_ALLOWED, allowed)
    native.command('copy xrsbef.pm=pmhold.pm')
    native.command('r teco', b'\n*')
    edit = ('ERx24lib.bcl\x1bEWxrlib.bcl\x1bY'
            'Nand chain.allowed(target)=\x1b0LK'
            'I' + allowed + '\r\x1bEX\x1b\x1b')
    native.connection.write(edit.encode('ascii'))
    native.receive(b'\n.')
    native.at_monitor = True
    actual = native.command('type xrlib.bcl').replace('\r', '').split('\n', 1)[1].rsplit('\n.', 1)[0]
    require(rendered(actual) == rendered(desired), 'Guest edit differs from generated allowlist-only patch')
    (output / 'MUDLIB-fixed.BCL').write_text(desired)
    compile_bcpl(native, 'xrlib')
    probe = '''get "bcl:acs"
get "bcl:rfs"
get "bcl:iolib"
get "bcl:bits"
get "bcl:kernel"
$ldtext "/runame:xchck"
let start() be
$( test chain.allowed("mud") /\\ chain.allowed($6"mud") /\\
        chain.allowed("MUD") /\\ chain.allowed("valley") /\\
        chain.allowed($6"valley") /\\ ~chain.allowed("other") /\\
        ~chain.allowed($6"other") /\\ sixbit($6"swamp1")=$6"swamp1"
   then writes(tty,"XCHCK PASS*C*L")
   or writes(tty,"XCHCK FAIL*C*L")
$)
''' + allowed + '\n'
    transfer(native, 'xchck.bcl', probe)
    compile_bcpl(native, 'xchck')
    native.command('r link', b'\n*')
    native.command('xchck/g')
    native.command('save xchck')
    result = native.command('run xchck')
    (output / 'allowlist-probe.txt').write_text(result)
    require('XCHCK PASS' in result, 'Native filename conversion probe failed')
    native.command('copy xrsold.exe=mud.exe')
    native.command('r link', b'\n*')
    native.command(f'/set:.low.:{MARKER_BASE:o}', b'\n*')
    counters = native.command('roboot,mud0,mud1,mud2,mud3,mud4,mud5,mud6,mud7,mud8,xrlib,mboots,xlstate/counter', b'\n*')
    (output / 'link-counters.txt').write_text(counters)
    values = re.findall(r'\.HIGH\.\s+[0-7]+\s+([0-7]+)', counters)
    require(values and int(values[-1], 8) < DATA_BASE, 'Current code end overlaps DBADAT')
    native.command(f'/set:.high.:{DATA_BASE:o}', b'\n*')
    native.command('dbadat/g')
    native.command('ssave xrsmud')
    native.command('run xrsmud', b'MUD saved')
    native.receive(b'\n.')
    native.at_monitor = True
    configure(native)
    native.command('r filcom', b'\n*')
    result = native.command('tty:=xrsbef.pm,pmhold.pm/b', b'\n*')
    require('No differences encountered' in result, 'Rebuild changed retained native personas')
    native.connection.write(b'\x1a')
    native.receive(b'\n.')
    native.at_monitor = True
    return {'allowed': allowed, 'code_end': values[-1], 'native_personas_unchanged': True}


def command(game, text, expected=None):
    def receive(marker):
        data = game.monitor.connection.read_until(marker, GAME_TIMEOUT)
        require(data.endswith(marker), 'Incomplete ' + text + ': ' + repr(data))
        return data.decode('ascii', errors='replace')
    game.monitor.send(text)
    receive((text + '\r\n').encode('ascii'))
    output = receive(expected.encode('ascii')) if expected else ''
    return output + receive(game.prompt)


def enter_saved_wizard(game):
    # Game.enter assumes every non-archwizard has a mortal prompt; this fixture
    # deliberately persists WIZARD mode on an ordinary name.
    monitor = game.monitor
    game.issuer.load(monitor)
    monitor.command('start', b'By what name shall I call you?')
    monitor.receive(b'*')
    monitor.send(NAME)
    monitor.receive(b"what's the password?")
    monitor.receive(b'*')
    monitor.send(PASSWORD)
    monitor.receive(b'Hello again, ' + NAME.encode('ascii'))
    game.prompt = b'\n----*'
    monitor.receive(game.prompt)
    game.accepted = True


def solo(machine, store, evidence, returning=False):
    with Controller(machine.port) as monitor:
        game = LifecycleGame(monitor, SeedIssuer())
        if returning:
            # Saved wizard admission already restores wizard mode.
            enter_saved_wizard(game)
        else:
            game.enter_new(NAME, PASSWORD)
            game.prompt = b'\n----*'
            command(game, 'wizard mode', 'Welcome')
            command(game, 'save', ' saved.')
        command(game, 'go swamp1', 'SWAMP1')
        before = store.get(pack_name(NAME.lower()))
        result = command(game, 'reset', 'Everything in the game has been reset')
        evidence['reset'] = result
        require('External handover' not in result and "can't get at" not in result,
                'Solo RESET failed: ' + repr(result))
        require('Room SWAMP1' in result, 'RESET destination not preserved')
        evidence['look'] = command(game, 'look me', 'Room SWAMP1')
        evidence['who'] = command(game, 'who', NAME + ' the wizard is playing')
        after = store.get(pack_name(NAME.lower()))
        require(before.words[7] == after.words[7], 'Password changed during handover')
        require('superseded' not in evidence['look'] + evidence['who'], 'Still in superseded world')
        game.quit()


async def browsers(machine, output):
    from playwright.async_api import async_playwright
    os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(ROOT / 'runtime/browsers'))
    report = {}
    async with TestServer(create_app(upstream_port=machine.port, session_bootstrap=ExternalBootstrap())) as server:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch()
            try:
                for chat in (False, True):
                    page = await browser.new_page()
                    await page.add_init_script("localStorage.setItem('mud86-chat-mode'," + json.dumps(str(chat).lower()) + ");")
                    await page.add_init_script('''window.gameOutput = ''; window.socketCount = 0;
                        const OriginalWebSocket = WebSocket;
                        window.WebSocket = class extends OriginalWebSocket {
                            constructor(...args) { super(...args); socketCount++;
                                this.addEventListener('message', e => gameOutput += e.data); }
                        };''')
                    await page.goto(str(server.make_url('/')))
                    await page.evaluate('terminalReady')

                    async def expect(text):
                        await page.wait_for_function('text => gameOutput.includes(text)', arg=text, timeout=30000)
                        await page.wait_for_function('incoming.pending.length === 0')
                        await page.evaluate("new Promise(resolve => terminal.write('', resolve))")

                    async def submit(text):
                        await page.evaluate("gameOutput = ''")
                        if chat:
                            field = page.get_by_label('Command', exact=True)
                            await field.fill(text)
                            await field.press('Enter')
                        else:
                            await page.keyboard.type(text)
                            await page.keyboard.press('Enter')

                    await expect('By what name shall I call you?')
                    await submit(NAME)
                    await expect("what's the password?")
                    await submit(PASSWORD)
                    await expect('Hello again, ' + NAME)
                    await expect('\n----*')
                    await submit('go swamp1')
                    await expect('Room SWAMP1')
                    await expect('\n----*')
                    await submit('score')
                    await expect('Games played to date:')
                    await expect('\n----*')
                    before = re.search(r'Games played to date:\s*(\d+)', await page.evaluate('gameOutput'))[1]
                    await submit('reset')
                    await expect('Everything in the game has been reset')
                    await expect('Room SWAMP1')
                    await expect('\n----*')
                    response = await page.evaluate('gameOutput')
                    require('External handover' not in response and 'superseded' not in response, 'Browser handover failed')
                    require(await page.evaluate('socketCount') == 1, 'Browser reconnected during RESET')
                    await submit('score')
                    await expect('Games played to date:')
                    await expect('\n----*')
                    after = re.search(r'Games played to date:\s*(\d+)', await page.evaluate('gameOutput'))[1]
                    require(before == after, 'RESET incremented GAMES')
                    label = 'chat' if chat else 'terminal'
                    report[label] = {'reset': response, 'same_socket': True, 'games_unchanged': True}
                    await page.screenshot(path=str(output / (label + '.png')))
                    await submit('quit')
                    await expect('By what name shall I call you?')
                    await page.close()
            finally:
                await browser.close()
    return report


def faults(machine, database, store, hub, evidence):
    with Controller(machine.port) as monitor:
        game = LifecycleGame(monitor, SeedIssuer())
        enter_saved_wizard(game)
        game.prompt = b'\n*'
        command(game, 'wizard mode')  # Earn the ordinary score fixture as a mortal.
        # Reset's destination in previous tests was swamp1; fresh admission uses
        # a normal start. All route outcomes are checked by the existing helper.
        route(lambda text: command(game, text))
        require('Score to date: 11' in command(game, 'score', 'Score to date:'), 'Scoring fixture failed')
        game.prompt = b'\n----*'
        command(game, 'wizard mode', 'Welcome')
        command(game, 'go swamp1', 'Room SWAMP1')
        key = pack_name(NAME.lower())
        before = revision(database, key)
        operations = len(hub.operations)
        hub.mode = 'unknown'
        evidence['save_unknown'] = command(game, 'save', 'outcome unknown')
        evidence['save_blocked_reset'] = command(game, 'reset', 'External handover unavailable')
        require(len(hub.operations) == operations + 1, 'Unknown SAVE allowed another mutation')
        database.start()
        require(revision(database, key) == before + 1, 'SAVE did not commit once')
        evidence['save_recovered_reset'] = command(game, 'reset', 'Room SWAMP1')
        require(revision(database, key) == before + 2, 'Recovery duplicated SAVE or missed exit checkpoint')
        require(store.get(key).words[3] == 11, 'Recovery lost saved score')
        with Controller(machine.port) as peer:
            victim = LifecycleGame(peer, SeedIssuer())
            victim.enter_new('Rvictim', PASSWORD)
            command(victim, 'save', ' saved.')
            victim.quit()
        target = pack_name('rvictim')
        hub.mode = 'unknown'
        monitor.send('purge rvictim')
        monitor.receive(b'Save, delete or finish? ')
        monitor.send('d')
        evidence['purge_unknown'] = monitor.receive(game.prompt)
        require('PURGE outcome UNKNOWN' in evidence['purge_unknown'], 'PURGE uncertainty not reproduced')
        operations, deletes = len(hub.operations), len(hub.purges)
        evidence['purge_blocked_reset'] = command(game, 'reset', 'External handover unavailable')
        require(len(hub.operations) == operations and len(hub.purges) == deletes, 'Unresolved PURGE allowed mutation')
        database.start()
        require(store.get(target) is None, 'PURGE did not commit')
        evidence['purge_recovered_reset'] = command(game, 'reset', 'Room SWAMP1')
        require(len(hub.purges) == deletes and store.get(target) is None, 'PURGE replayed after recovery')
        saved, before = store.get(key), revision(database, key)
        database.pause()
        try:
            monitor.send('reset')
            data = monitor.connection.read_until(b'\n.', GAME_TIMEOUT)
            evidence['checkpoint_outage'] = data.decode('ascii', errors='replace')
            require(data.endswith(b'\n.') and b'External handover not confirmed' in data,
                    'Unconfirmed checkpoint did not close at monitor')
            require(b'Room SWAMP1' not in data, 'Unconfirmed checkpoint launched destination')
            monitor.at_monitor, game.accepted = True, False
        finally:
            database.resume()
        require(store.get(key) == saved and revision(database, key) == before, 'Failed checkpoint changed record')
        game.enter_new('Rportal', PASSWORD)
        evidence['portal_out'] = command(game, 'e', 'Narrow road between lands.')
        evidence['portal_back'] = command(game, 'e', 'Narrow road between lands.')
        require(store.get(pack_name('rportal')).words[0] & ((1 << 18) - 1) == 1, 'Portal incremented GAMES')
        game.quit()


def run(args):
    output, source = args.output.resolve(), args.source.resolve()
    verify(args.simulator.resolve().parent.parent)
    require(source_stopped(source), 'Source disk is in use')
    output.mkdir(mode=0o700)
    directory = output / 'machine'
    directory.mkdir(mode=0o700)
    shutil.copyfile(source, directory / 'guest.dsk')
    original = source_hashes()
    report = {'complete': False, 'base_commit': 'c22828f', 'simulator': str(args.simulator.resolve()),
              'simulator_sha256': hashlib.sha256(args.simulator.read_bytes()).hexdigest(),
              'source_disk': str(source), 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest()}
    machine = None
    spawn = pexpect.spawn

    def simulator(executable, arguments, **kwargs):
        return spawn(str(args.simulator.resolve()), arguments, **kwargs)

    def save():
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')

    try:
        with patch('pexpect.spawn', simulator), ExitStack() as services:
            database = store = None
            for restart in (False, True):
                print('Private RESET check:', 'restart' if restart else 'first boot', flush=True)
                ports = reserve_ports()
                machine = private_emulator(directory, ports, reuse=True)
                machine.boot()
                machine.command('daytime')
                with NativeInspector(machine.port) as native:
                    if args.build and not restart:
                        print('Rebuilding generated allowlist with original BCPL', flush=True)
                        report['build'] = rebuild(native, output)
                    authorize(native)
                if database is None:
                    database = services.enter_context(LocalMariaDb(output / 'db', column_schema=True))
                    config = enable_writes(database, allow_create=True, allow_delete=True)
                    store = services.enter_context(isolated_writer(config))
                with AdminHub(machine, ports, store, database) as hub:
                    evidence = report.setdefault('restart' if restart else 'first', {})
                    try:
                        solo(machine, store, evidence, restart)
                        save()
                        if not restart:
                            report['browsers'] = asyncio.run(browsers(machine, output))
                            save()
                            faults(machine, database, store, hub, report.setdefault('faults', {}))
                        require(not hub.errors, 'Bridge errors: ' + repr(hub.errors))
                    finally:
                        if database.process is None:
                            database.start()
                        save()
                print('Behavior passed; requesting one native shutdown', flush=True)
                shutdown(machine)
                machine.stop()
                require(not machine.child.isalive(), 'Simulator still running')
                machine = None
                report.setdefault('clean_shutdowns', []).append('restart' if restart else 'first')
                save()
        require(original == source_hashes(), 'Original source changed')
        report.update(complete=True)
    except BaseException as error:
        report['error_type'] = type(error).__name__
        raise
    finally:
        if machine is not None:
            machine.stop()
            report['simulator_exited'] = not machine.child.isalive()
        report['source_unchanged'] = original == source_hashes()
        save()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True, help='Stopped external always-open guest.dsk')
    parser.add_argument('--simulator', type=Path, required=True, help='Checksum-verified active-tick-v1 SIMH binary')
    parser.add_argument('--build', action='store_true', help='Rebuild allowlist from current generated source')
    run(parser.parse_args())
