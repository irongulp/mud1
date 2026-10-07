"""Characterize original first-save allocation on a disposable native game."""
import argparse
import json
from pathlib import Path
import re
import time

from tools.audit_archwizards import Guest, MAX_BOOT_ATTEMPTS, logoff
from tools.inspect_game import NativeInspector
from tools.persona_protocol import pack_name, WORD_MASK
from tools.provision_archwizards import generate_password
from tests.integration_external_login import baseline, export_records
from tests.integration_external_save import private_export, route
from tests.integration_storage_bridge import ROOT, private_emulator
from tests.integration_provisioning import require, source_hashes

OPAQUE = (WORD_MASK, 1 << 35, int('123456765432', 8))


def edge(native, mode=0):
    native.command('run pmedge', b'PMEDGE MODE')
    text = native.command(str(mode))
    require('PMEDGE END' in text, 'Native allocation inspector failed')
    slots = []
    for match in re.finditer(r'PMEDGE SLOT (\d+) (-?\d+) (-?\d+) (-?\d+) ([0-7]+) ([0-7]+) ([0-7]+)', text):
        parts = match.groups()
        slots.append({'offset': int(parts[0]), 'active': int(parts[1]) != 0,
                      'score': int(parts[2]), 'header_guard': int(parts[3]),
                      'opaque': [int(value, 8) for value in parts[4:]]})
    require(slots, 'No native slots inspected')
    return slots


def purge(killer, name):
    killer.send('purge ' + name)
    killer.expect(b'Save, delete or finish? ')
    killer.connection.write(b'd')
    result = killer.expect(b'\n----*')
    require('deleted.' in result, 'Native PURGE did not delete fixture')


def bucket_name(bucket):
    for index in range(26 ** 3):
        suffix = ''.join(chr(ord('a') + index // (26 ** power) % 26) for power in (2, 1, 0))
        candidate = 'hdr' + suffix
        words = pack_name(candidate)
        if ((sum(words) & WORD_MASK) >> 1) % 253 == bucket:
            return candidate.capitalize()
    raise AssertionError('No fixture name for header bucket')


def run(output):
    output.mkdir(mode=0o700)
    report = {'complete': False}
    original = source_hashes()
    machine = None
    try:
        for attempt in range(MAX_BOOT_ATTEMPTS):
            machine = private_emulator(output / ('machine-' + str(attempt + 1)), {})
            try:
                machine.boot(); machine.command('daytime'); break
            except Exception:
                machine.stop(); machine = None
                if attempt + 1 == MAX_BOOT_ATTEMPTS: raise
        passwords = {name: generate_password() for name in ('Brian', 'Recyold')}
        baseline(machine.port, passwords)
        with NativeInspector(machine.port) as native:
            native.command('assign dsk: bcl:'); native.command('set tty no altmode')
            initial = export_records(native)
            require(initial[pack_name('recyold')].words[8:] == (0, 0, 0), 'Fresh native slot not zero initialized')
            report['fresh_opaque_zero'] = True
            native.command('copy crbase.pm=mud.?pm')
            native.install_source('pmedge', (ROOT / 'tools/fixtures/PMEDGE.BCL').read_text())
            report['marked'] = edge(native, 1)
            marked = private_export(native)[pack_name('recyold')]
            require(marked.words[3] == WORD_MASK - 1 and marked.words[8:] == OPAQUE, 'Marker did not retain all 36 bits')
            killer = Guest(machine.port, 'mudguest', [])
            try:
                require(killer.authenticate('Brian', passwords['Brian']), 'Native operator login failed')
                purge(killer, 'recyold')
                require(pack_name('recyold') not in private_export(native), 'Native deleted record still active')
                report['deleted'] = edge(native)
                guest = Guest(machine.port, 'mudguest', [])
                try:
                    password = generate_password()
                    require(guest.authenticate('Recynew', password, creating=True), 'New persona admission failed')
                    require(pack_name('recynew') not in private_export(native), 'Login prematurely persisted persona')
                    guest.save('Recynew')
                    saved = private_export(native)[pack_name('recynew')]
                    require(saved.words[3] == 0 and saved.words[8:] == OPAQUE, 'Recycled native SAVE did not preserve opaque tail')
                    report['recycled_opaque_retained'] = True
                    report['negative_recycled_score_did_not_block_first_save'] = True
                    report['saved'] = edge(native)
                    guest.close()
                finally:
                    logoff(guest.connection)
                # An admitted first-game persona that quits at zero score does
                # not acquire a file record merely by choosing a password.
                guest = Guest(machine.port, 'mudguest', [])
                try:
                    require(guest.authenticate('Nosave', generate_password(), creating=True), 'Unsaved creation failed')
                    guest.close()
                finally:
                    logoff(guest.connection)
                require(pack_name('nosave') not in private_export(native), 'Zero-score QUIT persisted new persona')
                report['zero_score_quit_not_persisted'] = True
                # Same logical session state, different valid hash-table state:
                # addrec leaves block 1 loaded for saverec's score comparison.
                # PURGE is original BCPL, not a fabricated deletion shortcut.
                for name, populate_header in (('Guardnew', False), ('Guardtwo', True)):
                    native.command('rename dskb:mud.exe[2011,2776]=dskb:mud.exe[2011,2776]')
                    guest = Guest(machine.port, 'mudguest', [])
                    try:
                        require(guest.authenticate(name, generate_password(), creating=True), 'Guard fixture creation failed')
                        def command(text):
                            guest.send(text)
                            return guest.expect(b'\n*')
                        route(command)
                        guest.save(name)
                        saved = private_export(native)[pack_name(name.lower())]
                        require(saved.words[3] == 11 and saved.words[0] & ((1 << 18) - 1) == 1,
                                'Guard fixture score/game count wrong')
                        slot = next(row for row in edge(native) if row['active'] and row['score'] == 11)
                        require(slot['header_guard'] == 0, 'Guard fixture header not initially empty')
                        if populate_header:
                            unrelated = Guest(machine.port, 'mudguest', [])
                            try:
                                other = bucket_name(slot['offset'] % 128 + 4)
                                require(unrelated.authenticate(other, generate_password(), creating=True), 'Header fixture creation failed')
                                unrelated.save(other)
                                unrelated.close()
                            finally:
                                logoff(unrelated.connection)
                        purge(killer, name.lower())
                        require(pack_name(name.lower()) not in private_export(native), 'Guard fixture not purged')
                        guest.send('quit')
                        text = guest.expect(b'\n.')
                        guest.accepted = False
                        after = private_export(native)
                        require((pack_name(name.lower()) in after) == populate_header,
                                'Native header-dependent recreation result differed')
                        require(('score seems to have changed' in text) != populate_header,
                                'Native header score check did not match allocation state')
                        report['header_populated' if populate_header else 'header_empty'] = {
                            'recreated': pack_name(name.lower()) in after,
                            'score_guard_message': 'score seems to have changed' in text,
                            'slots': edge(native)}
                    finally:
                        logoff(guest.connection)
                killer.close()
            finally:
                logoff(killer.connection)
        require(source_hashes() == original, 'Original source changed')
        report.update(complete=True, source_unchanged=True)
        print('Native creation characterization complete:', output, flush=True)
    finally:
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        if machine is not None: machine.stop()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'runtime' / f'native-creation-{time.time_ns()}')
    run(parser.parse_args().output.resolve())
