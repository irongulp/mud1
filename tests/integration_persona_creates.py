"""Atomic create-if-absent, replay and fencing on a private MariaDB instance."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import threading
import time

from tests.integration_persona_read import ROOT, fixture
from tests.integration_persona_writes import enable_writes, changed, revision
from tests.integration_persona_deletes import racing_call
from tests.integration_provisioning import require
from tests.mariadb_fixture import LocalMariaDb, DATABASE
from tools.persona_protocol import LogicalRecord, pack_name
from tools.persona_mariadb import encode_key
from tools.persona_writes import isolated_writer


def generation(database, key):
    with database.admin() as connection, connection.cursor() as cursor:
        cursor.execute('SELECT generation FROM ' + DATABASE + '.personas WHERE namespace=%s AND name_key=%s',
                       (b'mud', encode_key(key)))
        return cursor.fetchone()[0]


def verify(database, store):
    key = pack_name('newborn')
    record = LogicalRecord(fixture(key))
    snapshot = store.begin_create(401, key)
    require(snapshot.status == 'OPEN' and snapshot.record.words[8:] == (0, 0, 0), 'No clean creation template')
    require(store.get(key) is None, 'Creation begin published a persona')
    require(store.create(401, key, record).status == 'COMMITTED', 'Create failed')
    first_generation = generation(database, key)
    require(any(first_generation) and revision(database, key) == 1, 'Create metadata invalid')
    require(store.create(401, key, record).status == 'COMMITTED', 'Replay lost creation result')
    require(revision(database, key) == 1, 'Replay rewrote creation')
    require(store.create(401, key, changed(record, 22)).status == 'REUSED', 'Create intent changed')
    require(store.begin_create(402, key).status == 'CONFLICT', 'Duplicate name accepted')
    require(store.create(402, key, record).status == 'CONFLICT', 'Duplicate-name outcome not durable')
    require(store.get(key) == record, 'Duplicate creation changed stored record')
    require(store.begin_delete(403, key).status == 'OPEN', 'Delete snapshot failed')
    require(store.delete(403, key).status == 'COMMITTED', 'Delete failed')
    require(store.begin_create(404, key).status == 'OPEN', 'Recreation rejected')
    replacement = changed(record, 33)
    require(store.create(404, key, replacement).status == 'COMMITTED', 'Recreation failed')
    require(generation(database, key) != first_generation, 'Recreation reused generation')
    require(store.create(401, key, record).status == 'COMMITTED' and store.get(key) == replacement,
            'Old create replay overwrote replacement')
    require(store.delete(403, key).status == 'COMMITTED' and store.get(key) == replacement,
            'Old delete replay removed replacement')
    require(store.begin(404, key).status == 'REUSED' and store.delete(404, key).status == 'REUSED', 'Cross-kind reuse accepted')
    missing = pack_name('missing')
    require(store.resolve(405).status == 'ABORTED', 'Absent fence failed')
    require(store.begin_create(405, missing).status == 'ABORTED', 'Late begin bypassed fence')
    require(store.create(405, missing, LogicalRecord(fixture(missing))).status == 'ABORTED', 'Late create bypassed fence')
    race_key = pack_name('racing')
    one = LogicalRecord(fixture(race_key))
    two = changed(one, 42)
    require(store.begin_create(406, race_key).status == 'OPEN', 'Race begin one failed')
    require(store.begin_create(407, race_key).status == 'OPEN', 'Race begin two failed')
    barrier = threading.Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(racing_call, barrier, store.create, 406, race_key, one)
        b = pool.submit(racing_call, barrier, store.create, 407, race_key, two)
        outcomes = [a.result(), b.result()]
    # A storage deadlock can be inconclusive, but durable resolution must never
    # allow both proposals to win or overwrite the winning password/profile.
    for index, operation in enumerate((406, 407)):
        if outcomes[index] == 'UNKNOWN': outcomes[index] = store.resolve(operation).status
    require(outcomes.count('COMMITTED') == 1 and all(x in ('COMMITTED', 'CONFLICT', 'ABORTED') for x in outcomes),
            'Concurrent creation did not choose one durable winner')
    require(store.get(race_key) == (one if outcomes[0] == 'COMMITTED' else two), 'Concurrent creation overwrote winner')
    fence_key = pack_name('fencer')
    require(store.begin_create(408, fence_key).status == 'OPEN', 'Fence snapshot failed')
    barrier = threading.Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(racing_call, barrier, store.create, 408, fence_key, LogicalRecord(fixture(fence_key)))
        b = pool.submit(racing_call, barrier, store.resolve, 408)
        made, resolved = a.result(), b.result()
    require(made == resolved and resolved in ('COMMITTED', 'ABORTED'), 'Create/resolve fence disagreed')
    require((store.get(fence_key) is not None) == (resolved == 'COMMITTED'), 'Fenced create published')
    require(store.begin_create(409, missing).status == 'OPEN', 'Outage begin failed')
    database.stop()
    require(store.create(409, missing, LogicalRecord(fixture(missing))).status == 'UNKNOWN', 'Outage claimed definite result')
    database.start()
    require(store.resolve(409).status == 'ABORTED', 'Outage recovery did not fence')
    require(store.resolve(401).status == 'COMMITTED', 'Restart lost create result')
    require(store.get(missing) is None, 'Outage/fenced creation published')
    frozen = LogicalRecord(fixture(missing))
    require(store.begin_create(410, missing).status == 'OPEN', 'Blocked creation begin failed')
    with database.admin() as connection, connection.cursor() as cursor:
        cursor.execute('LOCK TABLES ' + DATABASE + '.personas WRITE')
        try:
            require(store.create(410, missing, frozen).status == 'UNKNOWN', 'Blocked creation was not ambiguous')
        finally:
            cursor.execute('UNLOCK TABLES')
    require(store.create(410, missing, changed(frozen, 444)).status == 'REUSED', 'Failed create lost its bound proposal')
    require(store.resolve(410).status == 'ABORTED', 'Failed creation could not be fenced')
    require(store.create(410, missing, frozen).status == 'ABORTED' and store.get(missing) is None,
            'Failed creation published after resolution')
    require(not store.worker_pids, 'Creation workers leaked')
    return {'replay': True, 'fresh_generation': True, 'immutable_intent': True, 'failed_intent_bound': True,
            'concurrent_creation': outcomes, 'create_resolve': resolved, 'restart': True}


def run(output):
    output.mkdir(mode=0o700)
    report = {'complete': False}
    try:
        with LocalMariaDb(output / 'database') as database:
            config = enable_writes(database, allow_delete=True, allow_create=True)
            with isolated_writer(config) as store: report.update(verify(database, store))
            report.update(complete=True, mariadb_version=database.version)
        print('Creation transaction checks complete:', output, flush=True)
    finally:
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'runtime' / f'persona-creates-{time.time_ns()}')
    run(parser.parse_args().output.resolve())
