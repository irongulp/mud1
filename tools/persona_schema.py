"""Explicit offline upgrade from word arrays to authoritative persona columns."""
import argparse
from contextlib import ExitStack
from dataclasses import replace
import json

from tools.persona_columns import ColumnPersona, COLUMN_FORMAT, DATA_COLUMNS, DATA_SQL, table_ddl
from tools.persona_timestamps import TIMESTAMP_FORMAT,TIMESTAMP_SQL
from tools.persona_mariadb import decode_row, MAX_RECORD_JSON_BYTES, payload_projection
from tools.persona_migrate import connect, load_config, quote_identifier
from tools.persona_protocol import WORD_MASK
from tools.persona_snapshot import MigrationError
from pathlib import Path

STAGING = 'personas_column_upgrade'
ARCHIVE = 'personas_words_archive'
MAX_UPGRADE_ROWS = 65536
LEGACY_COLUMNS = {'namespace','name_key','format_version','words','generation','revision','updated_at'}


def grant_column_writer(config, user):
    if not user or '\0' in user: raise MigrationError('Invalid writer account')
    with connect(config) as connection, connection.cursor() as cursor:
        _,_,version=payload_projection(cursor)
        sql=TIMESTAMP_SQL if version==TIMESTAMP_FORMAT else DATA_SQL
        cursor.execute('GRANT UPDATE (' + sql + ',revision) ON ' + quote_identifier(config.database)
                       + '.personas TO %s@localhost', (user,))


def upgrade_columns(config):
    """Writers/DDL must be stopped. Table swap is atomic; failed staging is retained."""
    with connect(config) as connection, connection.cursor() as cursor:
        projection, parameters, readable = payload_projection(cursor)
        if readable: return {'already_upgraded': True, 'upgraded': False}
        cursor.execute("SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='personas'")
        if {row[0] for row in cursor.fetchall()} != LEGACY_COLUMNS:
            raise MigrationError('Upgrade supports only the complete legacy persona schema; preserve additional columns explicitly')
        cursor.execute("SELECT ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='personas'")
        if cursor.fetchone() != ('InnoDB',): raise MigrationError('Upgrade requires InnoDB')
        cursor.execute("SELECT TRIGGER_NAME FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA=DATABASE() AND EVENT_OBJECT_TABLE='personas'")
        if cursor.fetchone(): raise MigrationError('Persona triggers need an explicit migration before upgrading')
        cursor.execute("SELECT CONSTRAINT_NAME FROM information_schema.KEY_COLUMN_USAGE WHERE TABLE_SCHEMA=DATABASE() AND (TABLE_NAME='personas' AND REFERENCED_TABLE_NAME IS NOT NULL OR REFERENCED_TABLE_NAME='personas')")
        if cursor.fetchone(): raise MigrationError('Persona foreign keys need an explicit migration before upgrading')
        cursor.execute('SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME IN (%s,%s)', (STAGING, ARCHIVE))
        if cursor.fetchone(): raise MigrationError('An earlier schema upgrade left staging/archive data; inspect it before retrying')
        # DDL cannot be rolled back. The existing authoritative table is left
        # intact until complete round-trip and metadata comparison succeeds.
        cursor.execute(table_ddl(STAGING))
        cursor.execute('LOCK TABLES personas WRITE,' + STAGING + ' WRITE')
        try:
            cursor.execute('SELECT namespace,name_key,format_version,OCTET_LENGTH(words),LEFT(CAST(words AS BINARY),%s),'
                           'generation,revision,updated_at FROM personas ORDER BY namespace,name_key LIMIT %s',
                           (MAX_RECORD_JSON_BYTES+1, MAX_UPGRADE_ROWS+1))
            source = cursor.fetchall()
            if len(source) > MAX_UPGRADE_ROWS: raise MigrationError('Schema upgrade exceeds row bound')
            expected = []
            for namespace, name, version, length, words, generation, revision, updated in source:
                if (not isinstance(name, bytes) or len(name) != 9 or not isinstance(generation, bytes)
                        or len(generation) != 9 or not any(generation) or type(revision) is not int or revision < 1):
                    raise MigrationError('Legacy identity metadata is invalid')
                number = int.from_bytes(name, 'big')
                try:
                    record = decode_row((number >> 36, number & WORD_MASK), (version,length,words))
                    persona = ColumnPersona.from_record(record)
                except Exception: raise MigrationError('Legacy record cannot be converted losslessly') from None
                values = (namespace,name,COLUMN_FORMAT,*persona.values(),generation,revision,updated)
                columns = 'namespace,name_key,format_version,' + DATA_SQL + ',generation,revision,updated_at'
                cursor.execute('INSERT INTO ' + STAGING + '(' + columns + ') VALUES (' + ','.join(['%s']*len(values)) + ')', values)
                expected.append((namespace,name,record,generation,revision,updated))
            cursor.execute('SELECT namespace,name_key,format_version,' + DATA_SQL + ',generation,revision,updated_at '
                           'FROM ' + STAGING + ' ORDER BY namespace,name_key')
            actual = []
            for row in cursor.fetchall():
                number = int.from_bytes(row[1], 'big')
                record = decode_row((number >> 36,number & WORD_MASK), row[2:-3])
                actual.append((row[0],row[1],record,*row[-3:]))
            if actual != expected: raise MigrationError('Persona column round-trip or metadata verification failed')
        finally:
            cursor.execute('UNLOCK TABLES')
        # MariaDB forbids RENAME with LOCK TABLES active. This deliberately
        # requires offline writers/DDL; recheck the source after releasing locks.
        cursor.execute('SELECT namespace,name_key,format_version,OCTET_LENGTH(words),LEFT(CAST(words AS BINARY),%s),'
                       'generation,revision,updated_at FROM personas ORDER BY namespace,name_key LIMIT %s',
                       (MAX_RECORD_JSON_BYTES+1,MAX_UPGRADE_ROWS+1))
        if cursor.fetchall() != source: raise MigrationError('Legacy rows changed during offline upgrade; no table swap performed')
        cursor.execute('RENAME TABLE personas TO ' + ARCHIVE + ',' + STAGING + ' TO personas')
        # Preserve the old table as explicit historical data until the operator
        # has verified deployment and backup. Runtime only accesses personas.
        return {'upgraded': True, 'personas': len(source), 'legacy_archive': ARCHIVE, 'format_version': COLUMN_FORMAT}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument('--config')
    selection.add_argument('--local-state', type=Path, help='Stopped local lab state; use its private Unix socket operator account')
    parser.add_argument('--backup', required=True, help='Fresh whole-database backup output before upgrade')
    parser.add_argument('--writer-user', help='Existing local runtime account to grant UPDATE on named fields')
    parser.add_argument('--timestamps',action='store_true',help='Upgrade v2 native/boolean fields to v3 timestamp fields')
    args = parser.parse_args()
    try:
        from tools.persona_backup import backup_database
        with ExitStack() as stack:
            writer = args.writer_user
            if args.local_state:
                from tools.serve_external import StateLock, load_local_config, LocalDatabase
                state = args.local_state.resolve()
                stack.enter_context(StateLock(state))
                runtime = load_local_config(state)
                # The launcher owns this private Unix-socket lab only. It must
                # be stopped (exclusive state lock); restart DB for maintenance.
                stack.enter_context(LocalDatabase(state))
                config = replace(runtime,user='root',password='')
                writer = writer or runtime.user
            else: config = load_config(args.config)
            backup_database(config, args.backup)
            if args.timestamps:
                from tools.persona_timestamp_schema import upgrade_timestamps
                result=upgrade_timestamps(config)
            else: result = upgrade_columns(config)
            if writer: grant_column_writer(config,writer)
        print(json.dumps(result, sort_keys=True))
    except MigrationError as error: parser.exit(1,str(error)+'\n')
    except Exception: parser.exit(1,'Column upgrade failed; keep writers stopped and inspect private staging state\n')


if __name__ == '__main__': main()
