"""Read-only MariaDB adapter for lossless native logical persona words."""
from dataclasses import asdict, dataclass, field
import json
import sys

from tools.persona_errors import InvalidRecord, StoreUnavailable
from tools.persona_protocol import FORMAT_VERSION, LogicalRecord
from tools.persona_store import IsolatedPersonaStore, validate_key
from tools.persona_columns import ColumnPersona, DATA_COLUMNS, DATA_SQL, COLUMN_FORMAT,FLAG_COLUMNS
from tools.persona_timestamps import (TIMESTAMP_FORMAT,TIMESTAMP_COLUMNS,TIMESTAMP_SQL,STATE_TIMESTAMP_COLUMNS,
                                     timestamp_values,timestamp_record)

MAX_RECORD_JSON_BYTES = 512
MAX_LOOKUP_ROWS = 2  # Detect duplicate identities if an external schema has drifted.
CONNECT_TIMEOUT = 1
SOCKET_TIMEOUT = 1
STATEMENT_TIMEOUT = 0.5
LOCK_TIMEOUT = 1


@dataclass(frozen=True)
class MariaDbConfig:
    database: str
    user: str
    password: str = field(repr=False)
    namespace: str = 'mud'
    host: str = '127.0.0.1'
    port: int = 3306
    unix_socket: str = ''

    def __post_init__(self):
        limits = {'database': 64, 'user': 80, 'password': 1024, 'namespace': 64,
                  'host': 255, 'unix_socket': 1024}
        for name, limit in limits.items():
            value = getattr(self, name)
            if not isinstance(value, str) or len(value) > limit or '\x00' in value:
                raise ValueError('Invalid database configuration')
        if not self.database or not self.user or not self.namespace:
            raise ValueError('Missing database configuration')
        if type(self.port) is not int or not 0 < self.port < 65536:
            raise ValueError('Invalid database port')
        try:
            self.namespace.encode('ascii')
        except UnicodeEncodeError:
            raise ValueError('Namespace must be ASCII') from None


def encode_key(name_words):
    first, second = validate_key(name_words)
    return ((first << 36) | second).to_bytes(9, 'big')


def decode_row(name_words, row):
    if row is None:
        return None
    try:
        if row and row[0]==TIMESTAMP_FORMAT:
            if type(row[0]) is not int: raise InvalidRecord()
            record=timestamp_record(row[1:])
            if record.name_words!=validate_key(name_words): raise InvalidRecord()
            return record
        if len(row) == len(DATA_COLUMNS) + 1:
            if type(row[0]) is not int or row[0] != COLUMN_FORMAT: raise InvalidRecord()
            record = ColumnPersona.from_values(row[1:]).to_record()
            if record.name_words != validate_key(name_words): raise InvalidRecord()
            return record
        version, length, data = row
        if (type(version) is not int or version != FORMAT_VERSION
                or type(length) is not int or not 0 < length <= MAX_RECORD_JSON_BYTES
                or not isinstance(data, bytes) or len(data) != length):
            raise InvalidRecord()
        record = LogicalRecord(json.loads(data.decode('ascii')))
        if record.name_words != validate_key(name_words):
            raise InvalidRecord()
        return record
    except (TypeError, ValueError):
        raise InvalidRecord() from None


def payload_projection(cursor):
    """Detect the complete supported layout; never use a half-upgraded table."""
    cursor.execute("SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='personas'")
    columns = {row[0] for row in cursor.fetchall()}
    if ('words' not in columns and set(TIMESTAMP_COLUMNS)<=columns
            and not (set(FLAG_COLUMNS)|{'native_day','native_day_fraction'})&columns):
        return 'format_version,'+TIMESTAMP_SQL,(),TIMESTAMP_FORMAT
    if 'words' in columns and not set(DATA_COLUMNS) & columns:
        return ('format_version,OCTET_LENGTH(words),CASE WHEN OCTET_LENGTH(words)<=%s '
                'THEN CAST(words AS BINARY) ELSE NULL END', (MAX_RECORD_JSON_BYTES,), False)
    if ('words' not in columns and set(DATA_COLUMNS)<=columns and not set(STATE_TIMESTAMP_COLUMNS)&columns
            and 'last_saved_at' not in columns):
        return 'format_version,' + DATA_SQL, (), COLUMN_FORMAT
    raise InvalidRecord()


def insert_persona(cursor, namespace, key, record, generation, revision=1):
    _, _, readable = payload_projection(cursor)
    if readable==TIMESTAMP_FORMAT:
        cursor.execute('SELECT UTC_TIMESTAMP()'); observation=cursor.fetchone()[0]
        values=(namespace,encode_key(key),TIMESTAMP_FORMAT,*timestamp_values(record,observation),generation,revision)
        columns='namespace,name_key,format_version,'+TIMESTAMP_SQL+',generation,revision'
    elif readable:
        values = (namespace, encode_key(key), COLUMN_FORMAT, *ColumnPersona.from_record(record).values(), generation, revision)
        columns = 'namespace,name_key,format_version,' + DATA_SQL + ',generation,revision'
    else:
        values = (namespace, encode_key(key), FORMAT_VERSION, json.dumps(record.words, separators=(',', ':')), generation, revision)
        columns = 'namespace,name_key,format_version,words,generation,revision'
    cursor.execute('INSERT INTO personas(' + columns + ') VALUES (' + ','.join(['%s'] * len(values)) + ')', values)


def update_persona(cursor, namespace, name, record, readable):
    if readable==TIMESTAMP_FORMAT:
        cursor.execute('SELECT UTC_TIMESTAMP()'); observation=cursor.fetchone()[0]
        values=timestamp_values(record,observation)
        assignment=','.join('`'+column+'`=COALESCE(`'+column+'`,%s)' if column in STATE_TIMESTAMP_COLUMNS and value is not None
                            else '`'+column+'`=%s' for column,value in zip(TIMESTAMP_COLUMNS,values))
    elif readable:
        assignment = ','.join('`' + column + '`=%s' for column in DATA_COLUMNS)
        values = ColumnPersona.from_record(record).values()
    else:
        assignment, values = 'words=%s', (json.dumps(record.words, separators=(',', ':')),)
    cursor.execute('UPDATE personas SET ' + assignment + ',revision=revision+1 WHERE namespace=%s AND name_key=%s',
                   (*values, namespace, name))


class MariaDbPersonaStore:
    """Direct driver adapter. Production callers must use isolated_mariadb().

    Socket and statement timeouts are defense in depth, not a total deadline.
    Each call obtains one coherent row with a size-bounded projection. It never
    creates tables, mutates personas, imports data or retries a failed query.
    """
    def __init__(self, config, *, connect=None):
        self.config, self._connect = config, connect

    def get(self, name_words):
        key = encode_key(name_words)
        connection = None
        try:
            connect = self._connect
            if connect is None:
                import pymysql
                connect = pymysql.connect
            connection = connect(host=self.config.host, port=self.config.port,
                                 unix_socket=self.config.unix_socket or None,
                                 user=self.config.user, password=self.config.password,
                                 database=self.config.database, charset='ascii', binary_prefix=True, autocommit=True,
                                 connect_timeout=CONNECT_TIMEOUT, read_timeout=SOCKET_TIMEOUT,
                                 write_timeout=SOCKET_TIMEOUT, local_infile=False)
            with connection.cursor() as cursor:
                cursor.execute('SET SESSION TRANSACTION READ ONLY')
                cursor.execute("SET SESSION time_zone='+00:00'")
                cursor.execute('SET SESSION max_statement_time = %s', (STATEMENT_TIMEOUT,))
                cursor.execute('SET SESSION lock_wait_timeout = %s', (LOCK_TIMEOUT,))
                projection, params, _ = payload_projection(cursor)
                cursor.execute(
                    'SELECT ' + projection + ' '
                    f'FROM personas WHERE namespace = %s AND name_key = %s LIMIT {MAX_LOOKUP_ROWS}',
                    (*params, self.config.namespace.encode('ascii'), key))
                row = cursor.fetchone()
                if cursor.fetchone() is not None:
                    raise InvalidRecord()
            return decode_row(name_words, row)
        except InvalidRecord:
            raise
        except Exception:
            raise StoreUnavailable() from None
        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass  # The isolated caller still requires worker exit by its deadline.


def isolated_mariadb(config, **limits):
    return IsolatedPersonaStore((sys.executable, '-m', 'tools.persona_mariadb_worker'),
                                asdict(config), **limits)
