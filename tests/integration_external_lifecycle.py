"""Cross-job persona lifetimes and creator recovery on disposable runtimes."""
import argparse
import asyncio
from contextlib import ExitStack
import hashlib
import json
import shutil
import signal
import socket
from pathlib import Path
import time
from unittest.mock import patch

from tools.audit_archwizards import ARCHWIZARDS, MAX_BOOT_ATTEMPTS
from tools.persona_bootstrap import SeedIssuer
from tools.persona_protocol import pack_name
from tools.prepare import prepare
from tools.persona_write_session import WriteSession
from tools.persona_mariadb import MariaDbConfig
from tools.persona_writes import isolated_writer
from tests.chaining_fixture import install_worlds
from tests import integration_external_creation as creation
from tests import integration_external_login as login
from tests.integration_external_admin import AdminHub
from tests.integration_external_creation import CreationGame
from tests.integration_native_crossjob import controls as native_crossjob
from tests.integration_provisioning import require
from tests.integration_external_save import route
from tests.integration_storage_bridge import private_emulator
from server.gateway import logout_guest

NAMES = ('Crossnew', 'Crossold', 'Crosslost', 'Cjabort', 'Crosscont', 'Slotfresh',
         'Chainnew', 'Ninechars', 'Chainfail', 'Chainack', 'Cleansex')


class LifecycleGame(CreationGame):
    def command(self, text):
        self.monitor.send(text)
        # Other jobs can cause asynchronous room messages and extra prompts.
        # Do not mistake a queued prompt for this command's response.
        self.monitor.receive(text.encode('ascii') + b'\r\n')
        return self.monitor.receive(self.prompt)


def gateway_cleanup(monitor):
    class Stream:
        buffer = b''
        logged_off = False
        def write(self, text): monitor.connection.write(text.encode('ascii'))
        async def readuntil(self, marker):
            while marker not in self.buffer:
                self.buffer += monitor.connection.read_very_eager()
                require(len(self.buffer) < 4 * 1024 * 1024, 'Cleanup transcript exceeded bound')
                await asyncio.sleep(0.02)
            index = self.buffer.index(marker) + len(marker)
            result, self.buffer = self.buffer[:index], self.buffer[index:]
            if marker == b'Logged-off': self.logged_off = True
            return result
    stream = Stream()
    asyncio.run(logout_guest(stream, stream, entered=True, monitor=False, connection_id='lifecycle-fixture'))
    require(stream.logged_off, 'Gateway cleanup did not remove external guest job')
    monitor.connection.close(); monitor.connection = None


def build_guest(machine, native, build, output):
    login.compile_source(native, build, 'mud3', output)
    login.transfer(native, 'xlstate.mac', (build / 'XLSTATE.MAC').read_text())
    native.command('r macro', b'\n*'); native.command('xlstate=xlstate', b'\n*')
    native.connection.write(b'\x1a'); native.receive(b'\n.'); native.at_monitor = True
    login.transfer(native, 'mboots.mac', (build / 'MBOOTS.MAC').read_text())
    native.command('r macro', b'\n*'); native.command('mboots=mboots', b'\n*')
    native.connection.write(b'\x1a'); native.receive(b'\n.'); native.at_monitor = True
    command = native.command
    def linked(text, *args):
        if text.startswith('roboot,mud0,') and text.endswith('/counter'):
            text = text.replace('/counter', ',xlstate/counter')
        return command(text, *args)
    native.command = linked
    try:
        original_build(machine, native, build, output)
        install_worlds(machine, native, output)
    finally:
        native.command = command


original_build = login.build_guest


def attach(game, name, wizard=False):
    game.monitor.send('attach ' + name)
    game.prompt = b'\n----*' if wizard else b'\n*'
    output = game.monitor.receive(game.prompt)
    require('Attaching to ' + name in output, 'External live ATTACH failed')
    return output


def exercise(machine, native, database, store, hub, passwords, controls, goldens, report):
    issuer = SeedIssuer()
    with login.Controller(machine.port) as owner_monitor, login.Controller(machine.port) as visitor_monitor:
        owner, visitor = LifecycleGame(owner_monitor, issuer), LifecycleGame(visitor_monitor, issuer)
        for name in (*ARCHWIZARDS, login.ORDINARY):
            for correct in (False, True):
                accepted, _ = owner.enter(name, passwords[name] if correct else 'wrongxyz')
                require(accepted == controls[name + (' correct' if correct else ' wrong')], 'Lifetime build changed authentication')
                if accepted: owner.quit()
        report['authentication_comparisons'] = 16
        roy_password = store.get(pack_name('roy')).words[7]
        for name, initially_saved in (('Crossnew', False), ('Crossold', True)):
            print('Cross-job SAVE:', name, flush=True)
            key = pack_name(name.lower())
            owner.enter_new(name, passwords[name])
            if initially_saved: require(' saved.' in owner.command('save'), 'Owner first SAVE failed')
            require(visitor.enter('Roy', passwords['Roy'])[0], 'Visitor login failed')
            attach(visitor, name)
            require(' saved.' in visitor.command('save'), 'Live attached first SAVE failed')
            record = store.get(key)
            require(record.words[7] == roy_password and record.words[0] & ((1 << 18)-1) == 1,
                    'Cross-job SAVE changed native password/game-count behavior')
            attach(visitor, 'Roy', wizard=True); visitor.quit()
            if not initially_saved:
                response = owner.command('save')
                require(' saved.' in response, 'Owner SAVE after visitor creation failed: ' + repr(response))
            owner.quit()
            require(store.get(key).words[7] != roy_password, 'Owner persistence did not restore original password')
            require(owner.enter(name, passwords[name])[0], 'Owner password re-entry failed')
            owner.quit()
            report['cases'][name] = {'visitor_save': True, 'owner_password_restored': True}
        print('Stopped creator recovery across jobs', flush=True)
        name, key = 'Crosslost', pack_name('crosslost')
        owner.enter_new(name, passwords[name])
        require(visitor.enter('Roy', passwords['Roy'])[0], 'Recovery visitor login failed')
        attach(visitor, name)
        hub.mode = 'unknown'
        require('outcome unknown' in visitor.command('save'), 'Unacknowledged first creation not reproduced')
        # Original DETACH keeps the shared live profile. KJOB then removes only
        # this controller's TOPS-10 job; the actual owner remains connected.
        visitor_monitor.send('det')
        stopped = visitor_monitor.connection.read_until(b'\n.', 12)
        require(stopped.endswith(b'\n.'), 'DETACH did not reach monitor: ' + repr(stopped))
        visitor_monitor.at_monitor = True
        visitor.accepted = False
        visitor_monitor.command('kjob', b'Logged-off')
        visitor_monitor.connection.close(); visitor_monitor.connection = None
        database.start()
        require(' saved.' in owner.command('save'), 'Another job could not reconcile stopped creator')
        require(store.get(key).words[7] != roy_password, 'Recovery incorrectly credited visitor password as owner save')
        owner.quit()
        require(owner.enter(name, passwords[name])[0], 'Recovered owner password failed')
        owner.quit()
        report['cases']['stopped_creator'] = {'reconciled': True, 'owner_checkpoint': True}
    with login.Controller(machine.port) as owner_monitor, login.Controller(machine.port) as creator_monitor:
        owner, creator = LifecycleGame(owner_monitor, issuer), LifecycleGame(creator_monitor, issuer)
        name, key = 'Cjabort', pack_name('cjabort')
        owner.enter_new(name, passwords[name])
        require(creator.enter('Roy', passwords['Roy'])[0], 'Uncommitted creator login failed')
        attach(creator, name)
        hub.mode = 'prepare_unknown'
        require('outcome unknown' in creator.command('save'), 'Uncommitted creation not reproduced')
        creator_monitor.command('det')
        creator.accepted = False
        creator_monitor.command('kjob', b'Logged-off')
        creator_monitor.connection.close(); creator_monitor.connection = None
        database.start()
        require(' saved.' in owner.command('save'), 'Owner could not fence and replace uncommitted creation')
        require(store.create(*hub.delayed).status == 'ABORTED', 'Late dead-owner request bypassed fence')
        owner.quit()
        report['cases']['aborted_creator'] = True
    print('EXORCISE, slot reuse and stale CONT', flush=True)
    with login.Controller(machine.port) as a, login.Controller(machine.port) as b, \
            login.Controller(machine.port) as c, login.Controller(machine.port) as d:
        owner, visitor, wizard, newcomer = [LifecycleGame(m, issuer) for m in (a, b, c, d)]
        owner.enter_new('Crosscont', passwords['Crosscont'])
        require(' saved.' in owner.command('save'), 'CONT fixture save failed')
        before = store.get(pack_name('crosscont'))
        require(visitor.enter('Roy', passwords['Roy'])[0], 'CONT visitor login failed')
        attach(visitor, 'Crosscont')
        b.command('det'); visitor.accepted = False
        require(wizard.enter('Brian', passwords['Brian'])[0], 'EXORCISE operator login failed')
        require('is no more' in wizard.command('exorcise crosscont'), 'EXORCISE failed')
        require(store.get(pack_name('crosscont')) == before, 'EXORCISE invented persistence')
        newcomer.enter_new('Slotfresh', passwords['Slotfresh'])
        require(' saved.' in newcomer.command('save'), 'Replacement slot save failed')
        replacement = store.get(pack_name('slotfresh'))
        require('no longer active' in b.command('cont'), 'Stale CONT entered a recycled persona')
        a.send('save')
        data = a.connection.read_until(b'\n.', 25)
        require(data.endswith(b'\n.'), 'Exorcised original job did not finish')
        a.at_monitor = True; owner.accepted = False
        require(store.get(pack_name('crosscont')) == before and store.get(pack_name('slotfresh')) == replacement,
                'Retired session mutated an old or replacement persona')
        newcomer.quit(); wizard.quit()
        report['cases']['exorcise_stale_cont'] = {'no_save': True, 'replacement_unchanged': True}
    print('External two-world round trips', flush=True)
    with login.Controller(machine.port) as monitor:
        game = LifecycleGame(monitor, issuer)
        for name in ('Chainnew', 'Ninechars', 'Chainack'):
            key = pack_name(name.lower())
            game.enter_new(name, passwords[name])
            require(store.get(key) is None, 'Chain admission persisted prematurely')
            if name == 'Chainack': hub.mode = 'after'
            monitor.send('e')
            response = monitor.connection.read_until(game.prompt, 25).decode('ascii', errors='replace')
            if response.endswith('\n.'):
                monitor.at_monitor = True
                print('Handover lookup PPN:', monitor.command('examine 77', b'.'), flush=True)
                print('Handover lookup tail:', monitor.command('examine 101', b'.'), flush=True)
            if 'Narrow road between lands' not in response:
                print(native.command('systat'), flush=True)
                print(native.command('directory valley.*'), flush=True)
            require('Narrow road between lands' in response, 'External chain did not arrive: ' + repr(response))
            require('VALLEY' in native.command('systat'), 'Destination image not running')
            first = store.get(key)
            require(first is not None and first.words[0] & ((1 << 18)-1) == 1, 'First-game chain did not create once')
            response = game.command('e')
            require('Narrow road between lands' in response, 'External return chain did not arrive')
            second = store.get(key)
            require(first.words[:5] + first.words[6:] == second.words[:5] + second.words[6:],
                    'Round trip changed persona except timestamp')
            game.quit()
            require(game.enter(name, passwords[name])[0], 'Chained persona password failed on ordinary re-entry')
            game.quit()
            report['cases'][name] = {'round_trip': True, 'games_not_incremented_on_chain': True}
        game.enter_new('Chainfail', passwords['Chainfail'])
        database.pause()
        try:
            monitor.send('e')
            failed = monitor.connection.read_until(b'\n.', 30)
            require(failed.endswith(b'\n.') and b'handover not confirmed' in failed, 'Unconfirmed source checkpoint launched destination')
            monitor.at_monitor = True; game.accepted = False
        finally: database.resume()
        require(store.get(pack_name('chainfail')) is None, 'Failed chain created a persona')
        report['cases']['chain_outage'] = True
    print('Gateway cleanup on external sessions', flush=True)
    for mode in ('normal', 'lost_reply', 'password', 'purge', 'creation_question'):
        with login.Controller(machine.port) as monitor:
            game = LifecycleGame(monitor, issuer)
            if mode == 'creation_question':
                issuer.load(monitor)
                monitor.command('start', b'By what name shall I call you?'); monitor.receive(b'*')
                monitor.send('Cleansex'); monitor.receive(b'What sex do you wish to be?'); monitor.receive(b'*')
            else:
                require(game.enter('Roy', passwords['Roy'])[0], 'Cleanup fixture login failed')
                if mode == 'lost_reply': hub.mode = 'after'
                elif mode == 'password':
                    monitor.send('password'); monitor.receive(b'What is your present password?'); monitor.receive(b'*')
                elif mode == 'purge':
                    monitor.send('purge crossold'); monitor.receive(b'Save, delete or finish? ')
            target = store.get(pack_name('crossold'))
            gateway_cleanup(monitor)
            require(store.get(pack_name('crossold')) == target, 'Cleanup changed the selected PURGE target')
            require(store.get(pack_name('cleansex')) is None, 'Interrupted creation question persisted a persona')
            report['cases']['cleanup_' + mode] = True


def run(output):
    def lifecycle_prepare(local, upstream, build, **options):
        return prepare(local, upstream, build, external_lifecycle=True, chain_targets=('mud', 'valley'))
    def native_controls(machine, native, passwords):
        return {}, native_crossjob(machine, native, passwords)
    challenges = set()
    recovery = {}
    class ObservedHub(AdminHub):
        def __init__(self, machine, ports, store, database):
            super().__init__(machine, ports, store, database)
            recovery.update(directory=machine.directory, ports=dict(ports), database=database,
                            config=MariaDbConfig(**store.configuration))
    receive = WriteSession.receive
    def checked_receive(session, line):
        if line.startswith(b'H1 HELLO '):
            digest = hashlib.sha256(line).digest()
            require(digest not in challenges, 'Bridge challenge reused across job/image handover')
            challenges.add(digest)
        return receive(session, line)
    with patch.object(creation, 'NEW_NAMES', NAMES), patch.object(creation, 'prepare', lifecycle_prepare), \
            patch.object(creation, 'native_controls', native_controls), patch.object(creation, 'exercise', exercise), \
            patch.object(creation, 'CreationHub', ObservedHub), patch.object(creation, 'build_guest', build_guest), \
            patch.object(WriteSession, 'receive', checked_receive):
        creation.run(output)
        report_path = output / 'report.json'
        report = json.loads(report_path.read_text())
        report['complete'] = False
        report_path.write_text(json.dumps(report, indent=2) + '\n')
        try:
            crash_recovery(output, recovery, report)
            report.update(complete=True, unique_handshake_challenges=len(challenges))
        finally:
            report_path.write_text(json.dumps(report, indent=2) + '\n')


def crash_recovery(output, context, report):
    """Restore the saved checkpoint after loss of an ungracefully stopped guest."""
    output = output.resolve()
    print('Guest-loss checkpoint recovery', flush=True)
    database = context['database']
    config, ports = context['config'], context['ports']
    private = json.loads(context.get('fixture_path', output / 'private-fixtures.json').read_text())
    clean_disk = context['directory'] / 'guest.dsk'  # Prior run completed KSYS and stopped SIMH.
    machine = None
    database.start()
    try:
        with isolated_writer(config) as store:
            for phase in ('crash', 'recover'):
                # A SIGKILL can leave the old raw listener ports in TIME_WAIT.
                # Recovery uses newly configured private listeners, not a retry
                # of an old transport session or stale response queue.
                with ExitStack() as reservations:
                    ports = {}
                    for line in context['ports']:
                        connection = reservations.enter_context(socket.socket())
                        connection.bind(('127.0.0.1', 0))
                        ports[line] = connection.getsockname()[1]
                directory = output / (phase + '-machine')
                directory.mkdir(mode=0o700)
                shutil.copyfile(clean_disk, directory / 'guest.dsk')
                for attempt in range(MAX_BOOT_ATTEMPTS):
                    sessions = ExitStack()
                    machine = private_emulator(directory, ports, reuse=True)
                    try:
                        machine.boot(); machine.command('daytime')
                        hub = sessions.enter_context(AdminHub(machine, ports, store, database))
                        monitor = sessions.enter_context(login.Controller(machine.port))
                        break
                    except Exception:
                        sessions.close()
                        machine.stop(); machine = None
                        if attempt + 1 == MAX_BOOT_ATTEMPTS: raise
                with sessions:
                    game = LifecycleGame(monitor, SeedIssuer())
                    require(game.enter('Chainnew', private['passwords']['Chainnew'])[0], 'Checkpoint recovery login failed')
                    if phase == 'crash':
                        require(' saved.' in game.command('save'), 'Crash checkpoint was not confirmed')
                        checkpoint = store.get(pack_name('chainnew'))
                        route(game.command)
                        require('Score to date: 11' in game.command('score'), 'No post-checkpoint unsaved progress')
                        require(store.get(pack_name('chainnew')) == checkpoint, 'Gameplay wrote without checkpoint')
                        hub.stopping = True
                        machine.child.kill(signal.SIGKILL)
                        machine.child.wait()
                        monitor.connection.close(); monitor.connection = None
                    else:
                        require('Score to date: 0' in game.command('score'), 'Guest loss restored unconfirmed progress')
                        require(store.get(pack_name('chainnew')) == checkpoint, 'Fresh guest changed committed checkpoint at login')
                        game.quit()
                machine.stop(); machine = None
            report['cases']['guest_loss'] = {'confirmed_checkpoint_restored': True, 'unsaved_progress_not_invented': True}
    finally:
        if machine is not None: machine.stop()
        database.stop()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=creation.ROOT / 'runtime' / f'external-lifecycle-{time.time_ns()}')
    run(parser.parse_args().output.resolve())
