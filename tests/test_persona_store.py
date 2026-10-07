"""Logical MariaDB records and a hard, process-isolated lookup boundary."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
import sys
import threading
import time
import unittest
from unittest.mock import MagicMock, Mock, patch

from tools.persona_errors import InvalidRecord, StoreUnavailable
from tools.persona_protocol import GetRequest, LogicalRecord, ResponseDecoder, lookup_response, pack_name, WORD_MASK
from tools.persona_store import IsolatedPersonaStore
from tools.persona_mariadb import MariaDbConfig, MariaDbPersonaStore, decode_row, encode_key


class RecordTests(unittest.TestCase):
    def setUp(self):
        self.key = pack_name('abcdefghi')
        self.words = (7, self.key[0] | 1, self.key[1] | 1, 1 << 35, WORD_MASK,
                      0, 511, WORD_MASK - 9, 0, 1 << 35, WORD_MASK)

    def row(self, words=None, version=1):
        raw = json.dumps(self.words if words is None else words).encode('ascii')
        return version, len(raw), raw

    def test_all_words_and_name_flags_round_trip(self):
        self.assertEqual(decode_row(self.key, self.row()), LogicalRecord(self.words))
        self.assertEqual(encode_key(self.key), ((self.key[0] << 36) | self.key[1]).to_bytes(9, 'big'))

    def test_only_missing_row_means_absence(self):
        self.assertIsNone(decode_row(self.key, None))
        for raw in (b'null', b'[]', b'{}', b'false', b'not JSON'):
            with self.subTest(raw=raw), self.assertRaises(InvalidRecord):
                decode_row(self.key, (1, len(raw), raw))

    def test_rejects_wrong_format_count_ranges_and_boolean_words(self):
        for row in (self.row(version=2), self.row(words=self.words[:-1]),
                    self.row(words=(True,) + self.words[1:]),
                    self.row(words=(1.0,) + self.words[1:]),
                    self.row(words=(-1,) + self.words[1:]),
                    self.row(words=(WORD_MASK + 1,) + self.words[1:])):
            with self.subTest(row=row), self.assertRaises(InvalidRecord):
                decode_row(self.key, row)

    def test_rejects_oversized_or_inconsistent_payload_and_wrong_name(self):
        for row in ((1, 1000000, None), (1, 2, b'[] '), (1, 0, None),
                    self.row(words=(7, *pack_name('other'), *self.words[3:]))):
            with self.subTest(row=row), self.assertRaises(InvalidRecord):
                decode_row(self.key, row)

    def test_database_config_and_failures_do_not_reveal_credentials(self):
        config = MariaDbConfig(database='fixture', user='reader', password='private-secret')
        self.assertNotIn('private-secret', repr(config))
        store = MariaDbPersonaStore(config, connect=Mock(side_effect=OSError('private-secret')))
        with self.assertRaises(StoreUnavailable) as caught:
            store.get(self.key)
        self.assertNotIn('private-secret', str(caught.exception))

    def test_schema_drift_with_duplicate_rows_is_not_silently_accepted(self):
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value.fetchall.return_value = [('words',)]
        connection.cursor.return_value.__enter__.return_value.fetchone.side_effect = [self.row(), self.row()]
        store = MariaDbPersonaStore(MariaDbConfig(database='fixture', user='reader', password='secret'),
                                   connect=Mock(return_value=connection))
        with self.assertRaises(InvalidRecord):
            store.get(self.key)
        connection.close.assert_called_once()

    def test_invalid_backend_record_is_not_an_outage_or_absence(self):
        request = GetRequest(1, 1, self.key)
        def broken(_):
            raise InvalidRecord()
        result = ResponseDecoder(request).feed(lookup_response(request, broken))
        self.assertEqual(result.status, 'INVALID_RECORD')


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.key = pack_name('fred')

    def store(self, script, **options):
        store = IsolatedPersonaStore((sys.executable, '-c', script), {}, **options)
        self.addCleanup(store.close)
        return store

    def wait_workers(self, store, count):
        deadline = time.monotonic() + 2
        while len(store.worker_pids) != count:
            if time.monotonic() >= deadline:
                self.fail('Worker startup did not reach expected concurrency')
            time.sleep(0.005)
        return store.worker_pids

    def assert_reaped(self, pids):
        for pid in pids:
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)

    def test_returns_validated_complete_record(self):
        script = ('import sys,json; r=json.load(sys.stdin); '
                  'w=[7,*r["name_words"],34359738368,68719476735,0,511,123,0,0,0]; '
                  'print(json.dumps({"status":"FOUND","words":w}))')
        store = self.store(script)
        record = store.get(self.key)
        self.assertEqual(record.name_words, self.key)
        self.assertEqual(record.words[3:5], (1 << 35, WORD_MASK))
        self.assertFalse(store.worker_pids)

    def test_missing_invalid_and_unavailable_results_remain_distinct(self):
        for status, error in (('NOT_FOUND', None), ('INVALID_RECORD', InvalidRecord),
                              ('UNAVAILABLE', StoreUnavailable)):
            store = self.store(f'import sys; sys.stdin.read(); print(\'{{"status":"{status}"}}\')')
            if error:
                with self.assertRaises(error):
                    store.get(self.key)
            else:
                self.assertIsNone(store.get(self.key))

    def test_hung_worker_is_killed_reaped_and_capacity_recovers(self):
        store = self.store('import sys,time; sys.stdin.read(); time.sleep(30)', timeout=0.3, capacity=1)
        with ThreadPoolExecutor(max_workers=1) as pool:
            started = time.monotonic()
            future = pool.submit(store.get, self.key)
            pids = self.wait_workers(store, 1)
            with self.assertRaises(StoreUnavailable):
                future.result(timeout=2)
            self.assertLess(time.monotonic() - started, 1.5)
        self.assert_reaped(pids)
        self.assertFalse(store.worker_pids)
        with self.assertRaises(StoreUnavailable):
            store.get(self.key)  # A real second timeout, not a leaked capacity slot.
        self.assertFalse(store.worker_pids)

    def test_complete_but_late_output_is_never_published(self):
        script = ('import sys,time; sys.stdin.read(); '
                  'print(\'{"status":"NOT_FOUND"}\',flush=True); time.sleep(30)')
        store = self.store(script, timeout=0.2)
        with self.assertRaises(StoreUnavailable):
            store.get(self.key)
        self.assertFalse(store.worker_pids)

    def test_oversized_output_is_bounded(self):
        store = self.store('import os,sys,time; sys.stdin.read(); os.write(1,b"X"*1000000); time.sleep(30)')
        started = time.monotonic()
        with self.assertRaises(StoreUnavailable):
            store.get(self.key)
        self.assertLess(time.monotonic() - started, 1)
        self.assertFalse(store.worker_pids)

    def test_crash_malformed_output_and_extra_fields_are_unavailable(self):
        for script in ('import sys; sys.exit(2)', 'print("not JSON")',
                       'print(\'{"status":"NOT_FOUND","words":[]}\')'):
            with self.subTest(script=script), self.assertRaises(StoreUnavailable):
                self.store(script).get(self.key)

    def test_capacity_is_fail_fast_and_bounds_process_count(self):
        store = self.store('import sys,time; sys.stdin.read(); time.sleep(.4); print(\'{"status":"NOT_FOUND"}\')',
                           capacity=2, timeout=2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(store.get, self.key) for _ in range(2)]
            pids = self.wait_workers(store, 2)
            started = time.monotonic()
            with self.assertRaises(StoreUnavailable):
                store.get(self.key)
            self.assertLess(time.monotonic() - started, 0.1)
            self.assertEqual(store.worker_pids, pids)
            self.assertEqual([future.result(timeout=2) for future in futures], [None, None])
        self.assert_reaped(pids)

    def test_close_cancels_active_lookup_and_disallows_new_work(self):
        store = self.store('import sys,time; sys.stdin.read(); time.sleep(30)', timeout=5)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(store.get, self.key)
            pids = self.wait_workers(store, 1)
            store.close()
            with self.assertRaises(StoreUnavailable):
                future.result(timeout=2)
        self.assert_reaped(pids)
        with self.assertRaises(StoreUnavailable):
            store.get(self.key)

    def test_close_between_worker_exit_and_publication_discards_result(self):
        store = self.store('import sys; sys.stdin.read(); print(\'{"status":"NOT_FOUND"}\')')
        original = store._exchange
        ready, release = threading.Event(), threading.Event()
        def delayed(*args):
            result = original(*args)
            ready.set()
            release.wait(1)
            return result
        with patch.object(store, '_exchange', side_effect=delayed), ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(store.get, self.key)
            self.assertTrue(ready.wait(1))
            store.close()
            release.set()
            with self.assertRaises(StoreUnavailable):
                future.result(timeout=2)

    def test_deadline_is_checked_again_before_publication(self):
        store = self.store('import sys; sys.stdin.read(); print(\'{"status":"NOT_FOUND"}\')', timeout=0.2)
        original = store._exchange
        def delayed(*args):
            result = original(*args)
            time.sleep(0.21)
            return result
        with patch.object(store, '_exchange', side_effect=delayed), self.assertRaises(StoreUnavailable):
            store.get(self.key)
