"""Original FOD death compared with generation-fenced external deletion."""
import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import secrets
import socket
import time
from unittest.mock import patch

from tools.audit_archwizards import Guest, ARCHWIZARDS, MAX_BOOT_ATTEMPTS, logoff
from tools.inspect_game import NativeInspector
from tools.persona_bootstrap import SeedIssuer
from tools.persona_protocol import pack_name
from tools.persona_mariadb import encode_key
from tools.persona_write_session import serve_personas
from tools.persona_writes import isolated_writer
from tools.prepare import prepare
from tools.provision_archwizards import generate_password, NativePersonas
from tests.integration_external_login import baseline, export_records, build_guest, transfer, Controller, ORDINARY
from tests.integration_external_exit import ExitGame, ExitHub, EXIT_BOUND
from tests.integration_external_save import private_export
from tests.integration_persona_writes import enable_writes
from tests.integration_storage_bridge import ROOT, BRIDGE_LINES, private_emulator
from tests.integration_provisioning import source_hashes, require
from tests.mariadb_fixture import LocalMariaDb, DATABASE

VICTIMS = ('Mortal', 'Gali', 'Ddrop', 'Dunknown', 'Ddown', 'Dpending', 'Dmissing', 'Dreplace')
ATTACHED = ('Dskip', 'Dsaved', 'Dabort', 'Dresolve')


def death_output(connection):
    started = time.monotonic()
    data = connection.read_until(b'\n.', EXIT_BOUND)
    require(data.endswith(b'\n.'), 'Death did not return to monitor within bound')
    text = data.decode('ascii', errors='replace')
    require('finger of death' in text.lower(), 'Original FOD death was not observed')
    return {'seconds': round(time.monotonic() - started, 3), 'output': text}


class DeathHub(ExitHub):
    allow_create = False
    allow_admin = False
    def __init__(self, *args):
        super().__init__(*args)
        self.deletions = []

    def begin_delete(self, operation, key):
        self.deletions.append(operation)
        return self.store.begin_delete(operation, key)

    def delete(self, operation, key):
        if self.mode == 'replace':
            self.mode = 'normal'
            with self.database.admin() as connection, connection.cursor() as cursor:
                cursor.execute('UPDATE ' + DATABASE + '.personas SET generation=%s '
                               'WHERE namespace=%s AND name_key=%s',
                               (secrets.token_bytes(9), b'mud', encode_key(key)))
        result = self.store.delete(operation, key)
        if result.status == 'COMMITTED' and self.mode in ('after', 'unknown'):
            previous = self.mode
            self.mode, self.drop = 'normal', True
            self.database.stop()
            if previous == 'after':
                self.database.start()
        return result

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
            serve_personas(FaultSocket(), self, allow_delete=True, allow_create=self.allow_create, allow_admin=self.allow_admin,
                           on_event=lambda state: self.events.append({'line': line, 'state': state}))
        except (OSError, ValueError, TimeoutError) as error:
            if not self.stopping:
                self.errors.append(type(error).__name__)


def native_controls(port, native, passwords, initial):
    results = {}
    killer = Guest(port, 'mudguest', [])
    try:
        require(killer.authenticate('Brian', passwords['Brian']), 'Native killer login failed')
        for name in ('Mortal', 'Gali'):
            victim = Guest(port, 'mudguest', [])
            try:
                require(victim.authenticate(name, passwords[name]), 'Native victim login failed')
                killer.send('fod ' + name)
                killer.expect(b'\n----*')
                results[name] = death_output(victim.connection)
            finally:
                logoff(victim.connection)
            after = private_export(native)
            if name == 'Mortal':
                require(pack_name('mortal') not in after, 'Native FOD did not delete persona')
            else:
                require(after[pack_name('gali')] == initial[pack_name('gali')], 'Native Gali death persisted')
        for name, explicit in (('Dskip', False), ('Dsaved', True)):
            require(initial[pack_name(name.lower())].words[0] & ((1 << 18) - 1) == 1,
                    'ATTACH fixture is not first-game')
            victim = Guest(port, 'mudguest', [])
            try:
                require(victim.authenticate('Roy', passwords['Roy']), 'Native attachment login failed')
                if explicit: victim.save('Roy')
                victim.send('attach ' + name)
                require('Attaching to ' + name in victim.expect(b'\n*'), 'Native ordinary ATTACH failed')
                killer.send('fod ' + name); killer.expect(b'\n----*')
                results[name] = death_output(victim.connection)
            finally:
                logoff(victim.connection)
            after = private_export(native)
            key = pack_name(name.lower())
            if explicit: require(key not in after, 'Prior SAVE did not qualify native attached death')
            else: require(after[key] == initial[key], 'Unsaved first-game ATTACH death deleted persona')
        killer.close()
    finally:
        logoff(killer.connection)
    return results


def exercise(machine, database, store, hub, passwords, controls, initial, report):
    issuer = SeedIssuer()
    with Controller(machine.port) as victim_monitor, Controller(machine.port) as killer_monitor:
        victim = ExitGame(victim_monitor, issuer)
        killer = ExitGame(killer_monitor, issuer)
        for name in (*ARCHWIZARDS, ORDINARY):
            for correct in (False, True):
                accepted, _ = victim.enter(name, passwords[name] if correct else 'wrongxyz')
                require(accepted == controls[name + (' correct' if correct else ' wrong')], 'Death build changed authentication')
                if accepted: victim.quit()
        report['authentication_comparisons'] = 16
        require(killer.enter('Brian', passwords['Brian'])[0], 'External killer login failed')
        for name, mode in (('Mortal', 'normal'), ('Gali', 'normal'), ('Ddrop', 'after'),
                           ('Dunknown', 'unknown'), ('Ddown', 'unavailable'), ('Dpending', 'pending'),
                           ('Dmissing', 'missing'), ('Dreplace', 'replace')):
            print('Death case:', name, mode, flush=True)
            key = pack_name(name.lower())
            before = store.get(key)
            require(victim.enter(name, passwords[name])[0], 'External victim login failed')
            count = len(hub.deletions)
            if mode == 'unavailable': database.pause()
            elif mode == 'pending':
                hub.mode = 'unknown'
                require('outcome unknown' in victim.command('save'), 'Pending SAVE not reproduced')
            elif mode == 'missing':
                with database.admin() as connection, connection.cursor() as cursor:
                    cursor.execute('DELETE FROM ' + DATABASE + '.personas WHERE namespace=%s AND name_key=%s',
                                   (b'mud', encode_key(key)))
            else: hub.mode = mode
            try:
                killer.command('fod ' + name)
                result = death_output(victim_monitor.connection)
                victim_monitor.at_monitor = True
                victim.accepted = False
            finally:
                if mode == 'unavailable': database.resume()
                elif mode in ('unknown', 'pending'): database.start()
            after = store.get(key)
            if name == 'Gali':
                require(after == before and len(hub.deletions) == count, 'Excluded death reached delete store')
            elif mode == 'unavailable':
                require(after == before and 'deletion not confirmed' in result['output'], 'Unavailable death falsely succeeded')
            elif mode == 'pending':
                require(after is not None and len(hub.deletions) == count, 'Unresolved SAVE allowed a delete')
                require('exit outcome UNKNOWN' in result['output'], 'Unresolved SAVE outcome hidden')
            elif mode == 'missing':
                require(after is None and len(hub.deletions) == count + 1, 'Missing deletion did not finish once')
                require('not confirmed' not in result['output'], 'Missing deletion was reported as failure')
                require(store.resolve(hub.deletions[-1]).status == 'NOT_FOUND', 'Missing outcome not durable')
            elif mode == 'replace':
                require(after == before and len(hub.deletions) == count + 1, 'Death retried against replacement')
                require('deletion not confirmed' in result['output'], 'Generation conflict hidden')
                require(store.resolve(hub.deletions[-1]).status == 'CONFLICT', 'Generation conflict not durable')
            else:
                require(after is None and len(hub.deletions) == count + 1, 'Death did not delete exactly once')
                if mode == 'unknown':
                    require('exit outcome UNKNOWN' in result['output'], 'Unknown delete falsely confirmed')
                require(store.resolve(hub.deletions[-1]).status == 'COMMITTED', 'Delete journal lost outcome')
                require(victim.enter(name, passwords[name])[1] == 'not_found', 'Deleted persona still logs in')
            report['cases'][name] = result
        for name, mode in (('Dskip', 'none'), ('Dsaved', 'saved'), ('Dabort', 'abort'), ('Dresolve', 'resolve')):
            print('Attached death case:', name, mode, flush=True)
            key = pack_name(name.lower())
            before = store.get(key)
            require(before.words[0] & ((1 << 18) - 1) == 1, 'External ATTACH fixture is not first-game')
            require(victim.enter('Roy', passwords['Roy'])[0], 'Attached death login failed')
            if mode == 'saved': require('saved.' in victim.command('save'), 'Prior SAVE failed')
            victim_monitor.send('attach ' + name)
            require('Attaching to ' + name in victim_monitor.receive(b'\n*'), 'Ordinary ATTACH failed')
            victim.prompt = b'\n*'
            if mode in ('abort', 'resolve'):
                hub.mode = 'prepare_unknown' if mode == 'abort' else 'unknown'
                require('outcome unknown' in victim.command('save'), 'Pending attached SAVE not reproduced')
                database.start()
            count = len(hub.deletions)
            killer.command('fod ' + name)
            result = death_output(victim_monitor.connection)
            victim_monitor.at_monitor = True; victim.accepted = False
            if mode in ('none', 'abort'):
                require(store.get(key) == before and len(hub.deletions) == count, 'Ineligible attached death deleted persona')
                if mode == 'abort':
                    require(store.commit(*hub.delayed).status == 'ABORTED', 'Death did not fence delayed SAVE')
            else:
                require(store.get(key) is None and len(hub.deletions) == count + 1, 'Confirmed SAVE did not qualify death')
            report['cases'][name] = result
        killer.quit()


def run(output):
    output.mkdir(mode=0o700)
    build = ROOT / 'build' / output.name
    prepare(ROOT / 'source', ROOT / 'upstream/mud1', build, external_death_existing=True)
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
            print('External death boot:', attempt + 1, flush=True)
            machine = private_emulator(output / f'machine-{attempt+1}', ports)
            try:
                machine.boot(); machine.command('daytime'); break
            except Exception:
                machine.stop(); machine = None
                if attempt + 1 == MAX_BOOT_ATTEMPTS: raise
        passwords = {name: generate_password() for name in (*ARCHWIZARDS, ORDINARY, *VICTIMS, *ATTACHED)}
        controls = baseline(machine.port, {name: value for name, value in passwords.items() if name not in ATTACHED})
        class ExistingInspector(NativePersonas):
            def install_inspector(self):
                pass  # baseline already compiled AUDPWD on this disposable disk.
        with ExistingInspector(machine.port) as creator:
            for name in ATTACHED: creator.create_and_save(name, passwords[name])
        with NativeInspector(machine.port) as native:
            native.command('assign dsk: bcl:'); native.command('set tty no altmode')
            initial = export_records(native)
            report['native'] = native_controls(machine.port, native, passwords, initial)
            fd = os.open(output / 'private-fixtures.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as private:
                json.dump({'passwords': passwords, 'controls': controls,
                           'initial': {name: initial[pack_name(name.lower())].words for name in passwords}}, private)
            native.command('copy debase.pm=mud.?pm')
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
            with LocalMariaDb(output / 'database') as database:
                for name in passwords:
                    database.seed(name.lower(), initial[pack_name(name.lower())].words)
                config = enable_writes(database, allow_delete=True)
                with isolated_writer(config) as store, patch('tools.persona_write_session.IDLE_TIMEOUT', 600), \
                        DeathHub(machine, ports, store, database) as hub:
                    exercise(machine, database, store, hub, passwords, controls, initial, report)
                    require(not hub.errors and not store.worker_pids, 'Death left transport/worker failure')
                    report['delete_attempts'] = len(hub.deletions)
            native.command('r filcom', b'\n*')
            text = native.command('tty:=debase.pm,pmhold.pm/b', b'\n*')
            require('No differences encountered' in text, 'External death touched retained native personas')
            native.connection.write(b'\x1a'); native.receive(b'\n.'); native.at_monitor = True
        require(source_hashes() == original, 'Original source changed')
        report.update(complete=True, source_unchanged=True, native_personas_unchanged=True)
        print('External death checks complete:', output, flush=True)
    except BaseException as error:
        report['error_type'] = type(error).__name__
        raise
    finally:
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        if machine is not None: machine.stop()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'runtime' / f'external-death-{time.time_ns()}')
    run(parser.parse_args().output.resolve())
