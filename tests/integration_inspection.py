"""Read-only inspection acceptance on a disposable historical disk and private port."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
import time

from tools.audit_archwizards import Guest, MAX_BOOT_ATTEMPTS, logoff
from tools.benchmark_idle import Emulator
from tools.inspect_game import NativeInspector, InspectionError
from tools.provision_archwizards import NativePersonas
from tests.integration_provisioning import source_hashes, require

ROOT = Path(__file__).resolve().parents[1]


def run(output):
    output.mkdir(mode=0o700)
    original = source_hashes()
    machine = guest = None
    report = {'complete': False}
    try:
        for attempt in range(MAX_BOOT_ATTEMPTS):
            print(f'Inspection private boot {attempt + 1}', flush=True)
            machine = Emulator(output / f'machine-{attempt + 1}', 'noidle', speed_factor=8)
            try:
                machine.boot()
                break
            except Exception:
                machine.stop()
                machine = None
                if attempt + 1 == MAX_BOOT_ATTEMPTS:
                    raise
        class DiagnosticInspector(NativeInspector):
            def receive(self, marker):
                text = super().receive(marker)
                with (output / 'inspection-transcript.txt').open('a') as stream:
                    stream.write(text)
                return text

        with DiagnosticInspector(machine.port) as native:
            print('Installing standalone companions', flush=True)
            native.install()
            initial = native.personas()
            report['initial_records'] = initial['records']
            # Independently hold the same native resource to prove contention.
            hold_source = (ROOT / 'tools/fixtures/MVPER.BCL').read_text().replace('/runame:mvper', '/runame:mvhld')
            hold_source = hold_source.replace('   for i=0 to HEADERWORDS-1',
                '   $( let ch=0; writes(tty,"HELD*C*L"); readch(tty,@ch) $)\n   for i=0 to HEADERWORDS-1')
            native.install_source('mvhld', hold_source)
            native.command('run mvhld', b'HELD\r\n')
            with NativeInspector(machine.port) as other, ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(other.personas)
                time.sleep(2)
                released_early = future.done()
                native.command('')
                try:
                    future.result()
                    require(not released_early, 'Reader ignored an existing native file lock')
                    report['lock_contention'] = 'waited until native lock released'
                except InspectionError as error:
                    require('busy' in str(error).lower(), 'Unexpected contention failure')
                    report['lock_contention'] = 'reported busy'
            listing = native.files()
            require('MUD' in listing['listing'], 'No native game directory')
            require(any(row['name'] == 'MUD..PM' for row in listing['files']), 'Persona file metadata missing')
            text = native.text('MUDLIB.BCL')
            require('and timeok' in text['text'], 'Native text decoding failed')
            tail = native.text('MUD.TXT')
            require(tail['truncated'] and len(tail['text']) == 65536, 'Large native file tail is not bounded')
            try:
                native.text('NOFILE.TXT')
            except InspectionError as error:
                require('missing or inaccessible' in str(error), 'Unexpected missing-file failure')
                pass
            else:
                raise AssertionError('Missing file was not rejected')
            # Query failure must leave the maintenance session usable.
            require(native.personas() == initial, 'Queries changed saved personas')

        # The independent password audit exposes full values only in memory.
        with NativePersonas(machine.port) as audit:
            before = audit.records()
            guest = Guest(machine.port, 'mudguest', [])
            require(guest.authenticate('Viewtest', 'inspectx', creating=True), 'Fixture creation failed')
            guest.save('Viewtest')
            saved = audit.records()
            with NativeInspector(machine.port) as native:
                native.command('copy vbef.pm=mud.?pm')
                snapshot = native.personas()
                row = next(row for row in snapshot['personas'] if row['name'].lower() == 'viewtest')
                require(row['password_set'] and row['games'] == 1, 'Persona decode mismatch')
                require(row['score'] == 0, 'Unexpected fixture score')
                require(audit.records() == saved, 'Inspection changed persona/password words')
                native.command('copy vaft.pm=mud.?pm')
                native.command('r filcom', b'\n*')
                comparison = native.command('tty:=vbef.pm,vaft.pm/b', b'\n*')
                require('No differences encountered' in comparison, 'Inspection changed persona file bytes')
                native.connection.write(b'\x1a')
                native.receive(b'\n.')
                native.at_monitor = True
                report['persona_file_byte_identical'] = True
                # A saved active player can continue using original SAVE concurrently.
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(native.personas)
                    guest.send('save')
                    require("haven't changed score" in guest.expect(b'\n*'), 'Concurrent SAVE failed')
                    require(future.result()['records'] == snapshot['records'], 'Concurrent snapshot failed')
                require(audit.records() == saved, 'Concurrent query changed password/games')
            guest.close()
            logoff(guest.connection)
            guest = None
            require(audit.records()['viewtest']['password_word'] == saved['viewtest']['password_word'],
                    'Inspection changed stored authentication')
            report['existing_personas_preserved'] = all(audit.records()[name] == value
                                                        for name, value in before.items())
        cli = subprocess.run([sys.executable, '-m', 'tools.inspect_game', 'persona', 'Viewtest',
                              '--port', str(machine.port), '--json'], cwd=ROOT,
                             capture_output=True, text=True, timeout=120)
        require(cli.returncode == 0, 'Persona CLI failed: ' + cli.stderr)
        require(json.loads(cli.stdout)['personas'][0]['name'].lower() == 'viewtest', 'CLI persona mismatch')
        with NativeInspector(machine.port) as native:
            try:
                game_log = native.text('MUD.LOG', area='logs')
                report['historical_game_log'] = 'available'
            except InspectionError as error:
                require('missing or inaccessible' in str(error), 'Unexpected historical log failure')
                report['historical_game_log'] = 'unavailable on baseline; reported as query failure'
        require(original == source_hashes(), 'Original source changed')
        report.update(complete=True, concurrent_save=True, native_text=True,
                      missing_file=True, source_unchanged=True)
        print(json.dumps(report, indent=2), flush=True)
    finally:
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        if guest is not None:
            guest.connection.close()
        if machine is not None:
            machine.stop()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'runtime' / f'inspection-check-{time.time_ns()}')
    run(parser.parse_args().output.resolve())
