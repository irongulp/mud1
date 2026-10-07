"""Real MariaDB transaction/idempotency acceptance, on a private test server."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import secrets
import threading
import time

from tools.persona_mariadb import MariaDbConfig, encode_key
from tools.persona_protocol import LogicalRecord, pack_name
from tools.persona_writes import isolated_writer
from tools.persona_columns import DATA_SQL
from tools.persona_timestamps import TIMESTAMP_FORMAT,TIMESTAMP_SQL
from tools.persona_mariadb import payload_projection
from tests.mariadb_fixture import LocalMariaDb, DATABASE
from tests.integration_persona_read import ROOT, fixture
from tests.integration_provisioning import require

WRITER = 'persona_writer'


def enable_writes(database, *, allow_delete=False, allow_create=False):
    password = secrets.token_urlsafe(24)
    with database.admin() as connection, connection.cursor() as cursor:
        cursor.execute('USE ' + DATABASE)
        _, _, readable = payload_projection(cursor)
        for statement in (ROOT / 'tools/fixtures/persona_writes.sql').read_text().split(';'):
            if statement.strip():
                if readable and 'ALTER TABLE personas ADD generation' in statement: continue
                cursor.execute(statement)
        cursor.execute('SELECT namespace,name_key FROM personas')
        for namespace, name in cursor.fetchall():
            cursor.execute('UPDATE personas SET generation=%s WHERE namespace=%s AND name_key=%s',
                           (secrets.token_bytes(9), namespace, name))
        cursor.execute('CREATE USER %s@localhost IDENTIFIED BY %s', (WRITER, password))
        columns = (TIMESTAMP_SQL if readable==TIMESTAMP_FORMAT else DATA_SQL)+',revision' if readable else 'words,revision'
        cursor.execute('GRANT SELECT, UPDATE(' + columns + ') ON ' + DATABASE + '.personas TO %s@localhost', (WRITER,))
        if allow_delete:
            cursor.execute('GRANT DELETE ON ' + DATABASE + '.personas TO %s@localhost', (WRITER,))
        if allow_create:
            cursor.execute('GRANT INSERT ON ' + DATABASE + '.personas TO %s@localhost', (WRITER,))
        cursor.execute('GRANT SELECT,INSERT,UPDATE ON ' + DATABASE + '.persona_operations TO %s@localhost', (WRITER,))
    return MariaDbConfig(database=DATABASE, user=WRITER, password=password, unix_socket=str(database.socket))


def revision(database, key):
    with database.admin() as connection, connection.cursor() as cursor:
        cursor.execute('SELECT revision FROM ' + DATABASE + '.personas WHERE namespace=%s AND name_key=%s',
                       (b'mud', encode_key(key)))
        return cursor.fetchone()[0]


def changed(record, score):
    words = list(record.words)
    words[3] = score
    return LogicalRecord(words)


def verify(database, store):
    key = pack_name('fred')
    first = store.begin(101, key)
    require(first.status == 'OPEN', 'Cannot start write snapshot: ' + first.status)
    one = changed(first.record, 11)
    require(store.commit(101, key, one).status == 'COMMITTED', 'First commit failed')
    require(store.commit(101, key, one).status == 'COMMITTED' and revision(database, key) == 2, 'Duplicate commit wrote twice')
    two = changed(store.begin(102, key).record, 22)
    require(store.commit(102, key, two).status == 'COMMITTED', 'Second save failed')
    require(store.commit(101, key, one).status == 'COMMITTED', 'Durable original result was lost')
    require(store.get(key) == two and revision(database, key) == 3, 'Old retry overwrote newer state')
    require(store.commit(101, key, two).status == 'REUSED', 'Operation accepted a changed intent')
    before = store.begin(103, key).record
    store.begin(104, key)
    require(store.commit(103, key, changed(before, 33)).status == 'COMMITTED', 'CAS winner failed')
    require(store.commit(104, key, changed(before, 44)).status == 'CONFLICT', 'Stale write was not rejected')
    require(store.get(key).words[3] == 33, 'Conflict modified persona')
    require(store.begin(105, pack_name('absent')).status == 'NOT_FOUND', 'Missing persona was created')
    require(store.get(pack_name('absent')) is None, 'BEGIN created a persona')
    store.begin(106, key)
    require(store.resolve(106).status == 'ABORTED', 'Open operation did not fence')
    require(store.commit(106, key, one).status == 'ABORTED', 'Fenced operation committed')
    require(store.resolve(107).status == 'ABORTED', 'Absent operation did not create a fence')
    require(store.begin(107, key).status == 'ABORTED', 'Late BEGIN bypassed tombstone')
    current = store.begin(108, key).record
    with database.admin() as connection, connection.cursor() as cursor:
        cursor.execute('UPDATE ' + DATABASE + '.personas SET generation=%s WHERE namespace=%s AND name_key=%s',
                       (secrets.token_bytes(9), b'mud', encode_key(key)))
    require(store.commit(108, key, changed(current, 99)).status == 'CONFLICT', 'Recreated identity accepted stale write')
    current = store.begin(109, key).record
    proposal = changed(current, 55)
    old_revision = revision(database, key)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(store.commit, 109, key, proposal) for _ in range(2)]
        require([future.result().status for future in futures] == ['COMMITTED', 'COMMITTED'], 'Concurrent replay failed')
    require(revision(database, key) == old_revision + 1, 'Concurrent replay incremented twice')
    outcomes = []
    for operation in range(110, 116):
        before = store.begin(operation, key).record
        proposal = changed(before, before.words[3] + 1)
        barrier = threading.Barrier(2)
        def commit_call():
            barrier.wait(); return store.commit(operation, key, proposal).status
        def resolve_call():
            barrier.wait(); return store.resolve(operation).status
        with ThreadPoolExecutor(max_workers=2) as pool:
            a, b = pool.submit(commit_call), pool.submit(resolve_call)
            commit_status, resolved = a.result(), b.result()
        require(resolved in ('COMMITTED', 'ABORTED'), 'Resolution race was inconclusive: ' + resolved)
        require(commit_status == resolved, 'Commit bypassed resolution fence')
        require(store.get(key) == (proposal if resolved == 'COMMITTED' else before), 'Resolution outcome disagrees with persona')
        outcomes.append(resolved)
    store.begin(116, key)
    database.stop()
    require(store.commit(116, key, one).status == 'UNKNOWN', 'Outage claimed a definite commit outcome')
    require(store.resolve(116).status == 'UNKNOWN', 'Outage falsely resolved operation')
    database.start()
    require(store.resolve(116).status == 'ABORTED', 'Recovery did not fence pending write')
    require(store.resolve(101).status == 'COMMITTED', 'Committed result did not survive restart')
    # A failed first commit must still bind its proposal. Otherwise reusing its
    # id with different data after an ambiguous error could change the intent.
    frozen = store.begin(200, key).record
    proposal = changed(frozen, 200)
    with database.admin() as connection, connection.cursor() as cursor:
        cursor.execute('LOCK TABLES ' + DATABASE + '.personas WRITE')
        try:
            require(store.commit(200, key, proposal).status == 'UNKNOWN', 'Blocked commit was not ambiguous')
        finally:
            cursor.execute('UNLOCK TABLES')
    require(store.commit(200, key, changed(frozen, 201)).status == 'REUSED', 'Failed commit did not retain immutable intent')
    require(store.resolve(200).status == 'ABORTED', 'Prepared intent could not be fenced')
    require(store.commit(200, key, proposal).status == 'ABORTED', 'Prepared intent committed after fencing')
    require(not store.worker_pids, 'Write workers leaked')
    return {'exactly_once': True, 'stale_conflict': True, 'generation_fence': True,
            'missing_not_created': True, 'resolve_races': outcomes, 'restart': True}


def run(output):
    output.mkdir(mode=0o700)
    report = {'complete': False}
    try:
        with LocalMariaDb(output / 'database') as database:
            database.seed('fred', fixture(pack_name('fred')))
            config = enable_writes(database)
            with isolated_writer(config) as store:
                report.update(verify(database, store))
            report.update(complete=True, mariadb_version=database.version)
        print('Write transaction checks complete:', output, flush=True)
    finally:
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'runtime' / f'persona-writes-{time.time_ns()}')
    run(parser.parse_args().output.resolve())
