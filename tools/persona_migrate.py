"""One-way native-persona import and verification. No external-to-native conversion."""
import argparse
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import secrets

from tools.persona_mariadb import MariaDbConfig, decode_row
from tools.persona_mariadb import payload_projection, insert_persona
from tools.persona_timestamps import table_ddl
from tools.persona_protocol import WORD_MASK
from tools.persona_snapshot import (MigrationError, MAX_SLOTS, read_snapshot, private_read,
                                   strict_json, logical_digest)

ROOT = Path(__file__).resolve().parents[1]
CONFIG_LIMIT = 16 * 1024
ADMIN_TIMEOUT = 30
LOCK_WAIT = 5
RECEIPT_DDL = ROOT / 'tools/fixtures/persona_imports.sql'


def load_config(path):
    try:
        value = strict_json(private_read(path, CONFIG_LIMIT))
        if not isinstance(value, dict): raise ValueError()
        return MariaDbConfig(**value)
    except (TypeError, ValueError):
        raise MigrationError('Invalid private database configuration') from None


@contextmanager
def connect(config):
    import pymysql
    connection = pymysql.connect(host=config.host, port=config.port,
        unix_socket=config.unix_socket or None, database=config.database, user=config.user,
        password=config.password, charset='utf8mb4', binary_prefix=True, local_infile=False,
        autocommit=True, connect_timeout=LOCK_WAIT, read_timeout=ADMIN_TIMEOUT, write_timeout=ADMIN_TIMEOUT)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET SESSION time_zone='+00:00'")
            cursor.execute('SET SESSION lock_wait_timeout=%s', (LOCK_WAIT,))
            cursor.execute('SET SESSION innodb_lock_wait_timeout=%s', (LOCK_WAIT,))
        yield connection
    finally:
        connection.close()


def quote_identifier(value):
    return '`' + value.replace('`', '``') + '`'


def initialize_schema(config):
    with connect(config) as connection, connection.cursor() as cursor:
        cursor.execute('SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s '
                       'UNION ALL SELECT ROUTINE_NAME FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA=%s '
                       'UNION ALL SELECT EVENT_NAME FROM information_schema.EVENTS WHERE EVENT_SCHEMA=%s LIMIT 1',
                       (config.database, config.database, config.database))
        if cursor.fetchone(): raise MigrationError('Schema initialization requires an empty database')
        cursor.execute(table_ddl())
        for name in ('personas.sql', 'persona_writes.sql', 'persona_imports.sql'):
            if name == 'personas.sql': continue
            sql = '\n'.join(line for line in (ROOT / 'tools/fixtures' / name).read_text().splitlines()
                            if not line.lstrip().startswith('--'))
            for statement in sql.split(';'):
                if statement.strip() and not statement.strip().upper().startswith('ALTER TABLE PERSONAS ADD GENERATION'):
                    cursor.execute(statement)
    return {'schema_initialized': True, 'database': config.database}


def validate_schema(connection, config):
    with connection.cursor() as cursor:
        for table, primary in (('personas', ['namespace', 'name_key']),
                               ('persona_operations', ['namespace', 'operation_id']),
                               ('persona_imports', ['namespace'])):
            cursor.execute('SELECT ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s',
                           (config.database, table))
            if cursor.fetchone() != ('InnoDB',): raise MigrationError('Migration requires the InnoDB persona schema')
            cursor.execute('SELECT COLUMN_NAME FROM information_schema.STATISTICS '
                           "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND INDEX_NAME='PRIMARY' ORDER BY SEQ_IN_INDEX",
                           (config.database, table))
            if [row[0] for row in cursor.fetchall()] != primary:
                raise MigrationError('Persona schema primary key mismatch')


def _verify(connection, config, snapshot, *, initial=False):
    records, generations = {}, set()
    with connection.cursor() as cursor:
        projection, parameters, _ = payload_projection(cursor)
        cursor.execute('SELECT name_key,' + projection + ',generation,revision FROM personas '
                       'WHERE namespace=%s ORDER BY name_key LIMIT %s',
                       (*parameters, config.namespace.encode('ascii'), MAX_SLOTS + 1))
        for row in cursor.fetchall():
            name, generation, revision = row[0],row[-2],row[-1]
            if not isinstance(name, bytes) or len(name) != 9: raise MigrationError('Invalid imported key')
            value = int.from_bytes(name, 'big')
            key = value >> 36, value & WORD_MASK
            try: record = decode_row(key, row[1:-2])
            except Exception: raise MigrationError('Invalid imported logical record') from None
            if (not isinstance(generation, bytes) or len(generation) != 9 or not any(generation)
                    or type(revision) is not int or revision < 1 or (initial and revision != 1)
                    or key in records or generation in generations):
                raise MigrationError('Imported identity metadata is invalid')
            records[key] = record; generations.add(generation)
    if records != snapshot.records: raise MigrationError('External records do not match the native snapshot')
    return {'verified': True, 'namespace': config.namespace, 'personas': len(records), 'logical_sha256': logical_digest(records)}


def verify_import(config, snapshot):
    try:
        with connect(config) as connection:
            connection.begin()
            result = _verify(connection, config, snapshot)
            connection.rollback()
            return result
    except MigrationError: raise
    except Exception: raise MigrationError('Import verification could not complete') from None


def import_snapshot(config, snapshot):
    """One transaction into an unused namespace; retries never reinsert deleted rows."""
    namespace = config.namespace.encode('ascii')
    summary = snapshot.report()
    summary['namespace'] = config.namespace
    digest = bytes.fromhex(snapshot.sha256)
    lock = 'mud86-import-' + hashlib.sha256(config.database.encode() + b'\0' + namespace).hexdigest()[:48]
    commit_attempted = False
    try:
        with connect(config) as connection, connection.cursor() as cursor:
            # Installation metadata is separate from the atomic data transaction.
            cursor.execute(RECEIPT_DDL.read_text())
            validate_schema(connection, config)
            cursor.execute('SELECT GET_LOCK(%s,%s)', (lock, LOCK_WAIT))
            if cursor.fetchone() != (1,): raise MigrationError('Another import owns this namespace')
            try:
                cursor.execute('SET TRANSACTION ISOLATION LEVEL SERIALIZABLE')
                connection.begin()
                cursor.execute('SELECT snapshot_sha256,logical_sha256,record_count,native_slots '
                               'FROM persona_imports WHERE namespace=%s FOR UPDATE', (namespace,))
                receipt = cursor.fetchone()
                expected = (digest, bytes.fromhex(summary['logical_sha256']), summary['personas'], summary['allocated_slots'])
                if receipt is not None:
                    if receipt != expected: raise MigrationError('Namespace already belongs to another native import')
                    connection.rollback()
                    return dict(summary, already_imported=True, current_state_verified=False)
                # Match the runtime writer's lock order. Gap locks on the empty
                # namespace prevent an overlapping admission/write from racing us.
                for table, key in (('persona_operations', 'operation_id'), ('personas', 'name_key')):
                    cursor.execute(f'SELECT {key} FROM {table} WHERE namespace=%s LIMIT 1 FOR UPDATE', (namespace,))
                    if cursor.fetchone(): raise MigrationError('Import requires a fresh, unused namespace')
                generations = set()
                for key, record in sorted(snapshot.records.items()):
                    generation = secrets.token_bytes(9)
                    while not any(generation) or generation in generations: generation = secrets.token_bytes(9)
                    generations.add(generation)
                    insert_persona(cursor,namespace,key,record,generation)
                _verify(connection, config, snapshot, initial=True)
                cursor.execute('INSERT INTO persona_imports(namespace,snapshot_sha256,logical_sha256,record_count,native_slots) '
                               'VALUES (%s,%s,%s,%s,%s)', (namespace, *expected))
                cursor.execute('SELECT snapshot_sha256,logical_sha256,record_count,native_slots '
                               'FROM persona_imports WHERE namespace=%s', (namespace,))
                if cursor.fetchone() != expected: raise MigrationError('Import receipt read-back failed')
                commit_attempted = True
                connection.commit()
                return dict(summary, imported=True, current_state_verified=True)
            except BaseException:
                try: connection.rollback()
                except Exception: pass
                raise
            finally:
                try: cursor.execute('SELECT RELEASE_LOCK(%s)', (lock,))
                except Exception: pass
    except MigrationError: raise
    except Exception:
        if commit_attempted:
            raise MigrationError('Import outcome uncertain; retry the identical snapshot and namespace to check its receipt') from None
        raise MigrationError('Import did not complete; the namespace was not partially imported') from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for command in ('import', 'verify'):
        child = sub.add_parser(command)
        child.add_argument('--config', type=Path, required=True)
        child.add_argument('--snapshot', type=Path, required=True)
    child = sub.add_parser('inspect')
    child.add_argument('--snapshot', type=Path, required=True)
    child = sub.add_parser('init-schema')
    child.add_argument('--config', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == 'inspect': result = read_snapshot(args.snapshot).report()
        elif args.command == 'init-schema': result = initialize_schema(load_config(args.config))
        else:
            snapshot = read_snapshot(args.snapshot)
            function = import_snapshot if args.command == 'import' else verify_import
            result = function(load_config(args.config), snapshot)
        print(json.dumps(result, sort_keys=True))
    except (MigrationError, OSError) as error:
        parser.exit(1, (str(error) if isinstance(error, MigrationError) else 'Private file operation failed') + '\n')
    except Exception:
        parser.exit(1, 'Database maintenance command failed; no credentials or records were logged\n')


if __name__ == '__main__': main()
