"""Generation-fenced deletion acceptance on a disposable MariaDB server."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import secrets
import threading
import time

from tests.integration_persona_read import ROOT, fixture
from tests.integration_persona_writes import enable_writes, changed
from tests.integration_provisioning import require
from tests.mariadb_fixture import LocalMariaDb, DATABASE
from tools.persona_mariadb import encode_key
from tools.persona_writes import isolated_writer
from tools.persona_protocol import LogicalRecord, pack_name


def racing_call(barrier, method, *args):
    barrier.wait()
    return method(*args).status


def verify(database, store):
    key = pack_name('fred')
    def recreate():
        with database.admin() as connection, connection.cursor() as cursor:
            cursor.execute('DELETE FROM ' + DATABASE + '.personas WHERE namespace=%s AND name_key=%s',
                           (b'mud', encode_key(key)))
        database.seed('fred', fixture(key))
        with database.admin() as connection, connection.cursor() as cursor:
            cursor.execute('UPDATE ' + DATABASE + '.personas SET generation=%s '
                           'WHERE namespace=%s AND name_key=%s',
                           (secrets.token_bytes(9), b'mud', encode_key(key)))

    require(store.begin_delete(301, key).status == 'OPEN', 'Delete snapshot unavailable')
    require(store.get(key) is not None, 'BEGIN deleted the persona')
    require(store.begin(301, key).status == 'REUSED', 'Delete id reused for update')
    require(store.commit(301, key, LogicalRecord(fixture(key))).status == 'REUSED', 'Delete id accepted update')
    require(store.delete(301, key).status == 'COMMITTED', 'Delete failed')
    require(store.get(key) is None, 'Delete left persona present')
    recreate()
    replacement = store.get(key)
    require(store.delete(301, key).status == 'COMMITTED', 'Replay lost terminal outcome')
    require(store.get(key) == replacement, 'Replay deleted replacement')
    require(store.begin_delete(302, key).status == 'OPEN', 'Second snapshot failed')
    recreate()
    require(store.delete(302, key).status == 'CONFLICT', 'Stale generation deleted replacement')
    require(store.get(key) is not None, 'Generation conflict mutated persona')
    snapshot = store.begin(303, key).record
    require(store.begin_delete(303, key).status == 'REUSED', 'Update id reused for delete')
    require(store.delete(303, key).status == 'REUSED', 'Update operation authorized deletion')
    require(store.begin_delete(304, key).status == 'OPEN', 'Concurrent delete snapshot failed')
    require(store.commit(303, key, changed(snapshot, 999)).status == 'COMMITTED', 'Concurrent update failed')
    require(store.delete(304, key).status == 'COMMITTED', 'Same-generation update blocked death deletion')
    absent = pack_name('absent')
    require(store.begin_delete(305, absent).status == 'NOT_FOUND', 'Missing deletion not a no-op')
    require(store.delete(305, absent).status == 'NOT_FOUND', 'Missing outcome not durable')
    recreate()
    require(store.resolve(306).status == 'ABORTED', 'Absent resolution failed')
    require(store.begin_delete(306, key).status == 'ABORTED', 'Late begin bypassed fence')
    require(store.delete(306, key).status == 'ABORTED', 'Late delete bypassed fence')
    require(store.delete(307, key).status == 'ABORTED', 'Unprepared delete succeeded')
    require(store.begin_delete(308, key).status == 'OPEN', 'Open snapshot failed')
    require(store.delete(308, absent).status == 'REUSED', 'Delete accepted different identity')
    require(store.resolve(308).status == 'ABORTED', 'Open deletion did not fence')
    require(store.delete(308, key).status == 'ABORTED', 'Resolved delete mutated persona')
    require(store.begin_delete(309, key).status == 'OPEN', 'Duplicate delete snapshot failed')
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = [pool.submit(store.delete, 309, key) for _ in range(2)]
        require([reply.result().status for reply in replies] == ['COMMITTED', 'COMMITTED'],
                'Concurrent duplicate delete lost outcome')
    recreate()
    require(store.delete(309, key).status == 'COMMITTED' and store.get(key) is not None,
            'Concurrent delete replay removed replacement')
    outcomes = []
    for operation in range(310, 316):
        recreate()
        require(store.begin_delete(operation, key).status == 'OPEN', 'Race snapshot failed')
        barrier = threading.Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            deletion = pool.submit(racing_call, barrier, store.delete, operation, key)
            resolution = pool.submit(racing_call, barrier, store.resolve, operation)
            a, b = deletion.result(), resolution.result()
        require(a == b and a in ('COMMITTED', 'ABORTED'), 'Delete/resolve race disagreed')
        require((store.get(key) is None) == (a == 'COMMITTED'), 'Race outcome disagrees with row')
        outcomes.append(a)
    update_races = []
    for operation in range(330, 336, 2):
        recreate()
        require(store.begin_delete(operation, key).status == 'OPEN', 'Delete/update snapshot failed')
        proposal = changed(store.begin(operation + 1, key).record, 888)
        barrier = threading.Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            deletion = pool.submit(racing_call, barrier, store.delete, operation, key)
            update = pool.submit(racing_call, barrier, store.commit, operation + 1, key, proposal)
            a, b = deletion.result(), update.result()
        require(a == 'COMMITTED' and b in ('COMMITTED', 'CONFLICT'), 'Delete/update race invalid')
        require(store.get(key) is None, 'Racing update resurrected deleted persona')
        update_races.append(b)
    recreate()
    require(store.begin_delete(320, key).status == 'OPEN', 'Outage snapshot failed')
    database.stop()
    require(store.delete(320, key).status == 'UNKNOWN', 'Outage claimed definite delete outcome')
    database.start()
    require(store.resolve(320).status == 'ABORTED', 'Restart failed to fence pending delete')
    require(store.resolve(301).status == 'COMMITTED', 'Restart lost committed outcome')
    require(store.delete(301, key).status == 'COMMITTED' and store.get(key) is not None,
            'Restart replay removed replacement')
    require(not store.worker_pids, 'Delete workers leaked')
    return {'generation_fence': True, 'replay': True, 'kind_binding': True,
            'missing_noop': True, 'resolve_races': outcomes, 'update_races': update_races,
            'concurrent_replay': True, 'restart': True}


def run(output):
    output.mkdir(mode=0o700)
    report = {'complete': False}
    try:
        with LocalMariaDb(output / 'database') as database:
            database.seed('fred', fixture(pack_name('fred')))
            config = enable_writes(database, allow_delete=True)
            with isolated_writer(config) as store:
                report.update(verify(database, store))
            report.update(complete=True, mariadb_version=database.version)
        print('Delete transaction checks complete:', output, flush=True)
    finally:
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'runtime' / f'persona-deletes-{time.time_ns()}')
    run(parser.parse_args().output.resolve())
