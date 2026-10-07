"""Real read-only MariaDB acceptance, optionally through a disposable PRREAD guest."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import json
from pathlib import Path
import socket
import threading
import time

import pymysql

from tools.audit_archwizards import MAX_BOOT_ATTEMPTS
from tools.inspect_game import NativeInspector
from tools.persona_errors import InvalidRecord, StoreUnavailable
from tools.persona_mariadb import isolated_mariadb
from tools.persona_protocol import pack_name, LogicalRecord
from tests.mariadb_fixture import LocalMariaDb, DATABASE, READER
from tests.integration_persona_read import Hub, fixture, probe, verify_persona_file
from tests.integration_storage_bridge import ROOT, BRIDGE_LINES, private_emulator
from tests.integration_storage_channels import GuestMonitor
from tests.integration_provisioning import source_hashes, require


def expect_unavailable(store, key):
    started = time.monotonic()
    try:
        store.get(key)
    except StoreUnavailable:
        seconds = time.monotonic() - started
        require(seconds < 2.5, 'Database failure exceeded lookup plus cleanup bound')
        require(not store.worker_pids, 'A database worker survived failure')
        return round(seconds, 3)
    raise AssertionError('Database failure was reported as a record or absence')


def host_checks(database, store):
    key = pack_name('fred')
    require(store.get(key) == LogicalRecord(fixture(key)), 'Database changed raw record bits')
    require(store.get(pack_name('missing')) is None, 'Missing row was not absent')
    for name in ('broken', 'future', 'mismatch', 'large', 'jsonnull'):
        try:
            store.get(pack_name(name))
        except InvalidRecord:
            continue
        raise AssertionError('Invalid database row was accepted: ' + name)
    with isolated_mariadb(database.reader_config('other')) as other:
        require(other.get(key).words[0] == 8, 'Configured namespace was ignored')
    with isolated_mariadb(database.reader_config('absent')) as other:
        require(other.get(key) is None, 'Lookup crossed namespaces')
    # Actual grants independently prohibit mutation, even without adapter policy.
    config = database.reader_config()
    with pymysql.connect(unix_socket=config.unix_socket, user=READER, password=config.password,
                         database=DATABASE, autocommit=True) as connection, connection.cursor() as cursor:
        try:
            cursor.execute('DELETE FROM personas WHERE 1=0')
        except pymysql.err.OperationalError as error:
            require(error.args[0] == 1142, 'Unexpected read-only denial')
        else:
            raise AssertionError('Reader has mutation privileges')
    result = {'records_and_statuses': True, 'namespace_isolation': True, 'select_only_account': True}
    with database.admin() as connection, connection.cursor() as cursor:
        cursor.execute('LOCK TABLES ' + DATABASE + '.personas WRITE')
        try:
            result['locked_seconds'] = expect_unavailable(store, key)
        finally:
            cursor.execute('UNLOCK TABLES')
    database.pause()
    try:
        result['paused_seconds'] = expect_unavailable(store, key)
    finally:
        database.resume()
    database.grant_reads(False)
    try:
        result['denied_seconds'] = expect_unavailable(store, key)
    finally:
        database.grant_reads(True)
    database.stop()
    result['stopped_seconds'] = expect_unavailable(store, key)
    database.start()
    require(store.get(key) == LogicalRecord(fixture(key)), 'Read failed after database restart')
    require(not store.worker_pids, 'Workers leaked after recovery')
    result['restart_recovery'] = True
    return result


class DatabaseHub(Hub):
    def __init__(self, machine, ports, store):
        super().__init__(machine, ports)
        self.store = store

    def fetch(self, name):
        return self.store.get(name)


def native_checks(output, database, store, report):
    machine = None
    try:
        with ExitStack() as stack:
            sockets = [stack.enter_context(socket.socket()) for _ in BRIDGE_LINES]
            ports = {}
            for line, sock in zip(BRIDGE_LINES, sockets):
                sock.bind(('127.0.0.1', 0))
                ports[line] = sock.getsockname()[1]
        for attempt in range(MAX_BOOT_ATTEMPTS):
            print('Database PRREAD boot:', attempt + 1, flush=True)
            machine = private_emulator(output / f'machine-{attempt+1}', ports)
            try:
                machine.boot()
                machine.command('daytime')
                for line in BRIDGE_LINES:
                    require('?' not in machine.command(f'set tty tty{line:o}: slave'), 'Cannot configure bridge')
                break
            except Exception:
                machine.stop()
                machine = None
                if attempt + 1 == MAX_BOOT_ATTEMPTS:
                    raise
        with NativeInspector(machine.port) as installer:
            installer.command('assign dsk: bcl:')
            installer.command('set tty no altmode')
            installer.install_source('prread', (ROOT / 'tools/fixtures/PRREAD.BCL').read_text())
            installer.command('protect prread.exe<055>')
            installer.command('copy r1bef.pm=mud.?pm')
            with GuestMonitor(machine.port, output / 'a.txt') as a, GuestMonitor(machine.port, output / 'b.txt') as b, \
                    DatabaseHub(machine, ports, store) as hub:
                for name, expected in (('fred', 'FOUND'), ('abcdefghi', 'FOUND'), ('test1', 'FOUND'),
                                       ('missing', 'NOT_FOUND'), ('broken', 'INVALID_RECORD'),
                                       ('future', 'INVALID_RECORD'), ('mismatch', 'INVALID_RECORD'),
                                       ('large', 'INVALID_RECORD'), ('jsonnull', 'INVALID_RECORD')):
                    print('Database native lookup:', name, expected, flush=True)
                    report[name] = probe(a, hub, name, expected)
                with database.admin() as connection, connection.cursor() as cursor:
                    cursor.execute('LOCK TABLES ' + DATABASE + '.personas WRITE')
                    try:
                        report['locked'] = probe(a, hub, expected='UNAVAILABLE')
                    finally:
                        cursor.execute('UNLOCK TABLES')
                database.pause()
                try:
                    report['paused'] = probe(a, hub, expected='UNAVAILABLE')
                finally:
                    database.resume()
                database.grant_reads(False)
                try:
                    report['denied'] = probe(a, hub, expected='UNAVAILABLE')
                finally:
                    database.grant_reads(True)
                database.stop()
                report['stopped'] = probe(a, hub, expected='UNAVAILABLE')
                database.start()
                report['after_restart'] = probe(b, hub)
                barrier = threading.Barrier(2)
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [pool.submit(probe, guest, hub, 'fred', 'FOUND', barrier) for guest in (a, b)]
                    pair = [future.result() for future in futures]
                require(len({row['line'] for row in pair}) == 2, 'Concurrent database reads shared a channel')
                report['parallel'] = pair
                require(not hub.errors, 'Database bridge failed: ' + repr(hub.errors))
                require(not store.worker_pids, 'Worker remained after native reads')
            verify_persona_file(installer)
    finally:
        if machine is not None:
            machine.stop()


def run(output, native=False):
    output.mkdir(mode=0o700)
    original = source_hashes()
    report = {'complete': False, 'native_requested': native}
    try:
        with LocalMariaDb(output / 'database') as database:
            for name in ('fred', 'abcdefghi', 'test1'):
                database.seed(name, fixture(pack_name(name)))
            database.seed('broken', [])
            database.seed('future', fixture(pack_name('future')), version=2)
            database.seed('mismatch', fixture(pack_name('fred')))
            database.seed('large', [0] * 1000)
            database.seed('jsonnull', None)
            database.seed('fred', (8,) + fixture(pack_name('fred'))[1:], namespace='other')
            before = database.digest()
            report['mariadb_version'] = database.version
            with isolated_mariadb(database.reader_config()) as store:
                report['host'] = host_checks(database, store)
                if native:
                    report['native'] = {}
                    native_checks(output, database, store, report['native'])
            require(before == database.digest(), 'Read-only tests changed database rows')
            report['database_rows_unchanged'] = True
        require(original == source_hashes(), 'Original source changed')
        report.update(complete=True, source_unchanged=True, persona_bytes_unchanged=True if native else None)
        print('MariaDB read checks complete:', output, flush=True)
    except BaseException as error:
        # Do not include driver exception strings or credentials in reports.
        report['error_type'] = type(error).__name__
        raise
    finally:
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native', action='store_true')
    parser.add_argument('--output', type=Path, default=ROOT / 'runtime' / f'persona-db-{time.time_ns()}')
    args = parser.parse_args()
    run(args.output.resolve(), args.native)
