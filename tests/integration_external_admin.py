"""Native PASSWORD/PURGE controls and external administration acceptance."""
import argparse
import json
from pathlib import Path
import re
import time
from unittest.mock import patch

from tools.audit_archwizards import Guest, ARCHWIZARDS, logoff
from tools.persona_bootstrap import SeedIssuer
from tools.persona_protocol import pack_name, LogicalRecord
from tools.persona_writes import WriteResult
from tools.persona_mariadb import encode_key
from tools.prepare import prepare
from tests import integration_external_creation as creation
from tests.integration_external_creation import CreationGame, CreationHub
from tests.integration_external_login import Controller, ORDINARY
from tests.integration_external_save import private_export
from tests.integration_persona_writes import revision
from tests.integration_provisioning import require
from tests.mariadb_fixture import DATABASE

FIXTURES = ('Pwdok', 'Pwdwrong', 'Pwdmism', 'Pwdsave', 'Preader', 'Pmatch', 'Pother',
            'Pkeep', 'Pdelete', 'Pdrop', 'Punknown', 'Pchange', 'Ppending', 'Pexit', 'Pabort')
EXTRA = (*FIXTURES, 'Newcode', 'Othercode', 'Pwdnew')


def password(send, receive, prompt, old, new, confirmation, *, wrong=False):
    send('password'); receive(b'What is your present password?'); receive(b'*')
    send(old)
    if wrong: return receive(prompt)
    receive(b'letters please.'); receive(b'*')
    send(new); receive(b"correct, please.")
    send(confirmation)
    return receive(prompt)


def names(text):
    return {name.lower() for name in re.findall(r'Name:\s*([A-Za-z0-9]+)', text)}


def menu(send, connection, target, choices='s', delay=0):
    send('purge ' + target)
    output, count = [], 0
    while True:
        index, _, data = connection.expect([rb'Save, delete or finish\? ', rb'\n----\*'], 30)
        require(index >= 0, 'PURGE did not reach menu or prompt')
        output.append(data.decode('ascii', errors='replace'))
        if index == 1: return ''.join(output)
        require(count < 100, 'PURGE enumeration exceeded fixture bound')
        if delay: time.sleep(delay); delay = 0
        connection.write(choices[min(count, len(choices)-1)].encode('ascii'))
        count += 1


def native_controls(machine, native, passwords):
    passwords['Pmatch'] = passwords['Preader']
    for name in FIXTURES:
        guest = Guest(machine.port, 'mudguest', [])
        try:
            require(guest.authenticate(name, passwords[name], creating=True), 'Native administration fixture creation failed')
            guest.save(name); guest.close()
        finally: logoff(guest.connection)
    initial = private_export(native)
    goldens = {name: initial[pack_name(name.lower())] for name in FIXTURES}
    observations = {}
    for name, mode in (('Pwdok', 'quit'), ('Pwdwrong', 'wrong'), ('Pwdmism', 'mismatch'), ('Pwdsave', 'save')):
        guest = Guest(machine.port, 'mudguest', [])
        try:
            require(guest.authenticate(name, passwords[name]), 'Native PASSWORD login failed')
            response = password(guest.send, guest.expect, b'\n*',
                                passwords['Othercode'] if mode == 'wrong' else passwords[name],
                                passwords['Newcode'], passwords['Othercode'] if mode == 'mismatch' else passwords['Newcode'],
                                wrong=mode == 'wrong')
            expected = 'incorrect' if mode == 'wrong' else "they're different" if mode == 'mismatch' else 'updated when you leave'
            require(expected in response, 'Native PASSWORD result unexpected')
            require(private_export(native)[pack_name(name.lower())] == goldens[name], 'PASSWORD immediately wrote native file')
            guest.send('password'); require('once per game' in guest.expect(b'\n*'), 'Native PASSWORD repeat allowed')
            if mode == 'save': guest.save(name)
            guest.close()
        finally: logoff(guest.connection)
        goldens[name + '.result'] = private_export(native)[pack_name(name.lower())]
        observations[name] = {'mode': mode, 'deferred': True, 'once_per_game': True}
    guest = Guest(machine.port, 'mudguest', [])
    try:
        require(guest.authenticate('Preader', passwords['Preader']), 'Native ordinary reader login failed')
        guest.send('purge pother'); hidden = guest.expect(b'\n*')
        require(not names(hidden), 'Ordinary PURGE exposed a nonmatching password')
        guest.send('purge that'); listing = guest.expect(b'\n*')
        require(names(listing) == {'preader', 'pmatch'}, 'Native password-filtered enumeration unexpected')
        guest.close()
    finally: logoff(guest.connection)
    observations['ordinary_listing'] = sorted(names(listing))
    guest = Guest(machine.port, 'mudguest', [])
    try:
        require(guest.authenticate('Roy', passwords['Roy']), 'Native administrator login failed')
        require('pkeep' in names(menu(guest.send, guest.connection, 'pkeep', 's')), 'Native targeted view failed')
        require(private_export(native)[pack_name('pkeep')] == goldens['Pkeep'], 'Native Save menu choice modified record')
        require('deleted.' in menu(guest.send, guest.connection, 'pdelete', 'd'), 'Native targeted deletion failed')
        require(pack_name('pdelete') not in private_export(native), 'Native target survived PURGE')
        listing = menu(guest.send, guest.connection, 'that', 's')
        require(names(listing) == {name.lower() for name in (*ARCHWIZARDS, ORDINARY, *FIXTURES) if name != 'Pdelete'},
                'Native full enumeration omitted records')
        require(len(names(menu(guest.send, guest.connection, 'that', 'f'))) == 1, 'Native Finish continued enumeration')
        guest.close()
    finally: logoff(guest.connection)
    observations['archwizard_listing'] = sorted(names(listing))
    return goldens, observations


class AdminHub(CreationHub):
    allow_admin = True
    def __init__(self, *args):
        super().__init__(*args)
        self.purges = []
    def begin_purge(self, operation, key): return self.store.begin_purge(operation, key)
    def begin_next(self, operation, after): return self.store.begin_next(operation, after)
    def purge(self, operation, key):
        self.purges.append(operation)
        if self.mode == 'before':
            self.mode, self.drop = 'normal', True
            self.database.stop()
            return WriteResult('UNKNOWN')
        if self.mode == 'change':
            self.mode = 'normal'
            record = self.store.get(key)
            words = list(record.words); words[7] ^= 1
            with self.database.admin() as connection, connection.cursor() as cursor:
                cursor.execute('UPDATE ' + DATABASE + '.personas SET words=%s,revision=revision+1 '
                               'WHERE namespace=%s AND name_key=%s', (json.dumps(words), b'mud', encode_key(key)))
        result = self.store.purge(operation, key)
        if result.status == 'COMMITTED' and self.mode in ('after', 'unknown'):
            previous = self.mode
            self.mode, self.drop = 'normal', True
            self.database.stop()
            if previous == 'after': self.database.start()
        return result


def exercise(machine, native, database, store, hub, passwords, controls, goldens, report):
    for name in FIXTURES: database.seed(name.lower(), goldens[name].words)
    # Fixture insertion is administrative; provision generation metadata before
    # exposing these rows to the experimental adapter.
    import secrets
    with database.admin() as connection, connection.cursor() as cursor:
        for name in FIXTURES:
            cursor.execute('UPDATE ' + DATABASE + '.personas SET generation=%s WHERE namespace=%s AND name_key=%s',
                           (secrets.token_bytes(9), b'mud', encode_key(pack_name(name.lower()))))
    with Controller(machine.port) as monitor:
        game = CreationGame(monitor, SeedIssuer())
        for name in (*ARCHWIZARDS, ORDINARY):
            for correct in (False, True):
                accepted, _ = game.enter(name, passwords[name] if correct else 'wrongxyz')
                require(accepted == controls[name + (' correct' if correct else ' wrong')], 'Admin build changed authentication')
                if accepted: game.quit()
        report['authentication_comparisons'] = 16
        for name, mode in (('Pwdok', 'quit'), ('Pwdwrong', 'wrong'), ('Pwdmism', 'mismatch'), ('Pwdsave', 'save')):
            print('PASSWORD comparison:', name, flush=True)
            key = pack_name(name.lower())
            require(game.enter(name, passwords[name])[0], 'External PASSWORD login failed')
            before = store.get(key)
            response = password(monitor.send, monitor.receive, game.prompt,
                                passwords['Othercode'] if mode == 'wrong' else passwords[name],
                                passwords['Newcode'], passwords['Othercode'] if mode == 'mismatch' else passwords['Newcode'],
                                wrong=mode == 'wrong')
            expected = 'incorrect' if mode == 'wrong' else "they're different" if mode == 'mismatch' else 'updated when you leave'
            require(expected in response and store.get(key) == before, 'PASSWORD policy or deferred persistence changed')
            require('once per game' in game.command('password'), 'PASSWORD repeated in same game')
            if mode == 'save': require(' saved.' in game.command('save'), 'Changed password explicit SAVE failed')
            game.quit()
            after, expected_record = store.get(key), goldens[name + '.result']
            require(after.words[:5] + after.words[6:] == expected_record.words[:5] + expected_record.words[6:],
                    'PASSWORD persisted fields differ from native, excluding rebooted clock')
            correct = passwords[name] if mode in ('wrong', 'mismatch') else passwords['Newcode']
            wrong = passwords['Newcode'] if mode in ('wrong', 'mismatch') else passwords[name]
            require(game.enter(name, wrong)[1] == 'rejected', 'Wrong/superseded password accepted')
            require(game.enter(name, correct)[0], 'Persisted password rejected')
            game.quit()
            report['cases'][name] = {'native_match': True, 'reentry': True}
        require(game.enter('Preader', passwords['Preader'])[0], 'Ordinary external reader login failed')
        before = store.get(pack_name('pmatch'))
        require(not names(game.command('purge pother')), 'Unauthorized ordinary view exposed record')
        listing = game.command('purge that')
        require(names(listing) == {'preader', 'pmatch'}, 'External password filter differs from native')
        require(store.get(pack_name('pmatch')) == before, 'Read-only enumeration changed persona')
        require('Score to date:' in game.command('score'), 'PURGE did not restore live command processing')
        game.quit()
        report['cases']['ordinary_listing'] = sorted(names(listing))
        require(game.enter('Roy', passwords['Roy'])[0], 'External administrator login failed')
        before = store.get(pack_name('pkeep'))
        require('pkeep' in names(menu(monitor.send, monitor.connection, 'pkeep', 's', delay=6)), 'Delayed menu view failed')
        require(store.get(pack_name('pkeep')) == before, 'Keep choice changed stored record')
        require('deleted.' in menu(monitor.send, monitor.connection, 'pdelete', 'd'), 'PURGE did not confirm deletion')
        require(store.get(pack_name('pdelete')) is None, 'Deleted target survived')
        listing = menu(monitor.send, monitor.connection, 'that', 's')
        expected = {name.lower() for name in (*ARCHWIZARDS, ORDINARY, *FIXTURES) if name != 'Pdelete'}
        require(names(listing) == expected, 'External full enumeration differs from native set')
        require(len(names(menu(monitor.send, monitor.connection, 'that', 'f'))) == 1, 'Finish did not stop enumeration')
        report['cases']['archwizard_listing'] = sorted(names(listing))
        report['cases']['keep_delete_finish'] = True
        for name, mode in (('Pdrop', 'after'), ('Pchange', 'change'), ('Punknown', 'unknown')):
            print('PURGE fault case:', mode, flush=True)
            hub.mode = mode
            result = menu(monitor.send, monitor.connection, name.lower(), 'd')
            key = pack_name(name.lower())
            if mode == 'unknown':
                require('outcome UNKNOWN' in result, 'Unknown purge falsely confirmed')
                for command in ('save', 'password', 'attach pkeep'):
                    require('pending PURGE' in game.command(command), 'Pending PURGE allowed another persistence transition')
                database.start()
                monitor.send('purge that')
                recovered = monitor.connection.read_until(game.prompt, 25)
                require(recovered.endswith(game.prompt), 'Pending PURGE retry did not return: ' + repr(recovered))
                require(b'deleted.' in recovered, 'Pending purge did not resolve its original operation')
            if mode == 'change':
                require('Persona changed; not deleted' in result and store.get(key) is not None, 'PURGE used stale password permission')
            else:
                require(store.get(key) is None and store.resolve(hub.purges[-1]).status == 'COMMITTED', 'Confirmed purge outcome lost')
            report['cases'][name] = {'mode': mode, 'passed': True}
        print('PURGE enumeration outage', flush=True)
        database.pause()
        try:
            require('lookup failed' in game.command('purge that'), 'Outage looked like an empty enumeration')
        finally: database.resume()
        require('Score to date:' in game.command('score'), 'Lookup failure stranded dormant persona')
        report['cases']['enumeration_outage'] = True
        print('PURGE pending exit', flush=True)
        hub.mode = 'unknown'
        require('outcome UNKNOWN' in menu(monitor.send, monitor.connection, 'pexit', 'd'), 'Exit pending purge not reproduced')
        exited = game.quit()
        require('PURGE outcome UNKNOWN' in exited['output'], 'Unknown purge exit falsely completed')
        database.start()
        require(store.resolve(hub.purges[-1]).status == 'COMMITTED', 'Exit lost purge journal outcome')
        report['cases']['unknown_purge_exit'] = True
        print('Aborted PURGE followed by eligible QUIT', flush=True)
        require(game.enter('Roy', passwords['Roy'])[0], 'Aborted purge fixture login failed')
        own_revision = revision(database, pack_name('roy'))
        hub.mode = 'before'
        require('outcome UNKNOWN' in menu(monitor.send, monitor.connection, 'pabort', 'd'), 'Uncommitted purge not reproduced')
        database.start()
        game.quit()
        require(store.resolve(hub.purges[-1]).status == 'ABORTED', 'Exit did not fence uncommitted purge')
        require(store.get(pack_name('pabort')) is not None, 'Aborted purge deleted target')
        require(revision(database, pack_name('roy')) == own_revision + 1, 'Resolved aborted purge suppressed eligible exit persistence')
        report['cases']['aborted_purge_exit'] = True
        print('Administration blocked by pending SAVE', flush=True)
        require(game.enter('Ppending', passwords['Ppending'])[0], 'Pending SAVE fixture login failed')
        hub.mode = 'unknown'
        require('outcome unknown' in game.command('save'), 'Pending SAVE not reproduced')
        require('pending SAVE before PASSWORD' in game.command('password'), 'PASSWORD ignored pending SAVE')
        require('pending SAVE before PURGE' in game.command('purge that'), 'PURGE ignored pending SAVE')
        database.start(); game.command('save'); game.quit()
        report['cases']['pending_save_gates'] = True


def run(output):
    def admin_prepare(local, upstream, build, **options):
        return prepare(local, upstream, build, external_admin=True)
    with patch.object(creation, 'NEW_NAMES', EXTRA), patch.object(creation, 'prepare', admin_prepare), \
            patch.object(creation, 'native_controls', native_controls), patch.object(creation, 'exercise', exercise), \
            patch.object(creation, 'CreationHub', AdminHub):
        creation.run(output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=creation.ROOT / 'runtime' / f'external-admin-{time.time_ns()}')
    run(parser.parse_args().output.resolve())
