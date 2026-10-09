"""Whole-store backups retain added data and fence open operations on restore."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import time
import subprocess
import sys

from tools.persona_backup import backup_database, restore_database, fingerprint
from tools.persona_migrate import import_snapshot, connect
from tools.persona_snapshot import NativeSnapshot, MigrationError, publish_private
from tools.persona_mariadb import MariaDbConfig
from tools.persona_protocol import pack_name
from tools.persona_writes import isolated_writer
from tests.test_persona_migration import image
from tests.integration_persona_writes import enable_writes
from tests.integration_persona_migration import rejected
from tests.integration_provisioning import require
from tests.integration_storage_bridge import ROOT
from tests.mariadb_fixture import LocalMariaDb, DATABASE


def verify(source, target, output):
    writer_config = enable_writes(source)
    secret = 'fixture-"\\#\n\tvalue%'
    for database in (source, target):
        with database.admin() as connection, connection.cursor() as cursor:
            cursor.execute('CREATE USER %s@localhost IDENTIFIED BY %s', ('archive_owner', secret))
            cursor.execute('GRANT ALL PRIVILEGES ON *.* TO %s@localhost', ('archive_owner',))
    config = MariaDbConfig(database=DATABASE, user='archive_owner', password=secret, unix_socket=str(source.socket))
    target_config = MariaDbConfig(database=DATABASE, user='archive_owner', password=secret, unix_socket=str(target.socket))
    import_snapshot(config, NativeSnapshot(image()))
    with isolated_writer(writer_config) as writer:
        require(writer.begin(999, pack_name('fred')).status == 'OPEN', 'Open operation fixture failed')
    with connect(config) as connection, connection.cursor() as cursor:
        cursor.execute('CREATE TABLE extra_data (id INT PRIMARY KEY, body LONGBLOB, amount DECIMAL(20,5), stamp DATETIME(6)) ENGINE=InnoDB')
        cursor.execute("INSERT INTO extra_data VALUES (1,%s,12345.01230,'2026-09-01 01:02:03.123456')", (bytes(range(256)),))
        cursor.execute('CREATE VIEW extra_view AS SELECT id,amount FROM extra_data')
        cursor.execute('CREATE TABLE extra_audit (id INT) ENGINE=InnoDB')
        cursor.execute('CREATE TRIGGER extra_trigger AFTER INSERT ON extra_data FOR EACH ROW INSERT INTO extra_audit VALUES (NEW.id)')
        cursor.execute('CREATE PROCEDURE extra_proc() SELECT COUNT(*) FROM extra_data')
        cursor.execute("CREATE EVENT extra_event ON SCHEDULE EVERY 1 DAY DISABLE DO INSERT INTO extra_audit VALUES (99)")
        before, expected = fingerprint(connection, config)
    archive = output / 'external.zip'
    require(backup_database(config, archive)['backup_complete'], 'Backup not published')
    require(archive.stat().st_mode & 0o777 == 0o600, 'Backup is not private')
    with connect(config) as connection:
        require(fingerprint(connection, config)[0] == before, 'Backup changed source data or journal')
    rejected(lambda: restore_database(target_config, archive))  # Fixture's existing personas table must not be dropped.
    with target.admin() as connection, connection.cursor() as cursor:
        cursor.execute('DROP TABLE ' + DATABASE + '.personas')
    restored = restore_database(target_config, archive)
    require(restored['restore_verified'] and restored['fenced_operations'] == 1, 'Restore did not fence open operation')
    require(restore_database(target_config, archive)['already_restored'], 'Completed restore cannot be verified/retried')
    with connect(target_config) as connection:
        require(fingerprint(connection, target_config)[0] == expected, 'Restore lost extra data, metadata or schema objects')
    target.stop(); target.start()
    require(restore_database(target_config, archive, verify_only=True)['restore_verified'], 'Restored state did not survive restart')
    with isolated_writer(target_config) as writer:
        require(writer.resolve(999).status == 'ABORTED', 'Restored pending operation remained executable')
        before_row = writer.get(pack_name('fred'))
        require(writer.commit(999, pack_name('fred'), before_row).status == 'ABORTED', 'Old commit replay bypassed restore fence')
        require(writer.begin(1000, pack_name('fred')).status == 'OPEN', 'Fresh work failed after restore')
        require(writer.commit(1000, pack_name('fred'), before_row).status == 'COMMITTED', 'Restored writer could not save')
    rejected(lambda: restore_database(target_config, archive))
    with isolated_writer(writer_config) as writer: writer.resolve(999)
    no_pending = output / 'ready.zip'
    backup_database(config, no_pending)
    with target.admin() as connection, connection.cursor() as cursor:
        cursor.execute('DROP DATABASE ' + DATABASE)
        cursor.execute('CREATE DATABASE ' + DATABASE + ' CHARACTER SET ascii COLLATE ascii_bin')
    fresh = restore_database(target_config, no_pending)
    require(fresh['restore_verified'] and not fresh['already_restored'], 'Fresh restore was reported as a replay')
    config_path = output / 'restore-config.json'
    publish_private(config_path, lambda stream: stream.write(json.dumps(asdict(target_config)).encode()))
    for command in ('check', 'verify-restore'):
        reply = subprocess.run([sys.executable, '-m', 'tools.persona_backup', command, '--file', str(no_pending),
                                '--config', str(config_path)], capture_output=True, text=True, timeout=30)
        require(reply.returncode == 0 and secret not in reply.stdout + reply.stderr, 'Backup CLI failed or exposed credentials')
    return {'whole_database': True, 'extra_blob_decimal_time': True, 'views_routines_triggers_events': True,
            'source_unchanged': True, 'pending_fenced': True, 'restart': True, 'no_overwrite_after_resume': True, 'cli': True}


def run(output):
    output.mkdir(mode=0o700)
    report = {'complete': False}
    try:
        with LocalMariaDb(output / 'src') as source, LocalMariaDb(output / 'dst') as target:
            report.update(verify(source, target, output))
        report['complete'] = True
    finally:
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print('External backup/restore checks complete:', output, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'runtime' / f'backup-{time.time_ns()}')
    run(parser.parse_args().output.resolve())
