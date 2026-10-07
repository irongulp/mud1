"""Explicit existing-persona SAVE through W1, compared with native BCPL policy."""
import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import re
import socket
import time
from unittest.mock import patch

from tools.audit_archwizards import Guest, ARCHWIZARDS, MAX_BOOT_ATTEMPTS, logoff
from tools.inspect_game import NativeInspector
from tools.persona_bootstrap import SeedIssuer
from tools.persona_protocol import LogicalRecord, pack_name, WORD_MASK
from tools.persona_mariadb import encode_key
from tools.persona_writes import isolated_writer, WriteResult
from tools.persona_write_session import serve_personas
from tools.prepare import prepare
from tools.provision_archwizards import generate_password
from tests.integration_external_login import baseline, export_records, build_guest, transfer, Game, Controller, ORDINARY
from tests.integration_persona_read import Hub
from tests.integration_persona_writes import enable_writes, revision
from tests.integration_storage_bridge import ROOT, BRIDGE_LINES, private_emulator
from tests.integration_provisioning import source_hashes, require
from tests.mariadb_fixture import LocalMariaDb, DATABASE


def private_export(native):
    # ROEXP has already been installed. The controlled players are waiting for
    # input; no persona writer runs while this private snapshot is collected.
    text = native.command('run roexp')
    records = {}
    for line in text.splitlines():
        if line.startswith('ROW '):
            record = LogicalRecord(tuple(int(word, 8) & WORD_MASK for word in line.split()[1:]))
            records[record.name_words] = record
    require('ROEXP END' in text, 'Incomplete private snapshot')
    return records


def route(command):
    for move, room in (('w', 'Narrow road.'), ('w', 'Road opposite cottage.'), ('s', 'Path.'),
                       ('s', 'Hall.'), ('u', 'Halfway up the stairs.'), ('u', 'Upstairs landing.'),
                       ('s', 'Large bedroom.')):
        require(room in command(move), 'Native route failed')
    command('make bed')
    require('unmake the bed' in command('unmake bed'), 'Native scoring action failed')


def native_goldens(port, native, passwords):
    guest = Guest(port, 'mudguest', [])
    try:
        require(guest.authenticate(ORDINARY, passwords[ORDINARY]), 'Native control login failed')
        def command(text):
            guest.send(text); return guest.expect(b'\n*')
        route(command)
        guest.save(ORDINARY)
        ordinary = private_export(native)[pack_name(ORDINARY.lower())]
        guest.close()
    finally:
        logoff(guest.connection)
    guest = Guest(port, 'mudguest', [])
    try:
        require(guest.authenticate('Roy', passwords['Roy']), 'Native Roy login failed')
        require(guest.attach('Richard', passwords['Richard'])['accepted'], 'Native Richard ATTACH failed')
        guest.save('Richard')
        attached = private_export(native)[pack_name('richard')]
        guest.close()
    finally:
        logoff(guest.connection)
    return ordinary, attached


class SaveGame(Game):
    def quit(self):
        if self.accepted:
            text = self.monitor.command('quit')
            require('automatic persistence unavailable' in text, 'Automatic persistence gate missing')
            self.accepted = False


class SaveHub(Hub):
    def __init__(self, machine, ports, store, database):
        super().__init__(machine, ports)
        self.store, self.database = store, database
        self.mode = 'normal'
        self.drop = False
        self.operations = []
        self.delayed = None

    def get(self, name):
        return self.store.get(name)

    def begin(self, operation, key):
        self.operations.append(operation)
        return self.store.begin(operation, key)

    def commit(self, operation, key, record):
        if self.mode == 'before':
            self.mode, self.drop = 'normal', True
            self.delayed = operation, key, record
            return WriteResult('UNKNOWN')  # Delivered later, after native resolution fences it.
        if self.mode == 'conflict':
            self.mode = 'normal'
            with self.database.admin() as connection, connection.cursor() as cursor:
                current = self.store.get(key)
                words = list(current.words)
                words[3] += 1
                cursor.execute('UPDATE ' + DATABASE + '.personas SET words=%s,revision=revision+1 '
                               'WHERE namespace=%s AND name_key=%s',
                               (json.dumps(words), b'mud', encode_key(key)))
        result = self.store.commit(operation, key, record)
        if result.status == 'COMMITTED' and self.mode in ('after', 'unknown'):
            previous = self.mode
            self.mode, self.drop = 'normal', True
            self.database.stop()
            if previous == 'after':
                self.database.start()
        return result

    def resolve(self, operation):
        return self.store.resolve(operation)

    def worker(self, line, channel):
        hub = self
        class FaultSocket:
            def settimeout(self, value): channel.settimeout(value)
            def recv(self, size): return channel.recv(size)
            def sendall(self, data):
                if data.startswith(b'W1 RESULT ') and hub.drop:
                    hub.drop = False
                    return
                channel.sendall(data)
        try:
            serve_personas(FaultSocket(), self, on_event=lambda state: self.events.append({'line': line, 'state': state}))
        except (OSError, ValueError, TimeoutError) as error:
            if not self.stopping:
                self.errors.append(type(error).__name__)


def same_native(actual, expected):
    # LSTM is generated by the original BCPL clock at the actual SAVE time.
    require(actual.words[:5] + actual.words[6:] == expected.words[:5] + expected.words[6:],
            'External persisted fields differ from original native SAVE')
    require(actual.words[5] >= expected.words[5], 'Native save timestamp did not advance')


def exercise(machine, database, store, hub, passwords, controls, golden, attached, report):
    issuer = SeedIssuer()
    with Controller(machine.port) as monitor:
        game = SaveGame(monitor, issuer)
        for name, password in passwords.items():
            for correct in (False, True):
                accepted, outcome = game.enter(name, password if correct else 'wrongxyz')
                expected = controls[name + (' correct' if correct else ' wrong')]
                require(accepted == expected and outcome == ('accepted' if expected else 'rejected'), 'Authentication changed')
                game.quit()
            print('External write-build authentication:', name, 'matched', flush=True)
        report['authentication_comparisons'] = len(controls)
        require(game.enter(ORDINARY, passwords[ORDINARY])[0], 'External ordinary login failed')
        route(game.command)
        print('External ordinary SAVE checkpoint', flush=True)
        before_revision = revision(database, pack_name(ORDINARY.lower()))
        response = game.command('save')
        require('Extguest saved.' in response, 'Explicit SAVE was not acknowledged: ' + response)
        saved = store.get(pack_name(ORDINARY.lower()))
        same_native(saved, golden)
        require(revision(database, saved.name_words) == before_revision + 1, 'SAVE revision count differs')
        report['native_fields_equivalent'] = True
        report['persisted_score'] = saved.words[3]
        require("haven't changed score" in game.command('save'), 'Unchanged-score policy changed')
        game.quit()
        require(game.enter(ORDINARY, passwords[ORDINARY])[0], 'Saved re-entry failed')
        score = re.search(r'Score to date:\s*(\d+)', game.command('score'))
        require(score and int(score[1]) == saved.words[3], 'Saved score did not survive re-entry')
        game.quit()
        require(game.enter('Roy', passwords['Roy'])[0], 'Roy login failed')
        for mode in ('before', 'after', 'unknown', 'conflict'):
            key = pack_name('roy')
            before = revision(database, key)
            hub.mode = mode
            print('Native write failure/concurrency case:', mode, flush=True)
            result = game.command('save')
            if mode == 'before':
                require(' saved.' not in result and 'did not complete' in result, 'Pre-commit loss was acknowledged')
                require(revision(database, key) == before, 'Pre-commit loss mutated data')
                require(store.commit(*hub.delayed).status == 'ABORTED', 'Delayed original commit bypassed native resolution')
            elif mode == 'after':
                require('Roy the arch-wizard saved.' in result, 'Lost acknowledgement did not resolve: ' + result)
                require(revision(database, key) == before + 1, 'Lost acknowledgement replay wrote twice')
            elif mode == 'unknown':
                require('outcome unknown' in result, 'Ambiguous save was falsely classified')
                require('Resolve the pending SAVE' in game.command('attach richard'), 'Pending save allowed persona switch')
                database.start()
                require('Previous SAVE committed' in game.command('save'), 'Explicit recovery lost durable result')
                require(revision(database, key) == before + 1, 'Recovery created a second mutation')
            else:
                require('Roy the arch-wizard saved.' in result, 'CAS conflict did not retry: ' + result)
                require(revision(database, key) == before + 2, 'CAS retry count differs (one admin change, one save)')
            report[mode] = 'passed'
        # Native signed score guard executes in BCPL, not in the SQL adapter.
        # Roy is a wizard, so unchanged-score admission does not mask this check.
        key = pack_name('roy')
        with database.admin() as connection, connection.cursor() as cursor:
            words = list(store.get(key).words)
            words[3] = WORD_MASK  # -1, less than the session's last saved score 0.
            cursor.execute('UPDATE ' + DATABASE + '.personas SET words=%s WHERE namespace=%s AND name_key=%s',
                           (json.dumps(words), b'mud', encode_key(key)))
        before = revision(database, key)
        result = game.command('save')
        require('score seems to have changed' in result and ' saved.' not in result, 'Native score guard was lost')
        require(revision(database, key) == before, 'Rejected score guard wrote data')
        report['score_guard'] = True
        game.quit()
        # Restore only the intentional administrative score fixture, then verify
        # the historical attached SAVE password/PN behavior against native bytes.
        with database.admin() as connection, connection.cursor() as cursor:
            words[3] = 0
            cursor.execute('UPDATE ' + DATABASE + '.personas SET words=%s WHERE namespace=%s AND name_key=%s',
                           (json.dumps(words), b'mud', encode_key(key)))
        require(game.enter('Roy', passwords['Roy'])[0], 'Roy re-entry failed')
        monitor.send('attach richard'); monitor.receive(b"What's the password for this persona?")
        monitor.send(passwords['Richard']); require('Attaching to Richard' in monitor.receive(game.prompt), 'ATTACH failed')
        require('Richard the arch-wizard saved.' in game.command('save'), 'Attached SAVE failed')
        same_native(store.get(pack_name('richard')), attached)
        report['attached_save_equivalent'] = True
        game.quit()


def run(output):
    output.mkdir(mode=0o700)
    build = ROOT / 'build' / output.name
    prepare(ROOT / 'source', ROOT / 'upstream/mud1', build, external_save_existing=True)
    original = source_hashes()
    machine = None
    report = {'complete': False, 'build': str(build)}
    try:
        with ExitStack() as stack:
            sockets = [stack.enter_context(socket.socket()) for _ in BRIDGE_LINES]
            ports = {}
            for line, sock in zip(BRIDGE_LINES, sockets):
                sock.bind(('127.0.0.1', 0)); ports[line] = sock.getsockname()[1]
        for attempt in range(MAX_BOOT_ATTEMPTS):
            machine = private_emulator(output / f'machine-{attempt+1}', ports)
            try:
                print('External SAVE boot:', attempt + 1, flush=True)
                machine.boot(); machine.command('daytime'); break
            except Exception:
                machine.stop(); machine = None
                if attempt + 1 == MAX_BOOT_ATTEMPTS: raise
        passwords = {name: generate_password() for name in (*ARCHWIZARDS, ORDINARY)}
        controls = baseline(machine.port, passwords)
        with NativeInspector(machine.port) as native:
            native.command('assign dsk: bcl:'); native.command('set tty no altmode')
            initial = export_records(native)
            golden, attached = native_goldens(machine.port, native, passwords)
            # Disposable credentials/records are a private restart checkpoint,
            # not an operator log or public evidence report.
            fd = os.open(output / 'private-fixtures.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as private:
                json.dump({'passwords': passwords, 'controls': controls,
                           'initial': {name: initial[pack_name(name.lower())].words for name in passwords},
                           'golden': golden.words, 'attached': attached.words}, private)
            native.command('copy wrbase.pm=mud.?pm')
            transfer(native, 'mudlib.get', (build / 'MUDLIB.GET').read_text())
            original_receive = native.receive
            def build_receive(marker):
                text = original_receive(marker)
                with (output / 'build.txt').open('a') as log:
                    log.write(text)
                return text
            native.receive = build_receive
            try:
                with patch('tests.integration_external_login.DATA_BASE', 0o520000):
                    build_guest(machine, native, build, output)
            finally:
                native.receive = original_receive
            native.command('rename pmhold.pm=mud.?pm')
            (output / 'build-complete.json').write_text(json.dumps({'machine': str(machine.directory), 'build': str(build)}) + '\n')
            print('Native write image built; starting database/game checks', flush=True)
            with LocalMariaDb(output / 'database') as database:
                for name in passwords:
                    database.seed(name.lower(), initial[pack_name(name.lower())].words)
                config = enable_writes(database)
                with isolated_writer(config) as store, patch('tools.persona_write_session.IDLE_TIMEOUT', 600), \
                        SaveHub(machine, ports, store, database) as hub:
                    exercise(machine, database, store, hub, passwords, controls, golden, attached, report)
                    require(not hub.errors, 'Write bridge failed')
                    require(not store.worker_pids, 'Write worker leaked')
                    report['operations'] = len(hub.operations)
                # A fresh getter after an actual database restart sees the saved checkpoint.
                database.stop(); database.start()
                with isolated_writer(config) as store:
                    require(store.get(pack_name(ORDINARY.lower())).words[3] == golden.words[3], 'Saved score lost on DB restart')
            native.command('r filcom', b'\n*')
            result = native.command('tty:=wrbase.pm,pmhold.pm/b', b'\n*')
            require('No differences encountered' in result, 'External SAVE changed retained native bytes')
            native.connection.write(b'\x1a'); native.receive(b'\n.'); native.at_monitor = True
        require(source_hashes() == original, 'Original source changed')
        report.update(complete=True, source_unchanged=True, native_personas_unchanged=True)
        print('External SAVE verified:', output, flush=True)
    except BaseException as error:
        report['error_type'] = type(error).__name__
        raise
    finally:
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        if machine is not None: machine.stop()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'runtime' / f'external-save-{time.time_ns()}')
    run(parser.parse_args().output.resolve())
