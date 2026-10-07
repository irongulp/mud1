"""Native locked capture -> MariaDB import -> database restore -> actual login."""
import argparse
from contextlib import ExitStack
from dataclasses import replace
import json
from pathlib import Path
import shutil
import socket
import subprocess
import time
from unittest.mock import patch

from tools.audit_archwizards import Guest, ARCHWIZARDS, logoff
from tools.capture_personas import capture
from tools.persona_backup import backup_database, restore_database
from tools.persona_mariadb import MariaDbConfig
from tools.persona_migrate import import_snapshot, verify_import
from tools.persona_snapshot import write_snapshot, read_snapshot, private_read
from tools.persona_bootstrap import SeedIssuer
from tools.persona_writes import isolated_writer
from tools.prepare import prepare
from tests import integration_external_creation as creation
from tests import integration_external_lifecycle as lifecycle
from tests.integration_external_login import Controller, ORDINARY
from tests.integration_external_save import private_export
from tests.integration_external_creation import CreationGame, CreationHub
from tests.integration_provisioning import require, source_hashes
from tests.integration_storage_bridge import private_emulator, BRIDGE_LINES
from tools.inspect_game import NativeInspector
from tests.mariadb_fixture import LocalMariaDb, DATABASE


def filcom(native):
    native.command('copy migend.pm=mud.?pm')
    native.command('r filcom', b'\n*')
    result = native.command('tty:=migbas.pm,migend.pm/b', b'\n*')
    require('No differences encountered' in result, 'Snapshot capture changed the native persona file')
    native.connection.write(b'\x1a'); native.receive(b'\n.'); native.at_monitor = True


def run(output, *, captured_run=None, prepared_runtime=None, column_schema=False):
    captured = {}
    original_writes = creation.enable_writes
    def configured(database): return replace(original_writes(database), namespace='imported')
    def prepared(local, upstream, build, **options): return prepare(local, upstream, build, external_lifecycle=True)
    def build_guest(*args):
        with patch.object(lifecycle, 'install_worlds', lambda *args: None): lifecycle.build_guest(*args)
    def native_controls(machine, native, passwords):
        guest = Guest(machine.port, 'mudguest', [])
        try:
            require(guest.authenticate('Oldmig', passwords['Oldmig'], creating=True), 'Deleted-slot fixture admission failed')
            guest.save('Oldmig'); guest.close()
        finally: logoff(guest.connection)
        guest = Guest(machine.port, 'mudguest', [])
        try:
            require(guest.authenticate('Roy', passwords['Roy']), 'Native purge fixture login failed')
            guest.send('purge oldmig'); guest.expect(b'Save, delete or finish? ')
            guest.connection.write(b'd'); require('deleted.' in guest.expect(b'\n----*'), 'Native purge fixture failed')
            guest.close()
        finally: logoff(guest.connection)
        expected = private_export(native)
        native.command('copy migbas.pm=mud.?pm')
        snapshot = capture(native, install=True)
        require(snapshot.records == expected, 'Full native snapshot differs from independent logical export')
        require(snapshot.deleted == 1, 'Deleted native slot not captured/validated')
        require(capture(native).words == snapshot.words, 'Repeated quiescent capture changed')
        filcom(native)
        write_snapshot(output / 'native-personas.json', snapshot)
        captured['snapshot'] = read_snapshot(output / 'native-personas.json')
        return {}, dict(snapshot.report(), native_bytes_unchanged=True)
    def exercise(machine, native, database, store, hub, passwords, controls, goldens, report):
        snapshot = captured['snapshot']
        admin = MariaDbConfig(database=DATABASE, user='root', password='', unix_socket=str(database.socket), namespace='imported')
        report['cases']['import'] = import_snapshot(admin, snapshot)
        report['cases']['verify'] = verify_import(admin, snapshot)
        for key, record in snapshot.records.items(): require(store.get(key) == record, 'Adapter altered imported native words')
        def authentication():
            with Controller(machine.port) as monitor:
                game = CreationGame(monitor, SeedIssuer())
                for name in (*ARCHWIZARDS, ORDINARY):
                    for correct in (False, True):
                        accepted, _ = game.enter(name, passwords[name] if correct else 'wrongxyz')
                        require(accepted == controls[name + (' correct' if correct else ' wrong')], 'Migrated authentication differs from native')
                        if accepted: game.quit()
            return 16
        report['authentication_comparisons'] = authentication()
        require(import_snapshot(admin, snapshot)['already_imported'], 'Post-play import was not receipt-only')
        archive = output / 'external-backup.zip'
        report['cases']['backup'] = backup_database(admin, archive)
        with LocalMariaDb(output / 'restored', column_schema=column_schema) as target:
            with target.admin() as connection, connection.cursor() as cursor:
                cursor.execute('DROP TABLE ' + DATABASE + '.personas')
            restored = replace(admin, unix_socket=str(target.socket))
            report['cases']['restore'] = restore_database(restored, archive)
            target.stop(); target.start()
            require(restore_database(restored, archive, verify_only=True)['restore_verified'], 'Restored DB restart changed contents')
            with isolated_writer(restored) as restored_store:
                old_store, hub.store = hub.store, restored_store
                try: report['restored_authentication_comparisons'] = authentication()
                finally: hub.store = old_store
    if captured_run is not None:
        require(prepared_runtime is not None, 'Prepared runtime required with captured run')
        output.mkdir(mode=0o700)
        captured['snapshot'] = read_snapshot(captured_run / 'native-personas.json')
        private = json.loads(private_read(captured_run / 'private-fixtures.json', 1024 * 1024))
        disk = prepared_runtime / 'guest.dsk'
        require(subprocess.run(['lsof', '-t', '--', str(disk)], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL).returncode == 1, 'Prepared disk must be stopped')
        directory = output / 'machine'
        directory.mkdir(mode=0o700)
        shutil.copyfile(disk, directory / 'guest.dsk')
        report = {'complete': False, 'native_snapshot': captured['snapshot'].report(),
                  'prepared_runtime': str(prepared_runtime), 'cases': {}}
        original = source_hashes()
        with ExitStack() as stack:
            ports = {}
            for line in BRIDGE_LINES:
                connection = stack.enter_context(socket.socket())
                connection.bind(('127.0.0.1', 0)); ports[line] = connection.getsockname()[1]
        machine = private_emulator(directory, ports, reuse=True)
        try:
            machine.boot(); machine.command('daytime')
            with NativeInspector(machine.port) as native, LocalMariaDb(output / 'db', column_schema=column_schema) as database:
                native.command('copy mgwork.pm=pmhold.pm')
                config = configured(database)
                with isolated_writer(config) as store, patch('tools.persona_write_session.IDLE_TIMEOUT', 600), CreationHub(machine, ports, store, database) as hub:
                    exercise(machine, native, database, store, hub, private['passwords'], private['controls'], {}, report)
                    require(not hub.errors and not store.worker_pids, 'Migration left failed transport/workers')
                native.command('r filcom', b'\n*')
                result = native.command('tty:=mgwork.pm,pmhold.pm/b', b'\n*')
                require('No differences encountered' in result, 'Migration/restore touched retained native personas')
                native.connection.write(b'\x1a'); native.receive(b'\n.'); native.at_monitor = True
            require(source_hashes() == original, 'Original source changed')
            machine.command('r opr', 'OPR>'); machine.child.send('set ksys now\r')
            machine.child.expect_exact('KSYS processing completed', timeout=120)
            report.update(complete=True, source_unchanged=True, native_personas_unchanged=True, clean_shutdown=True)
        finally:
            (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
            machine.stop()
        print('Native migration and restored login checks complete:', output, flush=True)
        return
    with patch.object(creation, 'NEW_NAMES', ('Oldmig',)), patch.object(creation, 'prepare', prepared), \
            patch.object(creation, 'build_guest', build_guest), patch.object(creation, 'native_controls', native_controls), \
            patch.object(creation, 'enable_writes', configured), patch.object(creation, 'exercise', exercise):
        if column_schema:
            database_factory = creation.LocalMariaDb
            with patch.object(creation, 'LocalMariaDb', lambda directory: database_factory(directory,column_schema=True)):
                creation.run(output)
        else: creation.run(output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=creation.ROOT / 'runtime' / f'migration-native-{time.time_ns()}')
    parser.add_argument('--captured-run', type=Path, help='Reuse a completed private capture and credential fixture')
    parser.add_argument('--prepared-runtime', type=Path, help='Stopped verified external runtime directory to copy')
    parser.add_argument('--column-schema', action='store_true', help='Exercise authoritative readable column storage')
    args = parser.parse_args()
    if bool(args.captured_run) != bool(args.prepared_runtime): parser.error('Both reuse paths are required together')
    run(args.output.resolve(), captured_run=args.captured_run.resolve() if args.captured_run else None,
        prepared_runtime=args.prepared_runtime.resolve() if args.prepared_runtime else None, column_schema=args.column_schema)
