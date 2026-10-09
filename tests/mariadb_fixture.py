"""Own a disposable local MariaDB process; never use an installed service/datadir."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import subprocess
import time

import pymysql

from tools.persona_mariadb import MariaDbConfig, encode_key
from tools.persona_protocol import pack_name
from tools.persona_columns import table_ddl, ColumnPersona, DATA_SQL, COLUMN_FORMAT
from tools.persona_timestamps import table_ddl as timestamp_ddl,TIMESTAMP_SQL,TIMESTAMP_FORMAT,timestamp_values

ROOT = Path(__file__).resolve().parents[1]
DATABASE = 'mud86_read'
READER = 'persona_reader'
START_TIMEOUT = 30
STOP_TIMEOUT = 15


class LocalMariaDb:
    def __init__(self, directory, *, column_schema=False):
        self.column_schema = column_schema
        self.directory = directory.resolve()
        self.socket = self.directory / 'db.sock'
        if len(str(self.socket).encode()) >= 100:
            raise ValueError('Use a shorter output path for the private Unix socket')
        self.password = secrets.token_urlsafe(24)
        self.process = None
        self.log = None
        self.paused = False

    def __enter__(self):
        server, initialize = shutil.which('mariadbd'), shutil.which('mariadb-install-db')
        if not server or not initialize:
            raise RuntimeError('Install MariaDB tools to run this optional integration test')
        self.server = str(Path(server).resolve())
        basedir = str(Path(self.server).parent.parent)
        self.directory.mkdir(mode=0o700)
        (self.directory / 'tmp').mkdir(mode=0o700)
        try:
            with (self.directory / 'initialize.log').open('wb') as log:
                subprocess.run([initialize, '--no-defaults', '--basedir=' + basedir,
                                 '--datadir=' + str(self.directory / 'data'),
                                 '--tmpdir=' + str(self.directory / 'tmp'),
                                '--auth-root-authentication-method=normal', '--skip-test-db'],
                               stdout=log, stderr=subprocess.STDOUT, check=True, timeout=90)
            self.start()
            with self.admin() as connection, connection.cursor() as cursor:
                cursor.execute('CREATE DATABASE ' + DATABASE + ' CHARACTER SET ascii COLLATE ascii_bin')
                cursor.execute('USE ' + DATABASE)
                cursor.execute((table_ddl() if self.column_schema==COLUMN_FORMAT else timestamp_ddl())
                               if self.column_schema else (ROOT / 'tools/fixtures/personas.sql').read_text())
                cursor.execute('CREATE USER %s@localhost IDENTIFIED BY %s', (READER, self.password))
                cursor.execute('GRANT SELECT ON ' + DATABASE + '.personas TO %s@localhost', (READER,))
                cursor.execute('SELECT VERSION()')
                self.version = cursor.fetchone()[0]
                cursor.execute("SHOW VARIABLES LIKE 'skip_networking'")
                if cursor.fetchone()[1] != 'ON':
                    raise AssertionError('Disposable MariaDB unexpectedly enabled TCP')
            return self
        except BaseException:
            self.stop()
            raise

    def start(self):
        (self.directory / 'tmp').mkdir(mode=0o700, exist_ok=True)
        self.log = (self.directory / 'process.log').open('ab')
        self.process = subprocess.Popen([
            self.server, '--no-defaults', '--datadir=' + str(self.directory / 'data'),
            '--socket=' + str(self.socket), '--pid-file=' + str(self.directory / 'db.pid'),
            '--tmpdir=' + str(self.directory / 'tmp'),
            '--skip-networking', '--skip-log-bin', '--general-log=0', '--slow-query-log=0',
            '--innodb-buffer-pool-size=32M', '--innodb-log-file-size=8M', '--max-connections=16',
            '--performance-schema=OFF', '--default-time-zone=+00:00',
            '--log-error=' + str(self.directory / 'server.log'),
        ], stdout=self.log, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + START_TIMEOUT
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError('Disposable MariaDB exited; inspect server.log')
            try:
                with self.admin():
                    return
            except pymysql.Error:
                time.sleep(0.05)
        raise TimeoutError('Disposable MariaDB did not become ready')

    def stop(self):
        if self.process is not None:
            if self.paused:
                self.resume()
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=STOP_TIMEOUT)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=STOP_TIMEOUT)
            self.process = None
        if self.log is not None:
            self.log.close()
            self.log = None

    def __exit__(self, *exc):
        self.stop()

    def pause(self):
        os.kill(self.process.pid, signal.SIGSTOP)
        self.paused = True

    def resume(self):
        os.kill(self.process.pid, signal.SIGCONT)
        self.paused = False

    def admin(self):
        # Empty bootstrap root password is confined to this 0700 directory and
        # private Unix socket, with no TCP listener. No installed service is used.
        return pymysql.connect(unix_socket=str(self.socket), user='root', password='',
                               autocommit=True, charset='utf8mb4', binary_prefix=True,
                               connect_timeout=1, read_timeout=2, write_timeout=2)

    def reader_config(self, namespace='mud'):
        return MariaDbConfig(database=DATABASE, user=READER, password=self.password,
                             unix_socket=str(self.socket), namespace=namespace)

    def seed(self, name, words, *, namespace='mud', version=1):
        with self.admin() as connection, connection.cursor() as cursor:
            if self.column_schema:
                from tools.persona_protocol import LogicalRecord
                if self.column_schema==COLUMN_FORMAT:
                    version,sql,data=COLUMN_FORMAT,DATA_SQL,ColumnPersona.from_record(LogicalRecord(words)).values()
                else:
                    cursor.execute('SELECT UTC_TIMESTAMP()')
                    version,sql,data=TIMESTAMP_FORMAT,TIMESTAMP_SQL,timestamp_values(LogicalRecord(words),cursor.fetchone()[0])
                values = (namespace.encode('ascii'),encode_key(pack_name(name)),version,*data)
                cursor.execute('INSERT INTO ' + DATABASE + '.personas(namespace,name_key,format_version,' + sql + ') '
                               'VALUES (' + ','.join(['%s']*len(values)) + ')', values)
                return
            cursor.execute('INSERT INTO ' + DATABASE + '.personas '
                           '(namespace,name_key,format_version,words) VALUES (%s,%s,%s,%s)',
                           (namespace.encode('ascii'), encode_key(pack_name(name)), version,
                            json.dumps(words, separators=(',', ':'))))

    def digest(self):
        with self.admin() as connection, connection.cursor() as cursor:
            if self.column_schema:
                sql=DATA_SQL if self.column_schema==COLUMN_FORMAT else TIMESTAMP_SQL
                cursor.execute('SELECT HEX(namespace),HEX(name_key),format_version,' + sql
                               + ',revision,updated_at FROM ' + DATABASE + '.personas ORDER BY namespace,name_key')
                data = json.dumps(cursor.fetchall(), default=str, separators=(',', ':')).encode()
                return hashlib.sha256(data).hexdigest()
            cursor.execute('SELECT HEX(namespace),HEX(name_key),format_version,words,revision,updated_at '
                           'FROM ' + DATABASE + '.personas ORDER BY namespace,name_key')
            data = json.dumps(cursor.fetchall(), default=str, separators=(',', ':')).encode()
        return hashlib.sha256(data).hexdigest()

    def grant_reads(self, enabled):
        with self.admin() as connection, connection.cursor() as cursor:
            cursor.execute(('GRANT SELECT ON ' + DATABASE + '.personas TO %s@localhost') if enabled else
                           ('REVOKE SELECT ON ' + DATABASE + '.personas FROM %s@localhost'), (READER,))
