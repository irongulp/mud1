"""One-way import transaction acceptance on disposable MariaDB."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict, replace
import json
from pathlib import Path
import time
import subprocess
import sys
from unittest.mock import patch

from tools import persona_migrate as migration
from tools.persona_mariadb import MariaDbConfig, encode_key
from tools.persona_protocol import pack_name
from tools.persona_snapshot import MigrationError, NativeSnapshot, write_snapshot, publish_private
from tests.test_persona_migration import image
from tests.integration_persona_writes import enable_writes
from tests.integration_provisioning import require
from tests.integration_storage_bridge import ROOT
from tests.mariadb_fixture import LocalMariaDb, DATABASE


def rejected(call):
    try: call()
    except MigrationError: return
    raise AssertionError('Unsafe migration was accepted')


def verify(database):
    enable_writes(database)
    config = MariaDbConfig(database=DATABASE, user='root', password='', unix_socket=str(database.socket), namespace='imported')
    snapshot = NativeSnapshot(image())
    report = migration.import_snapshot(config, snapshot)
    require(report['current_state_verified'], 'Import was not read back')
    require(migration.verify_import(config, snapshot)['verified'], 'Full-word import verification failed')
    require(migration.import_snapshot(config, snapshot)['already_imported'], 'Import replay not identified')
    rejected(lambda: migration.import_snapshot(config, NativeSnapshot(image(('other',)))))
    with database.admin() as connection, connection.cursor() as cursor:
        cursor.execute('SELECT COUNT(DISTINCT generation),MIN(revision),MAX(revision) FROM ' + DATABASE + '.personas WHERE namespace=%s', (b'imported',))
        require(cursor.fetchone() == (2, 1, 1), 'Import did not assign fresh generation/revision metadata')
        cursor.execute('DELETE FROM ' + DATABASE + '.personas WHERE namespace=%s AND name_key=%s',
                       (b'imported', encode_key(pack_name('fred'))))
    require(migration.import_snapshot(config, snapshot)['already_imported'], 'Post-cutover retry did not use receipt')
    rejected(lambda: migration.verify_import(config, snapshot))
    with database.admin() as connection, connection.cursor() as cursor:
        cursor.execute('SELECT COUNT(*) FROM ' + DATABASE + '.personas WHERE namespace=%s', (b'imported',))
        require(cursor.fetchone()[0] == 1, 'Retry resurrected an externally deleted persona')
        cursor.execute('CREATE TRIGGER ' + DATABASE + '.reject_import BEFORE INSERT ON ' + DATABASE + '.personas '
                       "FOR EACH ROW BEGIN IF NEW.namespace='rollback' AND NEW.name_key=%s THEN "
                       "SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='test interruption'; END IF; END",
                       (encode_key(pack_name('alice')),))
    rejected(lambda: migration.import_snapshot(replace(config, namespace='rollback'), snapshot))
    with database.admin() as connection, connection.cursor() as cursor:
        cursor.execute('DROP TRIGGER ' + DATABASE + '.reject_import')
        for table in ('personas', 'persona_imports'):
            cursor.execute('SELECT COUNT(*) FROM ' + DATABASE + '.' + table + ' WHERE namespace=%s', (b'rollback',))
            require(cursor.fetchone()[0] == 0, 'Failed import left partial rows or receipt')
    require(migration.import_snapshot(replace(config, namespace='rollback'), snapshot)['imported'], 'Retry after rollback failed')
    original_connect = migration.connect
    @contextmanager
    def lost_commit(config):
        with original_connect(config) as connection:
            commit = connection.commit
            def uncertain():
                commit()
                raise OSError('synthetic lost acknowledgement')
            connection.commit = uncertain
            yield connection
    uncertain_config = replace(config, namespace='uncertain')
    with patch.object(migration, 'connect', lost_commit):
        rejected(lambda: migration.import_snapshot(uncertain_config, snapshot))
    require(migration.import_snapshot(uncertain_config, snapshot)['already_imported'], 'Lost commit reply duplicated import')
    parallel = replace(config, namespace='parallel')
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = [pool.submit(migration.import_snapshot, parallel, snapshot) for _ in range(2)]
        replies = [future.result() for future in replies]
    require(sum(bool(reply.get('imported')) for reply in replies) == 1, 'Concurrent import committed twice')
    require(migration.verify_import(parallel, snapshot)['verified'], 'Concurrent import changed words')
    database.stop(); database.start()
    require(migration.import_snapshot(parallel, snapshot)['already_imported'], 'Import receipt lost on restart')
    with database.admin() as connection, connection.cursor() as cursor:
        cursor.execute('CREATE TRIGGER ' + DATABASE + '.bad_receipt BEFORE INSERT ON ' + DATABASE + '.persona_imports '
                       "FOR EACH ROW BEGIN IF NEW.namespace='badreceipt' THEN SET NEW.record_count=NEW.record_count+1; END IF; END")
    rejected(lambda: migration.import_snapshot(replace(config, namespace='badreceipt'), snapshot))
    with database.admin() as connection, connection.cursor() as cursor:
        cursor.execute('DROP TRIGGER ' + DATABASE + '.bad_receipt')
        cursor.execute('SELECT COUNT(*) FROM ' + DATABASE + '.personas WHERE namespace=%s', (b'badreceipt',))
        require(cursor.fetchone()[0] == 0, 'Corrupted receipt was published with persona data')
    snapshot_path = database.directory.parent / 'native.json'
    config_path = database.directory.parent / 'import-config.json'
    write_snapshot(snapshot_path, snapshot)
    publish_private(config_path, lambda stream: stream.write(json.dumps(asdict(replace(config, namespace='cli'))).encode()))
    for command in ('import', 'verify'):
        reply = subprocess.run([sys.executable, '-m', 'tools.persona_migrate', command, '--config', str(config_path),
                                '--snapshot', str(snapshot_path)], capture_output=True, text=True, timeout=30)
        require(reply.returncode == 0 and 'words' not in reply.stdout and not reply.stderr, 'Migration CLI failed or exposed payload')
        require(json.loads(reply.stdout)['personas'] == 2, 'CLI report count wrong')
    with database.admin() as connection, connection.cursor() as cursor:
        cursor.execute("INSERT INTO " + DATABASE + ".persona_operations(namespace,operation_id,status,kind) VALUES ('history',%s,'ABORTED','UPDATE')", ((1).to_bytes(9, 'big'),))
    rejected(lambda: migration.import_snapshot(replace(config, namespace='history'), snapshot))
    with database.admin() as connection, connection.cursor() as cursor:
        cursor.execute('CREATE DATABASE fresh_import CHARACTER SET ascii COLLATE ascii_bin')
    fresh = replace(config, database='fresh_import', namespace='new')
    require(migration.initialize_schema(fresh)['schema_initialized'], 'Fresh schema initialization failed')
    require(migration.import_snapshot(fresh, snapshot)['imported'], 'Fresh schema could not import')
    rejected(lambda: migration.initialize_schema(fresh))
    with database.admin() as connection, connection.cursor() as cursor:
        cursor.execute('CREATE DATABASE routine_only')
        cursor.execute('CREATE PROCEDURE routine_only.existing() SELECT 1')
    rejected(lambda: migration.initialize_schema(replace(config, database='routine_only')))
    return {'lossless': True, 'rollback': True, 'commit_reply_recovery': True,
            'concurrent_import': True, 'no_reimport_after_gameplay': True, 'restart': True,
            'receipt_integrity': True, 'cli': True, 'history_rejected': True, 'fresh_schema': True}


def run(output):
    output.mkdir(mode=0o700)
    report = {'complete': False}
    try:
        with LocalMariaDb(output / 'db') as database: report.update(verify(database))
        report['complete'] = True
    finally:
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print('One-way migration checks complete:', output, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'runtime' / f'migration-{time.time_ns()}')
    run(parser.parse_args().output.resolve())
