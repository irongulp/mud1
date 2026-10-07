"""Atomic persona mutations. Creation is explicit, never an update fallback."""
import json
import secrets

from tools.persona_errors import InvalidRecord
from tools.persona_mariadb import (MariaDbPersonaStore, decode_row, encode_key,
                                  MAX_RECORD_JSON_BYTES, CONNECT_TIMEOUT, SOCKET_TIMEOUT,
                                  STATEMENT_TIMEOUT, LOCK_TIMEOUT)
from tools.persona_mariadb import payload_projection, insert_persona, update_persona
from tools.persona_protocol import LogicalRecord, WORD_MASK, validate_name_key
from tools.persona_writes import WriteResult, operation_id, UNCERTAIN_ACTIONS

MAX_REVISION = (1 << 64) - 1
INITIAL_REVISION = 1
GENERATION_BYTES = 9


def packed(record):
    return json.dumps(record.words, separators=(',', ':'))


class MariaDbWriteStore(MariaDbPersonaStore):
    def _transaction(self, action, operation, key=None, record=None):
        import pymysql
        op = operation_id(operation)
        name = encode_key(key) if key is not None else None
        cursor_key = name if action == 'begin_next' else None
        if action == 'begin_next': name = None
        namespace = self.config.namespace.encode('ascii')
        starting = action in ('begin', 'begin_delete', 'begin_create', 'begin_purge', 'begin_next')
        committing = action in ('commit', 'create')
        kind = ('PNEXT' if action == 'begin_next' else
                'PURGE' if action in ('begin_purge', 'purge') else
                'CREATE' if action in ('begin_create', 'create') else
                'DELETE' if action in ('begin_delete', 'delete') else 'UPDATE')
        connection = None
        try:
            connection = pymysql.connect(host=self.config.host, port=self.config.port,
                unix_socket=self.config.unix_socket or None, database=self.config.database,
                user=self.config.user, password=self.config.password, charset='ascii', binary_prefix=True,
                connect_timeout=CONNECT_TIMEOUT, read_timeout=SOCKET_TIMEOUT, write_timeout=SOCKET_TIMEOUT,
                autocommit=False, local_infile=False)
            with connection.cursor() as cursor:
                cursor.execute("SET SESSION time_zone='+00:00'")
                cursor.execute('SET SESSION max_statement_time = %s', (STATEMENT_TIMEOUT,))
                cursor.execute('SET SESSION lock_wait_timeout = %s', (LOCK_TIMEOUT,))
                projection, projection_params, readable = payload_projection(cursor)
                # INSERT locks the operation identity, including its previously
                # absent case. A concurrent BEGIN/COMMIT/RESOLVE must serialize.
                initial = 'INIT' if starting else 'ABORTED'
                cursor.execute('INSERT INTO persona_operations(namespace,operation_id,name_key,status,kind,cursor_key) '
                               'VALUES (%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE operation_id=operation_id',
                               (namespace, op, name, initial, kind, cursor_key))
                cursor.execute('SELECT cursor_key,kind,name_key,status,generation,revision,'
                               'LEFT(CAST(before_words AS BINARY),%s),LEFT(CAST(after_words AS BINARY),%s) '
                               'FROM persona_operations WHERE namespace=%s AND operation_id=%s FOR UPDATE',
                               (MAX_RECORD_JSON_BYTES + 1, MAX_RECORD_JSON_BYTES + 1, namespace, op))
                old_cursor, old_kind, old_name, status, generation, revision, before, after = cursor.fetchone()
                if action == 'resolve':
                    if status in ('INIT', 'OPEN'):
                        status = 'ABORTED'
                        cursor.execute('UPDATE persona_operations SET status=%s WHERE namespace=%s AND operation_id=%s',
                                       (status, namespace, op))
                    connection.commit()
                    return WriteResult(status)
                # A nameless RESOLVE tombstone fences every operation kind.
                if old_name is None and status == 'ABORTED':
                    connection.commit()
                    return WriteResult('ABORTED')
                if ((action != 'begin_next' and old_name is not None and old_name != name)
                        or (action == 'begin_next' and old_cursor != cursor_key)):
                    connection.rollback()
                    return WriteResult('REUSED')
                if old_kind != kind and not (action == 'purge' and old_kind == 'PNEXT'):
                    connection.rollback()
                    return WriteResult('REUSED')
                if starting and status != 'INIT':
                    snapshot = LogicalRecord(json.loads(before)) if status == 'OPEN' else None
                    connection.commit()
                    return WriteResult(status, snapshot)
                if action in ('delete', 'purge') and status != 'OPEN':
                    connection.commit()
                    return WriteResult(status)
                if committing:
                    if record is None or record.name_words != tuple(key):
                        connection.rollback()
                        return WriteResult('INVALID_RECORD')
                    if kind == 'CREATE' and status == 'CONFLICT' and before is None:
                        connection.commit()
                        return WriteResult('CONFLICT')
                    if status == 'OPEN':
                        if after is not None and LogicalRecord(json.loads(after)) != record:
                            connection.rollback()
                            return WriteResult('REUSED')
                        if after is None:
                            # Bind the proposal durably before any persona lock
                            # or mutation. An interrupted attempt cannot later
                            # substitute different data under the same id.
                            cursor.execute('UPDATE persona_operations SET after_words=%s '
                                           'WHERE namespace=%s AND operation_id=%s', (packed(record), namespace, op))
                            connection.commit()
                            cursor.execute('SELECT name_key,status,generation,revision,'
                                           'LEFT(CAST(before_words AS BINARY),%s),LEFT(CAST(after_words AS BINARY),%s) '
                                           'FROM persona_operations WHERE namespace=%s AND operation_id=%s FOR UPDATE',
                                           (MAX_RECORD_JSON_BYTES + 1, MAX_RECORD_JSON_BYTES + 1, namespace, op))
                            old_name, status, generation, revision, before, after = cursor.fetchone()
                            if old_name != name or LogicalRecord(json.loads(after)) != record:
                                connection.rollback()
                                return WriteResult('REUSED')
                    if status not in ('INIT', 'OPEN'):
                        if status in ('COMMITTED', 'CONFLICT') and after is None:
                            raise InvalidRecord()
                        if after is not None and LogicalRecord(json.loads(after)) != record:
                            connection.rollback()
                            return WriteResult('REUSED')
                        connection.commit()
                        return WriteResult(status)
                columns = projection + ',generation,revision'
                if action == 'begin_next':
                    cursor.execute('SELECT name_key,' + columns + ' FROM personas '
                                   'WHERE namespace=%s AND (%s IS NULL OR name_key>%s) ORDER BY name_key LIMIT 1 FOR UPDATE',
                                   (*projection_params, namespace, cursor_key, cursor_key))
                    item = cursor.fetchone()
                    row = item[1:] if item else None
                    if item:
                        name = item[0]
                        if not isinstance(name, bytes) or len(name) != 9: raise InvalidRecord()
                        number = int.from_bytes(name, 'big')
                        try:
                            key = validate_name_key((number >> 36, number & WORD_MASK))
                        except ValueError:
                            raise InvalidRecord() from None
                else:
                    cursor.execute('SELECT ' + columns + ' FROM personas '
                                   'WHERE namespace=%s AND name_key=%s LIMIT 2 FOR UPDATE',
                                    (*projection_params, namespace, name))
                    row = cursor.fetchone()
                    if cursor.fetchone() is not None: raise InvalidRecord()
                current = decode_row(key, row[:-2]) if row else None
                if row and (not isinstance(row[-2], bytes) or len(row[-2]) != 9 or not any(row[-2])
                            or type(row[-1]) is not int or not 0 < row[-1] < MAX_REVISION):
                    raise InvalidRecord()
                if starting:
                    if kind == 'CREATE':
                        if current is not None:
                            status, snapshot, generation, revision = 'CONFLICT', None, None, None
                        else:
                            status = 'OPEN'
                            snapshot = LogicalRecord((0, *key, 0, 0, 0, 0, 0, 0, 0, 0))
                            generation = bytes(GENERATION_BYTES)
                            while not any(generation):
                                generation = secrets.token_bytes(GENERATION_BYTES)
                            revision = INITIAL_REVISION
                        cursor.execute('UPDATE persona_operations SET status=%s,generation=%s,revision=%s,before_words=%s '
                                       'WHERE namespace=%s AND operation_id=%s',
                                       (status, generation, revision, packed(snapshot) if snapshot else None, namespace, op))
                        connection.commit()
                        return WriteResult(status, snapshot)
                    status = 'OPEN' if current is not None else 'NOT_FOUND'
                    cursor.execute('UPDATE persona_operations SET status=%s,generation=%s,revision=%s,before_words=%s,name_key=%s '
                                   'WHERE namespace=%s AND operation_id=%s',
                                    (status, row[-2] if row else None, row[-1] if row else None,
                                     packed(current) if current else None, name, namespace, op))
                    connection.commit()
                    return WriteResult(status, current)
                if action in ('delete', 'purge'):
                    # Native death deletion has no save-score/revision guard.
                    # A newer save of this generation is still the same persona;
                    # a recreated generation must never be removed by this id.
                    if current is None:
                        status = 'NOT_FOUND'
                    elif row[-2] != generation:
                        status = 'CONFLICT'
                    elif action == 'purge' and (row[-1] != revision or current != LogicalRecord(json.loads(before))):
                        status = 'CONFLICT'
                    else:
                        cursor.execute('DELETE FROM personas WHERE namespace=%s AND name_key=%s',
                                       (namespace, name))
                        status = 'COMMITTED'
                    cursor.execute('UPDATE persona_operations SET status=%s WHERE namespace=%s AND operation_id=%s',
                                   (status, namespace, op))
                    connection.commit()
                    return WriteResult(status)
                if not committing or status != 'OPEN':
                    connection.rollback()
                    return WriteResult('ABORTED')
                expected = LogicalRecord(json.loads(before))
                if kind == 'CREATE':
                    if current is not None:
                        status = 'CONFLICT'
                    else:
                        insert_persona(cursor, namespace, key, record, generation, INITIAL_REVISION)
                        status = 'COMMITTED'
                elif (current is None or row[-2] != generation or row[-1] != revision or current != expected):
                    status = 'CONFLICT'
                else:
                    update_persona(cursor, namespace, name, record, readable)
                    status = 'COMMITTED'
                cursor.execute('UPDATE persona_operations SET status=%s,after_words=%s '
                               'WHERE namespace=%s AND operation_id=%s', (status, packed(record), namespace, op))
                connection.commit()  # Persona change and outcome are one durable transaction.
                return WriteResult(status)
        except InvalidRecord:
            if connection is not None:
                connection.rollback()
            return WriteResult('INVALID_RECORD')
        except Exception:
            if connection is not None:
                try:
                    connection.rollback()
                except Exception:
                    pass
            return WriteResult('UNKNOWN' if action in UNCERTAIN_ACTIONS else 'UNAVAILABLE')
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass

    def begin(self, operation, key):
        return self._transaction('begin', operation, key)

    def begin_purge(self, operation, key):
        return self._transaction('begin_purge', operation, key)

    def begin_next(self, operation, after=None):
        return self._transaction('begin_next', operation, after)

    def purge(self, operation, key):
        return self._transaction('purge', operation, key)

    def begin_delete(self, operation, key):
        return self._transaction('begin_delete', operation, key)

    def begin_create(self, operation, key):
        return self._transaction('begin_create', operation, key)

    def create(self, operation, key, record):
        return self._transaction('create', operation, key, record)

    def delete(self, operation, key):
        return self._transaction('delete', operation, key)

    def commit(self, operation, key, record):
        return self._transaction('commit', operation, key, record)

    def resolve(self, operation):
        return self._transaction('resolve', operation)
