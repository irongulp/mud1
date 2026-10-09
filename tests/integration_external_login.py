"""Original MUD login/gameplay using a read-only external persona build, privately."""
import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import re
import socket
import time
from unittest.mock import patch

from tools.audit_archwizards import Guest, ARCHWIZARDS, MAX_BOOT_ATTEMPTS, logoff
from tools.inspect_game import NativeInspector, SOURCE_LINE_DELAY
from tools.persona_bootstrap import SeedIssuer
from tools.persona_mariadb import isolated_mariadb
from tools.persona_protocol import LogicalRecord, WORD_MASK, pack_name
from tools.prepare import prepare, normalize
from tools.provision_archwizards import NativePersonas, generate_password
from tests.mariadb_fixture import LocalMariaDb
from tests.integration_persona_mariadb import DatabaseHub
from tests.integration_storage_bridge import ROOT, BRIDGE_LINES, private_emulator
from tests.integration_provisioning import require, source_hashes

DATA_BASE = 0o510000
ORDINARY = 'Extguest'
COPY_DELAY = 0.1


def transfer(native, filename, text):
    native.send('copy ' + filename + '=tty:')
    native.receive(('copy ' + filename + '=tty:\r\n').encode())
    for number, line in enumerate(text.splitlines(), 1):
        native.send(line)
        echoed = native.connection.read_until(b'\n', 10)
        require(echoed.endswith(b'\n'), f'Source transfer stalled at {filename}:{number}: {echoed!r}')
        time.sleep(COPY_DELAY)
    native.connection.write(b'\x1a')
    native.receive(b'\n.')
    native.at_monitor = True


def compile_source(native, build, name, output):
    print('Transferring/compiling', name, flush=True)
    native.command('assign dsk: bcl:')
    native.command('set tty no altmode')
    filename = name + '.bcl'
    old = normalize((ROOT / 'source' / filename.upper()).read_bytes()).decode('ascii')
    desired = (build / filename.upper()).read_text()
    def text_file():
        reply = native.command('type ' + filename).replace('\r', '')
        return reply.split('\n', 1)[1].rsplit('\n.', 1)[0]
    def rendered(text):
        # TTY output expands tabs and can discard deferred end-of-line padding.
        return '\n'.join(line.expandtabs(8).rstrip() for line in text.splitlines()).strip()
    actual = text_file()
    (output / (name + '-before.txt')).write_text(actual)
    require(rendered(actual) == rendered(old), 'Guest source differs from pinned input: ' + name)
    # The installed TECO pages large files; full paced COPY is slower but avoids
    # relying on global line offsets across editor pages. Verify all text below.
    transfer(native, filename, desired)
    actual = text_file()
    (output / (name + '-after.txt')).write_text(actual)
    require(rendered(actual) == rendered(desired), 'Guest edit differs from generated source: ' + name)
    native.command('r bcpl', b'\n*')
    text = native.command(name + '/o', b'\n*')
    (output / (name + '-compile.txt')).write_text(text)
    require(not re.search(r'\(W\d+-\d+\)|undefined global|error', text, re.I), 'BCPL compilation failed: ' + name)
    native.connection.write(b'\x1a')
    native.receive(b'\n.')
    native.at_monitor = True


def build_guest(machine, native, build, output):
    # COPY consumes input after echo. Keep compilation off the guest CPU while
    # another source stream is being paced into its small typeahead buffer.
    for name in ('mudlib', 'mud7', 'mud5'):
        compile_source(native, build, name, output)
    native.install_source('roseed', (ROOT / 'tools/fixtures/ROSEED.BCL').read_text())
    native.install_source('seedck', (ROOT / 'tools/fixtures/SEEDCK.BCL').read_text())
    native.command('run roseed', b'ROSEED READY\r\n')
    require('ROSEED SET' in native.command('777777777777777777777777'), 'Token setup failed')
    native.command('get seedck')
    result = native.command('start')
    require('SEEDCK MATCH' in result and 'SEEDCK CONSUMED' in result, 'TMPCOR token was not exact/read-once')
    native.command('protect roseed.exe<055>')
    transfer(native, 'roboot.mac', (build / 'ROBOOT.MAC').read_text())
    native.command('r macro', b'\n*')
    native.command('roboot=roboot', b'\n*')
    native.connection.write(b'\x1a')
    native.receive(b'\n.')
    native.command('copy mudnat.exe=mud.exe')
    native.command('r link', b'\n*')
    native.command('/set:.low.:140', b'\n*')
    listing = native.command('roboot,mud0,mud1,mud2,mud3,mud4,mud5,mud6,mud7,mud8,mudlib,mboots/counter', b'\n*')
    (output / 'link-counters.txt').write_text(listing)
    values = re.findall(r'\.HIGH\.\s+([0-7]+)', listing)
    require(values and int(values[-1], 8) < DATA_BASE, 'Game code would overlap its database')
    native.command(f'/set:.high.:{DATA_BASE:o}', b'\n*')
    native.command('dbadat/g')
    native.command('ssave mud')
    # Relink, rather than reimplement, the original authoritative DBASE compiler.
    native.command('r link', b'\n*')
    native.command('/set:.high.:430000', b'\n*')
    native.command(f'dbase,sys:bcplib/search/set:.high.:{DATA_BASE:o},dbadat/g')
    native.command('save dbase')
    generated = native.command('run dbase', b'MUD saved')
    (output / 'dbase.txt').write_text(generated)
    require('Total space used 25247' in generated, 'Original DBASE totals changed')
    native.receive(b'\n.')
    native.at_monitor = True
    native.command('protect mud.exe<055>')


def baseline(port, passwords):
    results = {}
    class PrivateFixtures(NativePersonas):
        def receive(self, marker):
            return self.expect(marker)
        def install_inspector(self):
            transfer(self, 'audpwd.bcl', (ROOT / 'tools/fixtures/AUDPWD.BCL').read_text())
            self.command('r bcpl', b'\n*'); self.command('audpwd/o', b'\n*')
            self.connection.write(b'\x1a'); self.expect(b'\n.')
            self.command('r link', b'\n*'); self.command('audpwd/g'); self.command('save audpwd')
    with PrivateFixtures(port) as native:
        for name, password in passwords.items():
            native.create_and_save(name, password)
    for name, password in passwords.items():
        for correct in (False, True):
            guest = Guest(port, 'mudguest', [])
            try:
                accepted = guest.authenticate(name, password if correct else 'wrongxyz')
                require(accepted == (correct and name != 'Richard'), 'Unexpected native baseline authentication')
                results[name + (' correct' if correct else ' wrong')] = accepted
                guest.close()
            finally:
                logoff(guest.connection)
    return results


def export_records(native):
    native.install_source('roexp', (ROOT / 'tools/fixtures/ROEXP.BCL').read_text())
    # This reply contains native password words. Keep it in memory only.
    text = native.command('run roexp')
    records = {}
    for line in text.splitlines():
        if line.startswith('ROW '):
            record = LogicalRecord(tuple(int(word, 8) & WORD_MASK for word in line.split()[1:]))
            require(record.name_words not in records, 'Duplicate exported persona')
            records[record.name_words] = record
    require('ROEXP END' in text, 'Incomplete native export')
    return records


class Game:
    def __init__(self, monitor, issuer):
        self.monitor, self.issuer = monitor, issuer
        self.accepted = False
        self.prompt = b'\n*'

    def enter(self, name, password, seed=True):
        if seed:
            self.issuer.load(self.monitor)
        else:
            self.monitor.command('get dskb:mud[2011,2776]')
        self.monitor.command('start', b'By what name shall I call you?')
        self.monitor.receive(b'*')
        self.monitor.send(name)
        index, _, data = self.monitor.connection.expect(
            [rb"what's the password\?", rb'External persona lookup unavailable\.',
             rb'External persona not found;'], 20)
        require(index >= 0, 'No external login result')
        if index != 0:
            self.monitor.receive(b'\n.')
            self.monitor.at_monitor = True
            return False, 'unavailable' if index == 1 else 'not_found'
        self.monitor.receive(b'*')
        self.monitor.send(password)
        index, _, data = self.monitor.connection.expect([rb'\nNo!\r?\n', rb'Hello(?: again)?,'], 20)
        require(index >= 0, 'No authentication decision')
        if index == 0:
            self.monitor.receive(b'\n.')
            self.monitor.at_monitor = True
            return False, 'rejected'
        self.prompt = b'\n----*' if name in ARCHWIZARDS else b'\n*'
        self.monitor.receive(self.prompt)
        self.accepted = True
        return True, 'accepted'

    def command(self, text):
        self.monitor.send(text)
        return self.monitor.receive(self.prompt)

    def quit(self):
        if self.accepted:
            text = self.monitor.command('quit')
            require('Read-only external persona storage: persona not saved.' in text, 'QUIT did not disclose read-only persistence')
            self.accepted = False


class Controller(NativeInspector):
    def __enter__(self):
        guest = Guest(self.port, 'mudguest', [])
        self.connection = guest.connection
        self.connection.write(b'\x03\x03')
        self.receive(b'\n.')
        self.at_monitor = True
        return self


def exercise(machine, database, passwords, baseline_results, report):
    issuer = SeedIssuer()
    with Controller(machine.port) as monitor:
        game = Game(monitor, issuer)
        for name, password in passwords.items():
            for correct in (False, True):
                accepted, outcome = game.enter(name, password if correct else 'wrongxyz')
                expected = baseline_results[name + (' correct' if correct else ' wrong')]
                require(accepted == expected and outcome == ('accepted' if expected else 'rejected'),
                        'External authentication differs from native baseline: ' + name)
                report.setdefault('authentication', {})[name + (' correct' if correct else ' wrong')] = outcome
                game.quit()
        require(game.enter(ORDINARY, passwords[ORDINARY])[0], 'External ordinary login failed')
        score = game.command('score')
        require('777' in score, 'Original MUD did not load the database score')
        require('Narrow road' in game.command('look me'), 'Original room lookup failed')
        require('MUD' in game.command('info'), 'Original INFO/world file access failed')
        game.command('inventory')
        for command, room in (('w', 'Narrow road.'), ('w', 'Road opposite cottage.'),
                              ('s', 'Path.'), ('s', 'Hall.'), ('u', 'Halfway up the stairs.'),
                              ('u', 'Upstairs landing.'), ('s', 'Large bedroom.')):
            require(room in game.command(command), 'Original travel failed: ' + command)
        game.command('make bed')
        require('unmake the bed' in game.command('unmake bed'), 'Original scoring action failed')
        scored = re.search(r'Score to date:\s*(\d+)', game.command('score'))
        require(scored and int(scored[1]) > 777, 'Game did not change its in-memory score')
        report['score_before'] = 777
        report['score_during_play'] = int(scored[1])
        with Controller(machine.port) as other:
            peer = Game(other, issuer)
            require(peer.enter('Roy', passwords['Roy'])[0], 'Second game job could not load an external persona')
            who = peer.command('who')
            require('Extguest' in who and 'Roy' in who, 'Two external players did not share the original world')
            peer.quit()
        report['multiplayer'] = True
        for command in ('save', 'password'):
            require('Read-only external persona storage' in game.command(command), 'Unsupported mutation was not gated')
        game.quit()
        require(game.enter(ORDINARY, passwords[ORDINARY])[0], 'External re-entry failed')
        require('777' in game.command('score'), 'Read-only state changed on re-entry')
        report['score_after_reentry'] = 777
        game.quit()
        require(game.enter('Roy', passwords['Roy'])[0], 'Roy login failed')
        require('Read-only external persona storage' in game.command('purge that'), 'PURGE reached native storage')
        game.monitor.send('attach richard')
        game.monitor.receive(b"What's the password for this persona?")
        game.monitor.send('wrongxyz')
        require('Wrong!' in game.monitor.receive(game.prompt), 'Wrong ATTACH password accepted')
        game.monitor.send('attach richard')
        game.monitor.receive(b"What's the password for this persona?")
        game.monitor.send(passwords['Roy'])
        require('Wrong!' in game.monitor.receive(game.prompt), 'Roy password authenticated Richard')
        game.monitor.send('attach richard')
        game.monitor.receive(b"What's the password for this persona?")
        game.monitor.send(passwords['Richard'])
        require('Attaching to Richard' in game.monitor.receive(game.prompt), 'Richard ATTACH did not authenticate')
        require('Read-only external persona storage' in game.command('save'), 'Attached SAVE was not gated')
        game.quit()
        report['richard_attach'] = 'wrong rejected; correct accepted; writes blocked'
        require(game.enter('Absent', 'unused')[1] == 'not_found', 'Missing record created a persona')
        require(game.enter(ORDINARY, passwords[ORDINARY], seed=False)[1] == 'unavailable', 'Unprovisioned image used a stale seed')
        database.pause()
        try:
            require(game.enter(ORDINARY, passwords[ORDINARY])[1] == 'unavailable', 'Database outage fell back to native data')
        finally:
            database.resume()
        require(game.enter(ORDINARY, passwords[ORDINARY])[0], 'Recovery after database outage failed')
        game.quit()
        report.update(gameplay=True, reentry=True, missing=True, missing_seed=True, database_outage=True)


def run(output):
    output.mkdir(mode=0o700)
    build = ROOT / 'build' / output.name
    original = source_hashes()
    prepare(ROOT / 'source', ROOT / 'upstream/mud1', build, external_readonly=True)
    machine = None
    report = {'complete': False, 'build': str(build)}
    try:
        with ExitStack() as stack:
            sockets = [stack.enter_context(socket.socket()) for _ in BRIDGE_LINES]
            ports = {}
            for line, sock in zip(BRIDGE_LINES, sockets):
                sock.bind(('127.0.0.1', 0)); ports[line] = sock.getsockname()[1]
        for attempt in range(MAX_BOOT_ATTEMPTS):
            print('External MUD private boot:', attempt + 1, flush=True)
            machine = private_emulator(output / f'machine-{attempt+1}', ports)
            try:
                machine.boot(); machine.command('daytime')
                break
            except Exception:
                machine.stop(); machine = None
                if attempt + 1 == MAX_BOOT_ATTEMPTS:
                    raise
        passwords = {name: generate_password() for name in (*ARCHWIZARDS, ORDINARY)}
        print('Preparing native authentication baseline', flush=True)
        baseline_results = baseline(machine.port, passwords)
        with NativeInspector(machine.port) as native:
            native.command('assign dsk: bcl:'); native.command('set tty no altmode')
            records = export_records(native)
            require(len(records) == len(passwords), 'Native fixture export count differs')
            native.command('copy robase.pm=mud.?pm')
            build_guest(machine, native, build, output)
            # Make fallback impossible, while retaining an exact comparison file.
            native.command('rename pmhold.pm=mud.?pm')
            with LocalMariaDb(output / 'database') as database:
                for name in passwords:
                    words = list(records[pack_name(name.lower())].words)
                    if name == ORDINARY:
                        words[3] = 777
                    database.seed(name.lower(), words)
                before = database.digest()
                with isolated_mariadb(database.reader_config()) as store, patch('tools.persona_session.IDLE_TIMEOUT', 600), \
                        DatabaseHub(machine, ports, store) as hub:
                    print('Testing original MUD against MariaDB', flush=True)
                    exercise(machine, database, passwords, baseline_results, report)
                    require(not hub.errors, 'External read transport failed')
                    report['lookups'] = len(hub.offers)
                require(before == database.digest(), 'Read-only game changed database personas')
                report['database_unchanged'] = True
            native.command('r filcom', b'\n*')
            comparison = native.command('tty:=robase.pm,pmhold.pm/b', b'\n*')
            require('No differences encountered' in comparison, 'Native persona bytes changed')
            native.connection.write(b'\x1a'); native.receive(b'\n.'); native.at_monitor = True
        require(original == source_hashes(), 'Original source changed')
        report.update(complete=True, source_unchanged=True, persona_bytes_unchanged=True)
        print('External MUD read-only login verified:', output, flush=True)
    except BaseException as error:
        report['error_type'] = type(error).__name__
        raise
    finally:
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        if machine is not None:
            machine.stop()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'runtime' / f'external-login-{time.time_ns()}')
    run(parser.parse_args().output.resolve())
