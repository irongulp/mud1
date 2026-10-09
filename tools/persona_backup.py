"""Whole-database external backup/restore; never converts data into native files."""
import argparse
from contextlib import contextmanager
import datetime
import decimal
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import selectors
import subprocess
import tempfile
import time
import zipfile

from tools.persona_migrate import connect, load_config, quote_identifier
from tools.persona_snapshot import MigrationError, publish_private, strict_json

BACKUP_FORMAT = 'mud86-mariadb-backup'
BACKUP_VERSION = 1
MAX_SQL_BYTES = 1024 * 1024 * 1024
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
CHUNK_BYTES = 64 * 1024
COMMAND_TIMEOUT = 600
HASH_MODULUS = 1 << 256


def validate_fingerprints(manifest):
    def hex_digest(value): return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value)
    for label in ('snapshot', 'restored'):
        state = manifest[label]
        if (not isinstance(state, dict) or set(state) != {'objects', 'settings', 'tables'}
                or not isinstance(state['objects'], dict) or not isinstance(state['tables'], dict)
                or not isinstance(state['settings'], list) or len(state['settings']) != 2
                or any(not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_]+', value) for value in state['settings'])
                or any(not isinstance(key, str) or not hex_digest(value) for key, value in state['objects'].items())):
            raise MigrationError('Invalid database verification metadata')
        for name, table in state['tables'].items():
            if (not isinstance(name, str) or 'TABLE:' + name not in state['objects']
                    or not isinstance(table, dict) or set(table) != {'columns', 'rows', 'sum', 'xor'}
                    or not isinstance(table['columns'], list) or not table['columns']
                    or any(not isinstance(column, str) for column in table['columns'])
                    or len(set(table['columns'])) != len(table['columns'])
                    or type(table['rows']) is not int or table['rows'] < 0
                    or not hex_digest(table['sum']) or not hex_digest(table['xor'])):
                raise MigrationError('Invalid table verification metadata')
    before, after = manifest['snapshot'], manifest['restored']
    if before['objects'] != after['objects'] or before['settings'] != after['settings'] or before['tables'].keys() != after['tables'].keys():
        raise MigrationError('Inconsistent restore verification metadata')
    for name in before['tables']:
        first, second = before['tables'][name], after['tables'][name]
        if (first['columns'] != second['columns'] or first['rows'] != second['rows']
                or (name != 'persona_operations' and first != second)):
            raise MigrationError('Backup attempts an unsupported data transformation')


def file_digest(path):
    digest, size = hashlib.sha256(), 0
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(CHUNK_BYTES), b''):
            size += len(chunk)
            if size > MAX_SQL_BYTES: raise MigrationError('Database backup exceeds size bound')
            digest.update(chunk)
    return digest.hexdigest(), size


def write_bundle(path, sql, metadata):
    digest, size = file_digest(sql)
    manifest = dict(metadata, format=BACKUP_FORMAT, version=BACKUP_VERSION, sql_sha256=digest, sql_bytes=size)
    def write(stream):
        with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('manifest.json', json.dumps(manifest, sort_keys=True, separators=(',', ':')))
            archive.write(sql, 'database.sql')
    publish_private(path, write)


@contextmanager
def read_bundle(path):
    try:
        with Path(path).open('rb') as source:
            if os.fstat(source.fileno()).st_mode & 0o077:
                raise MigrationError('Backup must be private to its owner')
            with zipfile.ZipFile(source) as archive, tempfile.TemporaryDirectory(prefix='mud86-restore-') as directory:
                if sorted(archive.namelist()) != ['database.sql', 'manifest.json']:
                    raise MigrationError('Unexpected or duplicate backup members')
                if archive.getinfo('manifest.json').file_size > MAX_MANIFEST_BYTES:
                    raise MigrationError('Backup manifest exceeds size bound')
                manifest = strict_json(archive.read('manifest.json'))
                if (not isinstance(manifest, dict) or manifest.get('format') != BACKUP_FORMAT
                        or type(manifest.get('version')) is not int or manifest['version'] != BACKUP_VERSION
                        or not {'database', 'snapshot', 'restored', 'sql_sha256', 'sql_bytes'} <= manifest.keys()
                        or type(manifest['sql_bytes']) is not int
                        or not 0 <= manifest['sql_bytes'] <= MAX_SQL_BYTES
                        or archive.getinfo('database.sql').file_size != manifest['sql_bytes']):
                    raise MigrationError('Unsupported or malformed database backup')
                validate_fingerprints(manifest)
                sql = Path(directory) / 'database.sql'
                with archive.open('database.sql') as input_stream, sql.open('xb') as output:
                    os.fchmod(output.fileno(), 0o600)
                    size = 0
                    while True:
                        data = input_stream.read(CHUNK_BYTES)
                        if not data: break
                        size += len(data)
                        if size > MAX_SQL_BYTES: raise MigrationError('Backup expanded past size bound')
                        output.write(data)
                if file_digest(sql) != (manifest['sql_sha256'], manifest['sql_bytes']):
                    raise MigrationError('Database backup checksum mismatch')
                yield manifest, sql
    except (zipfile.BadZipFile, RuntimeError, KeyError, ValueError):
        raise MigrationError('Malformed database backup') from None


def typed(value):
    if value is None: return ['null']
    if isinstance(value, bytes): return ['bytes', value.hex()]
    if isinstance(value, str): return ['text', value]
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)): return ['date', value.isoformat()]
    if isinstance(value, datetime.timedelta): return ['interval', value.days, value.seconds, value.microseconds]
    if isinstance(value, decimal.Decimal): return ['decimal', str(value)]
    if type(value) is int: return ['integer', str(value)]
    if type(value) is float: return ['float', value.hex()]
    raise MigrationError('Unsupported database value type for verification')


def digest_row(row):
    encoded = json.dumps([typed(value) for value in row], ensure_ascii=True, separators=(',', ':')).encode()
    return int.from_bytes(hashlib.sha256(encoded).digest(), 'big')


def objects(connection, config):
    found = []
    with connection.cursor() as cursor:
        cursor.execute('SELECT TABLE_NAME,TABLE_TYPE FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME', (config.database,))
        for name, kind in cursor.fetchall():
            if kind not in ('BASE TABLE', 'VIEW'): raise MigrationError('Unsupported database object type')
            found.append(('TABLE' if kind == 'BASE TABLE' else 'VIEW', name))
        cursor.execute('SELECT ROUTINE_NAME,ROUTINE_TYPE FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA=%s', (config.database,))
        found.extend((kind, name) for name, kind in cursor.fetchall())
        for kind, table, schema_column, name_column in (
                ('TRIGGER', 'TRIGGERS', 'TRIGGER_SCHEMA', 'TRIGGER_NAME'),
                ('EVENT', 'EVENTS', 'EVENT_SCHEMA', 'EVENT_NAME')):
            cursor.execute(f'SELECT {name_column} FROM information_schema.{table} WHERE {schema_column}=%s', (config.database,))
            found.extend((kind, row[0]) for row in cursor.fetchall())
    return sorted(found)


def schema(connection, config):
    result = {}
    with connection.cursor() as cursor:
        for kind, name in objects(connection, config):
            cursor.execute(f'SHOW CREATE {kind} {quote_identifier(config.database)}.{quote_identifier(name)}')
            row = cursor.fetchone()
            values = {column[0]: typed(value) for column, value in zip(cursor.description, row)
                      if column[0].lower() != 'created'}
            if not any(value is not None and ('create ' in column[0].lower() or column[0].lower() == 'sql original statement')
                       for column, value in zip(cursor.description, row)):
                raise MigrationError('Cannot read complete database object definition')
            result[kind + ':' + name] = hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()
        cursor.execute('SELECT DEFAULT_CHARACTER_SET_NAME,DEFAULT_COLLATION_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s', (config.database,))
        settings = list(cursor.fetchone())
    return {'objects': result, 'settings': settings}


@contextmanager
def locked(connection, config, *, write=False):
    tables = [(kind, name) for kind, name in objects(connection, config) if kind in ('TABLE', 'VIEW')]
    if tables:
        with connection.cursor() as cursor:
            cursor.execute('LOCK TABLES ' + ','.join(quote_identifier(config.database) + '.' + quote_identifier(name)
                           + (' WRITE' if write and kind == 'TABLE' else ' READ') for kind, name in tables))
    try: yield
    finally:
        if tables:
            with connection.cursor() as cursor: cursor.execute('UNLOCK TABLES')


def fingerprint(connection, config):
    """Bounded-memory multiset fingerprints; include duplicate rows and opaque data."""
    import pymysql
    base = schema(connection, config)
    raw, ready = dict(base, tables={}), dict(base, tables={})
    for kind, name in objects(connection, config):
        if kind != 'TABLE': continue
        with connection.cursor(pymysql.cursors.SSCursor) as cursor:
            cursor.execute('SELECT * FROM ' + quote_identifier(config.database) + '.' + quote_identifier(name))
            columns = [field[0] for field in cursor.description]
            status_index = columns.index('status') if name == 'persona_operations' and 'status' in columns else None
            count = total = exclusive = ready_total = ready_exclusive = 0
            for row in cursor:
                value = digest_row(row)
                count += 1; total = (total + value) % HASH_MODULUS; exclusive ^= value
                if status_index is not None and row[status_index] in ('INIT', 'OPEN'):
                    changed = list(row); changed[status_index] = 'ABORTED'
                    value = digest_row(changed)
                ready_total = (ready_total + value) % HASH_MODULUS; ready_exclusive ^= value
        raw['tables'][name] = {'columns': columns, 'rows': count, 'sum': f'{total:064x}', 'xor': f'{exclusive:064x}'}
        ready['tables'][name] = {'columns': columns, 'rows': count, 'sum': f'{ready_total:064x}', 'xor': f'{ready_exclusive:064x}'}
    return raw, ready


@contextmanager
def client_options(config):
    def escaped(value):
        return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t') + '"'
    with tempfile.TemporaryDirectory(prefix='mud86-db-options-') as directory:
        path = Path(directory) / 'client.cnf'
        values = {'user': config.user, 'password': config.password, 'default-character-set': 'utf8mb4'}
        if config.unix_socket: values.update(socket=config.unix_socket, protocol='SOCKET')
        else: values.update(host=config.host, port=config.port, protocol='TCP')
        with path.open('x') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write('[client]\n' + ''.join(key + '=' + escaped(value) + '\n' for key, value in values.items()))
        yield '--defaults-file=' + str(path)


def executable(name):
    result = shutil.which(name)
    if result is None: raise MigrationError('Required MariaDB client tool is not installed: ' + name)
    return result


def capture_dump(command, path, *, timeout, limit=MAX_SQL_BYTES):
    """Bound the dumper's output and whole execution, not just its socket reads."""
    if timeout <= 0 or limit <= 0: raise MigrationError('Invalid dump bounds')
    process = None
    created = False
    deadline = time.monotonic() + timeout
    try:
        with Path(path).open('xb') as output:
            created = True
            os.fchmod(output.fileno(), 0o600)
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            os.set_blocking(process.stdout.fileno(), False)
            size = 0
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0: raise MigrationError('Database dump deadline exceeded')
                    if not selector.select(remaining): continue
                    data = os.read(process.stdout.fileno(), CHUNK_BYTES)
                    if not data: break
                    size += len(data)
                    if size > limit: raise MigrationError('Database dump exceeds size bound')
                    output.write(data)
            remaining = deadline - time.monotonic()
            if remaining <= 0 or process.wait(timeout=remaining) != 0:
                raise MigrationError('Database dump failed')
    except BaseException as error:
        if created: Path(path).unlink(missing_ok=True)
        if isinstance(error, subprocess.TimeoutExpired):
            raise MigrationError('Database dump deadline exceeded') from None
        raise
    finally:
        if process is not None:
            if process.poll() is None: process.kill()
            process.wait()
            process.stdout.close()


def backup_database(config, path, *, timeout=COMMAND_TIMEOUT):
    with tempfile.TemporaryDirectory(prefix='mud86-backup-') as directory, connect(config) as connection:
        sql = Path(directory) / 'database.sql'
        with locked(connection, config):
            before, ready = fingerprint(connection, config)
            if not {'personas', 'persona_operations'} <= before['tables'].keys():
                raise MigrationError('Selected database is not an external persona store')
            with client_options(config) as options:
                command = [executable('mariadb-dump'), options, '--single-transaction', '--skip-lock-tables',
                           '--skip-add-locks', '--hex-blob', '--routines', '--events', '--triggers',
                           '--complete-insert', '--order-by-primary', '--skip-comments', '--no-tablespaces', '--', config.database]
                capture_dump(command, sql, timeout=timeout)
            if schema(connection, config) != {key: before[key] for key in ('objects', 'settings')}:
                raise MigrationError('Database schema changed during backup')
        write_bundle(path, sql, {'database': config.database, 'snapshot': before, 'restored': ready,
                                'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat()})
    return {'backup_complete': True, 'database': config.database, 'whole_database': True, 'tables': len(before['tables']),
            'rows': sum(table['rows'] for table in before['tables'].values())}


def restore_database(config, path, *, timeout=COMMAND_TIMEOUT, verify_only=False):
    with read_bundle(path) as (manifest, sql), connect(config) as connection:
        if manifest['database'] != config.database:
            raise MigrationError('Restore must retain the original database name on a recovery instance')
        with connection.cursor() as cursor:
            cursor.execute('SELECT @@global.event_scheduler')
            if str(cursor.fetchone()[0]).upper() not in ('OFF', 'DISABLED'):
                raise MigrationError('Recovery instance must have the event scheduler disabled')
        current_objects = objects(connection, config)
        loaded = False
        if not current_objects and not verify_only:
            charset, collation = manifest['snapshot']['settings']
            with connection.cursor() as cursor:
                cursor.execute('ALTER DATABASE ' + quote_identifier(config.database) + ' CHARACTER SET '
                               + quote_identifier(charset) + ' COLLATE ' + quote_identifier(collation))
            with client_options(config) as options, sql.open('rb') as input_stream:
                result = subprocess.run([executable('mariadb'), options, '--binary-mode', '--', config.database],
                                        stdin=input_stream, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout)
            if result.returncode: raise MigrationError('Restore incomplete; keep services stopped and use an empty recovery database')
            loaded = True
        with locked(connection, config, write=not verify_only):
            actual, _ = fingerprint(connection, config)
            if actual == manifest['restored']:
                return {'restore_verified': True, 'already_restored': not loaded, 'fenced_operations': 0}
            if verify_only or actual != manifest['snapshot']:
                raise MigrationError('Recovery database differs from the backup; existing data was not overwritten')
            with connection.cursor() as cursor:
                cursor.execute("UPDATE persona_operations SET status='ABORTED' WHERE status IN ('INIT','OPEN')")
                fenced = cursor.rowcount
            actual, _ = fingerprint(connection, config)
            if actual != manifest['restored']: raise MigrationError('Recovery verification failed after fencing; do not start services')
        return {'restore_verified': True, 'already_restored': False, 'fenced_operations': fenced}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('backup', 'restore', 'verify-restore', 'check'))
    parser.add_argument('--config', type=Path)
    parser.add_argument('--file', type=Path, required=True)
    parser.add_argument('--timeout', type=float, default=COMMAND_TIMEOUT)
    args = parser.parse_args()
    if args.timeout <= 0: parser.error('Timeout must be positive')
    if args.command != 'check' and args.config is None: parser.error('--config is required')
    try:
        if args.command == 'check':
            with read_bundle(args.file) as (manifest, _): result = {'backup_valid': True, 'database': manifest['database']}
        else:
            config = load_config(args.config)
            if args.command == 'backup': result = backup_database(config, args.file, timeout=args.timeout)
            else: result = restore_database(config, args.file, timeout=args.timeout, verify_only=args.command == 'verify-restore')
        print(json.dumps(result, sort_keys=True))
    except MigrationError as error: parser.exit(1, str(error) + '\n')
    except Exception: parser.exit(1, 'External backup/restore failed; no credentials or SQL payload were logged\n')


if __name__ == '__main__': main()
