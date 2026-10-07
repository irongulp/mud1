"""Original character creation with atomic external first persistence."""
import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import re
import secrets
import socket
import time
from unittest.mock import patch

from tools.audit_archwizards import Guest, ARCHWIZARDS, MAX_BOOT_ATTEMPTS, logoff
from tools.inspect_game import NativeInspector
from tools.persona_bootstrap import SeedIssuer
from tools.persona_protocol import pack_name, LogicalRecord
from tools.persona_writes import isolated_writer, WriteResult
from tools.prepare import prepare
from tools.provision_archwizards import generate_password
from tests.integration_external_login import baseline, export_records, build_guest, transfer, Controller, ORDINARY
from tests.integration_external_exit import ExitGame
from tests.integration_external_death import DeathHub, death_output
from tests.integration_external_save import private_export, route
from tests.integration_persona_writes import enable_writes
from tests.integration_persona_creates import generation
from tests.integration_storage_bridge import ROOT, BRIDGE_LINES, private_emulator
from tests.integration_provisioning import source_hashes, require
from tests.mariadb_fixture import LocalMariaDb

NEW_NAMES = ('Newsaver', 'Newquit', 'Newnone', 'Newattach', 'Newdrop', 'Newunk',
             'Newabort', 'Newclash', 'Newlost', 'Newdead', 'Newoutage')


def profile(text):
    values = {}
    for name, pattern in (('score', r'Score to date:\s*(-?\d+)'), ('strength', r'Strength:\s*(\d+)'),
                          ('stamina', r'Stamina:\s*(\d+)'), ('dexterity', r'Dexterity:\s*(\d+)'),
                          ('maximum', r'Maximum stamina:\s*(\d+)'), ('games', r'Games played to date:\s*(\d+)')):
        match = re.search(pattern, text)
        require(match is not None, 'Original SCORE omitted ' + name)
        values[name] = int(match[1])
    values['female'] = 'Sex: female' in text
    return values


def check_profile(record, shown):
    require(record.words[0] & ((1 << 18) - 1) == shown['games'], 'Persisted games differ from live profile')
    require(record.words[3] == shown['score'], 'Persisted score differs from live profile')
    require(record.words[1] & 1 == shown['female'], 'Persisted sex differs from live profile')
    packed = record.words[4]
    for shift, name in ((27, 'strength'), (18, 'dexterity'), (9, 'stamina'), (0, 'maximum')):
        require((packed >> shift) & 511 == shown[name], 'Persisted character differs: ' + name)
    require(record.words[8:] == (0, 0, 0), 'New logical record not initialized cleanly')


class CreationGame(ExitGame):
    def enter_new(self, name, password, sex='m'):
        self.issuer.load(self.monitor)
        self.monitor.command('start', b'By what name shall I call you?')
        self.monitor.receive(b'*'); self.monitor.send(name)
        self.monitor.receive(b'What sex do you wish to be?'); self.monitor.receive(b'*')
        self.monitor.connection.write(sex.encode('ascii'))
        self.monitor.receive(b'letters, please.'); self.monitor.receive(b'*')
        self.monitor.send(password)
        greeting = self.monitor.receive(b'\n*')
        require('Hello' in greeting, 'Original new-persona greeting missing')
        self.prompt, self.accepted = b'\n*', True


class CreationHub(DeathHub):
    allow_create = True

    def __init__(self, *args):
        super().__init__(*args)
        self.creates = []
        self.created = []  # Private in-memory proposals; never log password words.

    def begin_create(self, operation, key):
        self.creates.append(operation)
        return self.store.begin_create(operation, key)

    def create(self, operation, key, record):
        if self.mode == 'prepare_unknown':
            self.mode, self.drop = 'normal', True
            self.delayed = operation, key, record
            self.database.stop()
            return WriteResult('UNKNOWN')
        if self.mode == 'clash':
            self.mode = 'normal'
            competing = secrets.randbits(72) or 1
            while competing == operation: competing = secrets.randbits(72) or 1
            words = list(record.words); words[3] = 41; words[7] ^= 1
            self.competitor = LogicalRecord(words)
            require(self.store.begin_create(competing, key).status == 'OPEN', 'Competing create begin failed')
            require(self.store.create(competing, key, self.competitor).status == 'COMMITTED', 'Competing create failed')
        result = self.store.create(operation, key, record)
        if result.status == 'COMMITTED':
            self.created.append((operation, key, record))
            if self.mode in ('after', 'unknown'):
                previous = self.mode
                self.mode, self.drop = 'normal', True
                self.database.stop()
                if previous == 'after': self.database.start()
        return result


def native_controls(machine, native, passwords):
    goldens, observations = {}, {}
    for name, mode in (('Newsaver', 'save'), ('Newquit', 'quit'), ('Newnone', 'none')):
        guest = Guest(machine.port, 'mudguest', [])
        try:
            require(guest.authenticate(name, passwords[name], creating=True), 'Native new-persona admission failed')
            def command(text):
                guest.send(text); return guest.expect(b'\n*')
            require(pack_name(name.lower()) not in private_export(native), 'Native admission persisted before SAVE')
            if mode == 'quit': route(command)
            shown = profile(command('score'))
            if mode == 'save': guest.save(name)
            guest.close()
        finally:
            logoff(guest.connection)
        record = private_export(native).get(pack_name(name.lower()))
        if mode == 'none': require(record is None, 'Native zero-score QUIT persisted')
        else: check_profile(record, shown); goldens[name] = record
        observations[name] = shown
    guest = Guest(machine.port, 'mudguest', [])
    try:
        require(guest.authenticate('Roy', passwords['Roy']), 'Native ATTACH fixture login failed')
        guest.send('attach newattach')
        guest.expect(b'What sex do you wish to be?'); guest.expect(b'*')
        guest.connection.write(b'm')
        require('Attaching to Newattach' in guest.expect(b'\n*'), 'Native missing-target ATTACH failed')
        guest.send('save')
        require('Not to an attached persona!' in guest.expect(b'\n*'), 'Native attached SAVE restriction absent')
        guest.close()
    finally:
        logoff(guest.connection)
    require(pack_name('newattach') not in private_export(native), 'Native new ATTACH persisted')
    observations['Newattach'] = {'save_rejected': True, 'not_persisted': True}
    return goldens, observations


def exercise(machine, native, database, store, hub, passwords, controls, goldens, report):
    issuer = SeedIssuer()
    with Controller(machine.port) as monitor, Controller(machine.port) as killer_monitor:
        game, killer = CreationGame(monitor, issuer), CreationGame(killer_monitor, issuer)
        for name in (*ARCHWIZARDS, ORDINARY):
            for correct in (False, True):
                accepted, _ = game.enter(name, passwords[name] if correct else 'wrongxyz')
                require(accepted == controls[name + (' correct' if correct else ' wrong')], 'Creation build changed authentication')
                if accepted: game.quit()
        report['authentication_comparisons'] = 16
        for name, mode in (('Newsaver', 'save'), ('Newquit', 'quit'), ('Newnone', 'none')):
            print('Creation comparison:', name, flush=True)
            key = pack_name(name.lower())
            game.enter_new(name, passwords[name])
            require(store.get(key) is None, 'External admission prematurely persisted')
            if mode == 'quit': route(game.command)
            shown = profile(game.command('score'))
            if mode == 'save': require(' saved.' in game.command('save'), 'First explicit SAVE failed')
            game.quit()
            record = store.get(key)
            if mode == 'none': require(record is None, 'Zero-score new QUIT persisted')
            else:
                check_profile(record, shown)
                # RAN and LSTM differ between runs. All other serialized fields,
                # including original password and PPN, must match native creation.
                expected = goldens[name]
                require(record.words[:4] + record.words[6:] == expected.words[:4] + expected.words[6:],
                        'Creation fields differ from native (excluding random stats/time)')
                require(game.enter(name, 'wrongxyz')[1] == 'rejected', 'Wrong new password accepted')
                accepted, outcome = game.enter(name, passwords[name])
                require(accepted, 'New persona password re-entry failed: ' + outcome)
                require(profile(game.command('score'))['score'] == shown['score'], 'First checkpoint did not restore score')
                game.quit()
            report['cases'][name] = shown
        require(game.enter('Roy', passwords['Roy'])[0], 'External ATTACH fixture login failed')
        monitor.send('attach newattach')
        monitor.receive(b'What sex do you wish to be?'); monitor.receive(b'*')
        monitor.connection.write(b'm')
        require('Attaching to Newattach' in monitor.receive(b'\n*'), 'External missing-target ATTACH failed')
        game.prompt = b'\n*'
        require('Not to an attached persona!' in game.command('save'), 'Attached SAVE gate changed')
        game.quit()
        require(store.get(pack_name('newattach')) is None, 'New attached persona persisted')
        report['cases']['Newattach'] = {'not_persisted': True}
        for name, mode in (('Newdrop', 'after'), ('Newunk', 'unknown'), ('Newabort', 'prepare_unknown'), ('Newclash', 'clash')):
            print('Creation failure case:', mode, flush=True)
            key = pack_name(name.lower())
            game.enter_new(name, passwords[name], sex='f')
            shown = profile(game.command('score'))
            count = len(hub.creates)
            hub.mode = mode
            response = game.command('save')
            if mode in ('unknown', 'prepare_unknown'):
                require('outcome unknown' in response, 'Ambiguous creation not reproduced')
                database.start()
                response = game.command('save')
                if mode == 'unknown':
                    require('Previous SAVE committed' in response, 'Pending creation not recovered')
                else:
                    require('Previous SAVE did not commit' in response, 'Aborted creation falsely recovered')
                    require(store.get(key) is None, 'Aborted creation published')
                    require(store.create(*hub.delayed).status == 'ABORTED', 'Late creation bypassed fence')
                    require(' saved.' in game.command('save'), 'Fresh attempt after abort failed')
            elif mode == 'clash':
                require(' saved.' not in response and store.get(key) == hub.competitor, 'Conflicting create overwrote winner')
            else: require(' saved.' in response, 'Lost create acknowledgement did not resolve')
            if mode != 'clash': check_profile(store.get(key), shown)
            require(len(hub.creates) == count + (2 if mode in ('prepare_unknown', 'clash') else 1), 'Unexpected creation attempt count')
            game.quit()
            report['cases'][name] = {'mode': mode, 'passed': True}
        # A saved persona removed during this session is not a new admission.
        name, key = 'Newlost', pack_name('newlost')
        game.enter_new(name, passwords[name])
        require(' saved.' in game.command('save'), 'Missing-record fixture SAVE failed')
        count = len(hub.creates)
        op = secrets.randbits(72) or 1
        store.begin_delete(op, key)
        require(store.delete(op, key).status == 'COMMITTED', 'Missing-record fixture delete failed')
        exited = game.quit()
        require('External persona missing' in exited['output'], 'Missing saved identity did not fail as an update')
        require(store.get(key) is None and len(hub.creates) == count, 'Missing saved identity reached CREATE')
        report['cases'][name] = {'not_recreated': True}
        require(killer.enter('Brian', passwords['Brian'])[0], 'Death fixture killer login failed')
        name, key = 'Newdead', pack_name('newdead')
        game.enter_new(name, passwords[name])
        require(' saved.' in game.command('save'), 'Death fixture first SAVE failed')
        old_generation = generation(database, key)
        old_create = hub.created[-1]
        killer.command('fod ' + name)
        death_output(monitor.connection); monitor.at_monitor = True; game.accepted = False
        require(store.get(key) is None, 'Newly saved persona death did not delete')
        game.enter_new(name, passwords[name])
        require(' saved.' in game.command('save'), 'Recreation after death failed')
        replacement = store.get(key)
        require(generation(database, key) != old_generation, 'Recreation reused generation')
        require(store.create(*old_create).status == 'COMMITTED' and store.get(key) == replacement, 'Old creation overwrote reincarnation')
        game.quit(); killer.quit()
        report['cases'][name] = {'death_and_recreation': True}
        database.pause()
        try:
            require(game.enter('Newoutage', passwords['Newoutage'])[1] == 'unavailable', 'Outage entered creation flow')
        finally: database.resume()
        require(store.get(pack_name('newoutage')) is None, 'Outage created phantom persona')
        report['cases']['Newoutage'] = {'not_created': True}


def run(output):
    output.mkdir(mode=0o700)
    build = ROOT / 'build' / output.name
    prepare(ROOT / 'source', ROOT / 'upstream/mud1', build, external_creation=True)
    original = source_hashes()
    report = {'complete': False, 'build': str(build), 'cases': {}}
    machine = None
    try:
        with ExitStack() as stack:
            ports = {}
            for line in BRIDGE_LINES:
                connection = stack.enter_context(socket.socket())
                connection.bind(('127.0.0.1', 0)); ports[line] = connection.getsockname()[1]
        for attempt in range(MAX_BOOT_ATTEMPTS):
            print('External creation boot:', attempt + 1, flush=True)
            machine = private_emulator(output / f'machine-{attempt+1}', ports)
            try:
                machine.boot(); machine.command('daytime'); break
            except Exception:
                machine.stop(); machine = None
                if attempt + 1 == MAX_BOOT_ATTEMPTS: raise
        passwords = {name: generate_password() for name in (*ARCHWIZARDS, ORDINARY, *NEW_NAMES)}
        controls = baseline(machine.port, {name: passwords[name] for name in (*ARCHWIZARDS, ORDINARY)})
        with NativeInspector(machine.port) as native:
            native.command('assign dsk: bcl:'); native.command('set tty no altmode')
            initial = export_records(native)
            goldens, report['native'] = native_controls(machine, native, passwords)
            fd = os.open(output / 'private-fixtures.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as private:
                json.dump({'passwords': passwords, 'controls': controls,
                           'initial': {name: initial[pack_name(name.lower())].words for name in (*ARCHWIZARDS, ORDINARY)},
                           'goldens': {name: record.words for name, record in goldens.items()}}, private)
            native.command('copy crbase.pm=mud.?pm')
            transfer(native, 'mudlib.get', (build / 'MUDLIB.GET').read_text())
            receive = native.receive
            def build_receive(marker):
                text = receive(marker)
                with (output / 'build.txt').open('a') as log: log.write(text)
                return text
            native.receive = build_receive
            try:
                with patch('tests.integration_external_login.DATA_BASE', 0o520000):
                    build_guest(machine, native, build, output)
            finally: native.receive = receive
            native.command('rename pmhold.pm=mud.?pm')
        machine.command('r opr', 'OPR>')
        machine.child.send('set ksys now\r')
        machine.child.expect_exact('KSYS processing completed', timeout=120)
        directory = machine.directory
        machine.stop(); machine = None
        report['clean_build_shutdown'] = True
        for attempt in range(MAX_BOOT_ATTEMPTS):
            print('Creation image reboot:', attempt + 1, flush=True)
            machine = private_emulator(directory, ports, reuse=True)
            try:
                machine.boot(); machine.command('daytime'); break
            except Exception:
                machine.stop(); machine = None
                if attempt + 1 == MAX_BOOT_ATTEMPTS: raise
        with NativeInspector(machine.port) as native:
            with LocalMariaDb(output / 'database') as database:
                for name in (*ARCHWIZARDS, ORDINARY): database.seed(name.lower(), initial[pack_name(name.lower())].words)
                config = enable_writes(database, allow_delete=True, allow_create=True)
                with isolated_writer(config) as store, patch('tools.persona_write_session.IDLE_TIMEOUT', 600), \
                        CreationHub(machine, ports, store, database) as hub:
                    exercise(machine, native, database, store, hub, passwords, controls, goldens, report)
                    require(not hub.errors and not store.worker_pids, 'Creation left transport/worker failure')
                    report['creation_attempts'] = len(hub.creates)
            native.command('r filcom', b'\n*')
            text = native.command('tty:=crbase.pm,pmhold.pm/b', b'\n*')
            require('No differences encountered' in text, 'External creation touched retained native personas')
            native.connection.write(b'\x1a'); native.receive(b'\n.'); native.at_monitor = True
        machine.command('r opr', 'OPR>')
        machine.child.send('set ksys now\r')
        machine.child.expect_exact('KSYS processing completed', timeout=120)
        report['clean_final_shutdown'] = True
        require(source_hashes() == original, 'Original source changed')
        report.update(complete=True, source_unchanged=True, native_personas_unchanged=True)
        print('External creation checks complete:', output, flush=True)
    except BaseException as error:
        report['error_type'] = type(error).__name__
        raise
    finally:
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        if machine is not None: machine.stop()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'runtime' / f'external-creation-{time.time_ns()}')
    run(parser.parse_args().output.resolve())
