"""Readable authoritative columns, legacy upgrade and SQL update acceptance."""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import secrets
import time

from tools.persona_columns import DATA_COLUMNS, ColumnPersona
from tools.persona_schema import upgrade_columns, grant_column_writer
from tools.persona_mariadb import MariaDbConfig, encode_key
from tools.persona_protocol import pack_name
from tools.persona_writes import isolated_writer
from tools.persona_backup import backup_database, restore_database
from tests.integration_persona_writes import enable_writes, changed
from tests.integration_persona_read import ROOT, fixture
from tests.integration_provisioning import require
from tests.mariadb_fixture import LocalMariaDb, DATABASE
from tests.integration_persona_migration import rejected


def verify(database, output):
    key = pack_name('fred')
    database.seed('fred', fixture(key))
    writer_config = enable_writes(database, allow_create=True, allow_delete=True)
    admin = replace(writer_config, user='root', password='')
    with isolated_writer(writer_config) as store:
        original = store.get(key)
        require(store.begin(701, key).status == 'OPEN', 'Legacy pending snapshot failed')
    with database.admin() as connection, connection.cursor() as cursor:
        cursor.execute('SELECT generation,revision,updated_at FROM ' + DATABASE + '.personas')
        metadata = cursor.fetchone()
    backup_database(admin, output / 'before-columns.zip')
    require(upgrade_columns(admin)['upgraded'], 'Upgrade failed')
    grant_column_writer(admin, writer_config.user)
    require(upgrade_columns(admin)['already_upgraded'], 'Upgrade replay not identified')
    with database.admin() as connection, connection.cursor() as cursor:
        cursor.execute('SHOW COLUMNS FROM ' + DATABASE + '.personas')
        columns = {row[0] for row in cursor.fetchall()}
        require('words' not in columns and set(DATA_COLUMNS) <= columns, 'Values are not stored as columns')
        cursor.execute('SELECT name,score,strength,games_played,generation,revision,updated_at FROM ' + DATABASE + '.personas')
        row = cursor.fetchone()
        require(row[0] == 'fred' and row[1] == -(1<<35) and row[2] == 511 and row[3] == 7, 'Decoded fields wrong')
        require(row[4:] == metadata, 'Upgrade modified identity/revision/time')
    with isolated_writer(writer_config) as store:
        require(store.get(key) == original, 'Column migration lost native bits')
        require(store.commit(701, key, original).status == 'COMMITTED', 'Pre-upgrade operation no longer commits')
        require(store.begin_purge(702, key).status == 'OPEN', 'Column purge snapshot failed')
        require(store.begin(703, key).status == 'OPEN', 'Column update snapshot failed')
        with database.admin() as connection, connection.cursor() as cursor:
            cursor.execute('UPDATE ' + DATABASE + '.personas SET score=1500,strength=80,revision=revision+1 '
                           'WHERE namespace=%s AND name=%s', (b'mud', 'fred'))
            require(cursor.rowcount == 1, 'Human-readable UPDATE could not select name')
        current = store.get(key)
        require(current.words[3] == 1500 and current.words[4] >> 27 == 80, 'SQL changes did not translate to BCPL')
        require(current.words[7:] == original.words[7:], 'SQL edit changed password/opaque words')
        require(store.commit(703, key, changed(original, 42)).status == 'CONFLICT', 'SQL edit was overwritten by stale snapshot')
        require(store.purge(702, key).status == 'CONFLICT', 'SQL edit bypassed PURGE guard')
        require(store.begin(704, key).status == 'OPEN', 'Fresh update failed')
        require(store.commit(704, key, current).status == 'COMMITTED', 'Column adapter could not SAVE')
        fresh = pack_name('newborn')
        require(store.begin_create(705, fresh).status == 'OPEN', 'Column creation failed')
        from tools.persona_protocol import LogicalRecord
        require(store.create(705, fresh, LogicalRecord(fixture(fresh))).status == 'COMMITTED', 'Column create publication failed')
        require(store.begin_delete(706, fresh).status == 'OPEN' and store.delete(706, fresh).status == 'COMMITTED', 'Column death failed')
        require(store.begin_next(707, None).record.name_words == key, 'Column enumeration failed')
        require(store.resolve(707).status == 'ABORTED', 'Column enumeration view not fenced')
    rejected_count = 0
    with database.admin() as connection, connection.cursor() as cursor:
        import pymysql
        for assignment in ('score=34359738368', 'strength=512', 'games_played=262144', 'wizard_mode=2',
                           'unknown_state_bits=1', "name='other'", "sex='other'", 'password_word=68719476736'):
            try: cursor.execute('UPDATE ' + DATABASE + '.personas SET ' + assignment + " WHERE name='fred'")
            except pymysql.MySQLError: rejected_count += 1
            else: raise AssertionError('Invalid SQL column update accepted: ' + assignment)
    database.stop(); database.start()
    with isolated_writer(writer_config) as store:
        require(store.get(key).words[3] == 1500, 'Column values lost after DB restart')
    archive = output / 'column-store.zip'
    backup_database(admin,archive)
    with LocalMariaDb(output / 'recovery') as target:
        with target.admin() as connection, connection.cursor() as cursor:
            cursor.execute('DROP TABLE ' + DATABASE + '.personas')
        recovered = replace(admin,unix_socket=str(target.socket))
        require(restore_database(recovered,archive)['restore_verified'], 'Column backup did not restore')
        with isolated_writer(recovered) as store:
            require(store.get(key).words[3] == 1500, 'Restore changed column values')
            require(store.resolve(701).status == 'COMMITTED', 'Restore lost historical journal outcome')
    # Corruption must leave the old authority untouched rather than publish a
    # partially converted table or silently omit the invalid record.
    with LocalMariaDb(output / 'invalid') as invalid:
        invalid.seed('fred',fixture(key))
        invalid_config = enable_writes(invalid)
        invalid_admin = replace(invalid_config,user='root',password='')
        with invalid.admin() as connection, connection.cursor() as cursor:
            cursor.execute('UPDATE ' + DATABASE + '.personas SET words=%s', ('[]',))
        rejected(lambda: upgrade_columns(invalid_admin))
        with invalid.admin() as connection, connection.cursor() as cursor:
            cursor.execute('SELECT words FROM ' + DATABASE + '.personas')
            require(cursor.fetchone()[0] == '[]', 'Failed migration changed source record')
            cursor.execute('SELECT COUNT(*) FROM ' + DATABASE + '.personas_column_upgrade')
            require(cursor.fetchone()[0] == 0, 'Failed migration published staged rows')
    return {'lossless': True, 'metadata_preserved': True, 'sql_updates': True, 'journal_compatible': True,
            'constraints_rejected': rejected_count, 'create_update_delete_purge_enumeration': True,
            'restart': True, 'backup_restore': True, 'failed_upgrade_preserves_authority': True}


def run(output):
    output.mkdir(mode=0o700)
    report = {'complete': False}
    try:
        with LocalMariaDb(output / 'db') as database: report.update(verify(database, output))
        report['complete'] = True
    finally:
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print('Persona column acceptance complete:', output, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'runtime' / f'persona-columns-{time.time_ns()}')
    run(parser.parse_args().output.resolve())
