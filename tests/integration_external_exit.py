"""Eligible exit updates compared with native QUIT, on disposable runtimes."""
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
from tools.persona_mariadb import encode_key
from tools.persona_protocol import pack_name, WORD_MASK
from tools.persona_writes import isolated_writer, WriteResult
from tools.prepare import prepare
from tools.provision_archwizards import generate_password
from tests.integration_external_login import baseline, export_records, build_guest, transfer, Game, Controller, ORDINARY
from tests.integration_external_save import private_export, route, same_native, SaveHub
from tests.integration_persona_writes import enable_writes, revision
from tests.integration_storage_bridge import ROOT, BRIDGE_LINES, private_emulator
from tests.integration_provisioning import source_hashes, require
from tests.mariadb_fixture import LocalMariaDb, DATABASE

EXIT_BOUND = 25
EXTRA_PERSONAS = ('Exitidle', 'Gali', 'Exitpend', 'Exitdrop', 'Exitfail', 'Exithold', 'Exitguard', 'Exitprom')


class ExitGame(Game):
    def quit(self):
        require(self.accepted, 'No active game to exit')
        started = time.monotonic()
        self.monitor.send('quit')
        data = self.monitor.connection.read_until(b'\n.', EXIT_BOUND)
        require(data.endswith(b'\n.'), 'Exit did not finish at the monitor (possible teardown re-entry)')
        self.monitor.at_monitor = True
        self.accepted = False
        elapsed = time.monotonic() - started
        require(elapsed < EXIT_BOUND, 'Exit exceeded its host bound')
        return {'seconds': round(elapsed, 3), 'output': data.decode('ascii', errors='replace')}


class ExitHub(SaveHub):
    def commit(self, operation, key, record):
        if self.mode == 'prepare_unknown':
            self.mode, self.drop = 'normal', True
            self.delayed = operation, key, record
            self.database.stop()
            return WriteResult('UNKNOWN')
        return super().commit(operation, key, record)


def native_controls(port, native, passwords, initial):
    results = {}
    for name in (ORDINARY, 'Exitidle', 'Gali'):
        guest = Guest(port, 'mudguest', [])
        try:
            require(guest.authenticate(name, passwords[name]), 'Native exit control login failed')
            if name == ORDINARY:
                def command(text):
                    guest.send(text); return guest.expect(b'\n*')
                route(command)
            guest.close()
        finally:
            logoff(guest.connection)
        results[name] = private_export(native)[pack_name(name.lower())]
    require(results['Gali'] == initial[pack_name('gali')], 'Native excluded-name control unexpectedly persisted')
    for explicit in (False, True):
        guest = Guest(port, 'mudguest', [])
        try:
            require(guest.authenticate('Roy', passwords['Roy']), 'Native Roy control failed')
            if explicit:
                guest.save('Roy')
            require(guest.attach('Richard', passwords['Richard'])['accepted'], 'Native ATTACH control failed')
            guest.close()
        finally:
            logoff(guest.connection)
        result = private_export(native)[pack_name('richard')]
        if not explicit:
            require(result == initial[pack_name('richard')], 'Native first-game zero-score ATTACH exit wrote data')
        results['attached_saved' if explicit else 'attached_unsaved'] = result
    return results


def admin_words(database, name, words, *, reset=False):
    with database.admin() as connection, connection.cursor() as cursor:
        if reset:
            cursor.execute('UPDATE ' + DATABASE + '.personas SET words=%s,generation=%s,revision=1 '
                           'WHERE namespace=%s AND name_key=%s',
                           (json.dumps(words), secrets.token_bytes(9), b'mud', encode_key(pack_name(name.lower()))))
        else:
            cursor.execute('UPDATE ' + DATABASE + '.personas SET words=%s WHERE namespace=%s AND name_key=%s',
                           (json.dumps(words), b'mud', encode_key(pack_name(name.lower()))))


def exercise(machine, native, database, store, hub, passwords, controls, initial, goldens, report):
    issuer = SeedIssuer()
    with Controller(machine.port) as monitor:
        game = ExitGame(monitor, issuer)
        for name in (*ARCHWIZARDS, ORDINARY):
            for correct in (False, True):
                accepted, outcome = game.enter(name, passwords[name] if correct else 'wrongxyz')
                expected = controls[name + (' correct' if correct else ' wrong')]
                require(accepted == expected and outcome == ('accepted' if expected else 'rejected'), 'Exit build authentication changed')
                if accepted:
                    game.quit()
        report['authentication_comparisons'] = 16
        # Authentication's correct logins legitimately update game counts on
        # QUIT. Restore controlled initial fixtures with fresh generations before
        # differential lifecycle comparisons; no operation ids are reused.
        for name in passwords:
            admin_words(database, name, initial[pack_name(name.lower())].words, reset=True)
        for name in (ORDINARY, 'Exitidle', 'Gali'):
            print('Native/external QUIT comparison:', name, flush=True)
            before = store.get(pack_name(name.lower()))
            count = len(hub.operations)
            require(game.enter(name, passwords[name])[0], 'External exit control login failed')
            if name == ORDINARY:
                route(game.command)
            exited = game.quit()
            after = store.get(pack_name(name.lower()))
            if name == 'Gali':
                require(after == before and len(hub.operations) == count, 'Excluded name reached storage')
                require('Not updating persona.' in exited['output'], 'Native skip message changed')
            else:
                same_native(after, goldens[name])
                require(len(hub.operations) == count + 1, 'Eligible exit did not issue exactly one checkpoint')
            report['cases'][name] = exited
        require(game.enter(ORDINARY, passwords[ORDINARY])[0], 'Automatic checkpoint re-entry failed')
        score = re.search(r'Score to date:\s*(\d+)', game.command('score'))
        require(score and int(score[1]) == goldens[ORDINARY].words[3], 'QUIT score did not persist')
        game.quit()
        report['restored_score'] = int(score[1])

        for explicit in (False, True):
            require(game.enter('Roy', passwords['Roy'])[0], 'Roy login failed')
            if explicit:
                require('saved.' in game.command('save'), 'Roy explicit checkpoint failed')
            before = store.get(pack_name('richard'))
            count = len(hub.operations)
            monitor.send('attach richard'); monitor.receive(b"What's the password for this persona?")
            monitor.send(passwords['Richard'])
            require('Attaching to Richard' in monitor.receive(game.prompt), 'External ATTACH failed')
            exited = game.quit()
            after = store.get(pack_name('richard'))
            if explicit:
                same_native(after, goldens['attached_saved'])
                require(len(hub.operations) == count + 1, 'Prior SAVE did not qualify attached QUIT')
            else:
                require(after == before and len(hub.operations) == count, 'Unsaved zero-score attached persona persisted')
            report['cases']['attached_saved' if explicit else 'attached_unsaved'] = exited

        for name, mode in (('Exitfail', 'unavailable'), ('Exitdrop', 'after'),
                           ('Exitdrop', 'exit_unknown'), ('Exithold', 'pending_unknown')):
            print('Exit failure case:', mode, flush=True)
            key = pack_name(name.lower())
            before = store.get(key)
            rev = revision(database, key)
            require(game.enter(name, passwords[name])[0], 'Failure fixture login failed')
            if mode == 'unavailable':
                database.pause()
            elif mode in ('after', 'exit_unknown'):
                hub.mode = 'after' if mode == 'after' else 'unknown'
            else:
                hub.mode = 'unknown'
                require('outcome unknown' in game.command('save'), 'Pending explicit SAVE was not reproduced')
            operations = len(hub.operations)
            try:
                exited = game.quit()
            finally:
                if mode == 'unavailable':
                    database.resume()
                elif mode in ('pending_unknown', 'exit_unknown'):
                    database.start()
            if mode == 'unavailable':
                require('checkpoint not confirmed' in exited['output'], 'Known exit failure was not reported')
                require(store.get(key) == before and revision(database, key) == rev, 'Unavailable exit changed persona')
            elif mode == 'after':
                require('UNKNOWN' not in exited['output'], 'Committed exit did not resolve')
                require(revision(database, key) == rev + 1, 'Lost exit acknowledgement wrote twice')
            else:
                require('exit outcome UNKNOWN' in exited['output'], 'Ambiguous exit was falsely classified')
                require(len(hub.operations) == operations + (mode == 'exit_unknown'), 'Unknown exit issued an extra write')
                require(store.resolve(hub.operations[-1]).status == 'COMMITTED', 'Old explicit save outcome disappeared')
                require(revision(database, key) == rev + 1, 'Unknown exit replayed mutation')
            report['cases'][mode] = exited

        # An aborted pending SAVE must not set savedp and accidentally qualify
        # this existing first-game, zero-score ATTACH target for exit storage.
        admin_words(database, 'Richard', initial[pack_name('richard')].words, reset=True)
        require(game.enter('Roy', passwords['Roy'])[0], 'Abort fixture login failed')
        monitor.send('attach richard'); monitor.receive(b"What's the password for this persona?")
        monitor.send(passwords['Richard'])
        require('Attaching to Richard' in monitor.receive(game.prompt), 'Abort fixture ATTACH failed')
        before = store.get(pack_name('richard'))
        hub.mode = 'prepare_unknown'
        require('outcome unknown' in game.command('save'), 'Pending uncommitted SAVE was not reproduced')
        operations = len(hub.operations)
        database.start()
        exited = game.quit()
        require('Not updating persona.' in exited['output'], 'Aborted save changed native exit eligibility')
        require(len(hub.operations) == operations and store.get(pack_name('richard')) == before,
                'Aborted pending SAVE caused an exit mutation')
        require(store.commit(*hub.delayed).status == 'ABORTED', 'Exit resolution failed to fence the delayed request')
        report['cases']['pending_aborted_skips_exit'] = exited

        # A resolved old checkpoint must not mistake later gameplay for saved
        # state: use its serialized score for the ensuing native score guard.
        native.command('rename dskb:mud.exe[2011,2776]=dskb:mud.exe[2011,2776]')
        key = pack_name('exitpend')
        require(game.enter('Exitpend', passwords['Exitpend'])[0], 'Pending fixture login failed')
        rev = revision(database, key)
        hub.mode = 'unknown'
        require('outcome unknown' in game.command('save'), 'Pending save setup failed')
        route(game.command)
        current = re.search(r'Score to date:\s*(\d+)', game.command('score'))
        require(current and int(current[1]) > 0, 'No post-checkpoint gameplay change')
        database.start()
        exited = game.quit()
        require(revision(database, key) == rev + 2, 'QUIT did not resolve old SAVE then create its own checkpoint')
        require(store.get(key).words[3] == int(current[1]), 'Exit guard used later score instead of resolved checkpoint score')
        report['cases']['pending_resolved_then_exit'] = exited

        key = pack_name('exitguard')
        require(game.enter('Exitguard', passwords['Exitguard'])[0], 'Score guard fixture login failed')
        words = list(store.get(key).words); words[3] = WORD_MASK - 1  # -2 < initial savescr -1.
        admin_words(database, 'Exitguard', words)
        rev = revision(database, key)
        exited = game.quit()
        require('score seems to have changed' in exited['output'], 'Exit bypassed native score guard')
        require(revision(database, key) == rev, 'Rejected exit checkpoint mutated persona')
        report['cases']['score_guard'] = exited

        # Exercise the unmodified promotion prefix on an external fixture. This
        # branch is source-identical; it is not a separate native-file byte control.
        native.command('rename dskb:mud.exe[2011,2776]=dskb:mud.exe[2011,2776]')
        key = pack_name('exitprom')
        words = list(store.get(key).words); words[3] = 102399; words[6] &= ~(1 << 8)
        admin_words(database, 'Exitprom', words)
        require(game.enter('Exitprom', passwords['Exitprom'])[0], 'Promotion fixture login failed')
        route(game.command)
        exited = game.quit()
        require(store.get(key).words[6] & (1 << 8), 'Original exit promotion was not persisted')
        report['cases']['promotion'] = exited


def run(output):
    output.mkdir(mode=0o700)
    build = ROOT / 'build' / output.name
    prepare(ROOT / 'source', ROOT / 'upstream/mud1', build, external_exit_existing=True)
    original = source_hashes()
    report = {'complete': False, 'build': str(build), 'cases': {}}
    machine = None
    try:
        with ExitStack() as stack:
            reservations = [stack.enter_context(socket.socket()) for _ in BRIDGE_LINES]
            ports = {}
            for line, connection in zip(BRIDGE_LINES, reservations):
                connection.bind(('127.0.0.1', 0)); ports[line] = connection.getsockname()[1]
        for attempt in range(MAX_BOOT_ATTEMPTS):
            print('External exit boot:', attempt + 1, flush=True)
            machine = private_emulator(output / f'machine-{attempt+1}', ports)
            try:
                machine.boot(); machine.command('daytime'); break
            except Exception:
                machine.stop(); machine = None
                if attempt + 1 == MAX_BOOT_ATTEMPTS: raise
        passwords = {name: generate_password() for name in (*ARCHWIZARDS, ORDINARY, *EXTRA_PERSONAS)}
        controls = baseline(machine.port, passwords)
        with NativeInspector(machine.port) as native:
            native.command('assign dsk: bcl:'); native.command('set tty no altmode')
            initial = export_records(native)
            goldens = native_controls(machine.port, native, passwords, initial)
            fd = os.open(output / 'private-fixtures.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as private:
                json.dump({'passwords': passwords, 'controls': controls,
                           'initial': {name: initial[pack_name(name.lower())].words for name in passwords},
                           'goldens': {name: record.words for name, record in goldens.items()}}, private)
            native.command('copy exbase.pm=mud.?pm')
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
            finally:
                native.receive = receive
            native.command('rename pmhold.pm=mud.?pm')
            print('Exit image built; running lifecycle checks', flush=True)
            with LocalMariaDb(output / 'database') as database:
                for name in passwords:
                    database.seed(name.lower(), initial[pack_name(name.lower())].words)
                config = enable_writes(database)
                with isolated_writer(config) as store, patch('tools.persona_write_session.IDLE_TIMEOUT', 600), \
                        ExitHub(machine, ports, store, database) as hub:
                    exercise(machine, native, database, store, hub, passwords, controls, initial, goldens, report)
                    require(not hub.errors and not store.worker_pids, 'Exit left a transport/worker failure')
                    report['operations'] = len(hub.operations)
                database.stop(); database.start()
                with isolated_writer(config) as store:
                    require(store.get(pack_name(ORDINARY.lower())).words[3] == goldens[ORDINARY].words[3], 'Automatic checkpoint lost after restart')
            native.command('r filcom', b'\n*')
            text = native.command('tty:=exbase.pm,pmhold.pm/b', b'\n*')
            require('No differences encountered' in text, 'External exit touched retained native personas')
            native.connection.write(b'\x1a'); native.receive(b'\n.'); native.at_monitor = True
        require(source_hashes() == original, 'Original source changed')
        report.update(complete=True, source_unchanged=True, native_personas_unchanged=True)
        print('External exit checks complete:', output, flush=True)
    except BaseException as error:
        report['error_type'] = type(error).__name__
        raise
    finally:
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        if machine is not None: machine.stop()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'runtime' / f'external-exit-{time.time_ns()}')
    run(parser.parse_args().output.resolve())
