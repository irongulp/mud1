"""PURGE snapshots, traversal and conditional deletion on private MariaDB."""
import argparse
import json
from pathlib import Path
import secrets
import time
from tools.persona_protocol import pack_name
from tools.persona_mariadb import encode_key
from tools.persona_writes import isolated_writer
from tests.integration_persona_read import ROOT, fixture
from tests.integration_persona_writes import enable_writes, changed
from tests.integration_provisioning import require
from tests.mariadb_fixture import LocalMariaDb, DATABASE


def verify(database, store):
    keys = sorted(pack_name(name) for name in ('fred', 'alice', 'bob'))
    cursor = None
    for index, expected in enumerate(keys):
        answer = store.begin_next(500 + index, cursor)
        require(answer.status == 'OPEN' and answer.record.name_words == expected, 'Enumeration skipped/repeated a record')
        require(store.begin_next(500 + index, cursor) == answer, 'Enumeration replay changed its snapshot')
        require(store.begin_next(500 + index, expected).status == 'REUSED', 'Cursor intent changed')
        require(store.resolve(500 + index).status == 'ABORTED', 'Read-only view did not retire')
        cursor = expected
    require(store.begin_next(503, cursor).status == 'NOT_FOUND', 'Enumeration end not explicit')
    key = pack_name('fred')
    before = store.begin_purge(504, key).record
    store.begin(505, key)
    newer = changed(before, 123)
    require(store.commit(505, key, newer).status == 'COMMITTED', 'Concurrent update failed')
    require(store.purge(504, key).status == 'CONFLICT' and store.get(key) == newer, 'PURGE deleted changed record')
    store.begin_purge(506, key)
    with database.admin() as connection, connection.cursor() as sql:
        sql.execute('UPDATE ' + DATABASE + '.personas SET generation=%s WHERE namespace=%s AND name_key=%s',
                    (secrets.token_bytes(9), b'mud', encode_key(key)))
    require(store.purge(506, key).status == 'CONFLICT', 'PURGE removed replacement generation')
    require(store.begin_purge(507, key).status == 'OPEN', 'Fresh purge view failed')
    require(store.delete(507, key).status == 'REUSED', 'PURGE bypassed snapshot guard through death DELETE')
    require(store.purge(507, key).status == 'COMMITTED', 'Confirmed PURGE failed')
    require(store.get(key) is None and store.purge(507, key).status == 'COMMITTED', 'PURGE replay failed')
    require(store.begin_purge(508, key).status == 'NOT_FOUND', 'Missing PURGE not a no-op')
    require(store.resolve(509).status == 'ABORTED', 'Absent operation fence failed')
    require(store.begin_next(509, None).status == 'ABORTED', 'Enumeration bypassed absent fence')
    require(store.begin_next(509, keys[0]).status == 'ABORTED', 'Cursor bypassed absent fence')
    key = keys[0]
    require(store.begin_next(510, None).record.name_words == key, 'Delete-from-enumeration snapshot failed')
    require(store.purge(510, key).status == 'COMMITTED', 'Enumeration operation could not delete selected record')
    database.stop()
    require(store.purge(510, key).status == 'UNKNOWN', 'Offline PURGE claimed definite outcome')
    require(store.begin_next(511, None).status == 'UNAVAILABLE', 'Offline enumeration claimed end')
    database.start()
    require(store.resolve(510).status == 'COMMITTED', 'PURGE lost durable outcome across restart')
    survivor = pack_name('alice')
    require(store.begin_purge(512, survivor).status == 'OPEN', 'Password-only conflict snapshot failed')
    with database.admin() as connection, connection.cursor() as sql:
        words = list(store.get(survivor).words); words[7] ^= 1
        sql.execute('UPDATE ' + DATABASE + '.personas SET words=%s WHERE namespace=%s AND name_key=%s',
                    (json.dumps(words), b'mud', encode_key(survivor)))
    require(store.purge(512, survivor).status == 'CONFLICT', 'PURGE missed changed password without revision bump')
    with database.admin() as connection, connection.cursor() as sql:
        sql.execute('INSERT INTO ' + DATABASE + '.personas(namespace,name_key,format_version,words,generation) '
                    'VALUES (%s,%s,1,%s,%s)', (b'mud', bytes(9), json.dumps(fixture(survivor)), secrets.token_bytes(9)))
    require(store.begin_next(513, None).status == 'INVALID_RECORD', 'Malformed first key silently omitted')
    return {'traversal': True, 'record_guard': True, 'generation_guard': True, 'fencing': True, 'restart': True}


def run(output):
    output.mkdir(mode=0o700)
    report = {'complete': False}
    try:
        with LocalMariaDb(output / 'database') as database:
            for name in ('fred', 'alice', 'bob'): database.seed(name, fixture(pack_name(name)))
            config = enable_writes(database, allow_delete=True)
            with isolated_writer(config) as store: report.update(verify(database, store))
            report['complete'] = True
    finally:
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print('Administration storage checks complete:', output, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'runtime' / f'persona-admin-{time.time_ns()}')
    run(parser.parse_args().output.resolve())
