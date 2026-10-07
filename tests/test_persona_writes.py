"""Write framing/policy boundaries; real transaction tests live in integration."""
import unittest

from tools.persona_protocol import GetRequest, LogicalRecord, pack_name, encode_get, encode_result, ReadResult
from tools.persona_session import hello, accept, ack
from tools.persona_write_session import WriteSession, begin, key_frame, put, commit, resolve
from tools.persona_writes import WriteResult


class MemoryStore:
    def __init__(self):
        name = pack_name('fred')
        self.record = LogicalRecord((7, *name, 777, 0, 0, 0, 123, 8, 9, 10))
        self.commits = []
        self.resolutions = []

    def get(self, key):
        return self.record

    def begin(self, operation, key):
        return WriteResult('OPEN', self.record)

    def commit(self, operation, key, record):
        self.commits.append((operation, key, record))
        return WriteResult('COMMITTED')

    def resolve(self, operation):
        self.resolutions.append(operation)
        return WriteResult('ABORTED')


class WriteSessionTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.session = WriteSession(self.store, epoch_factory=lambda: 5)
        self.session.receive(hello(1))
        self.session.receive(accept(1, 5))
        self.request = GetRequest(5, 1, pack_name('fred'))
        self.operation = 99

    def prepare(self):
        self.assertEqual(self.session.receive(begin(5, self.operation)), b'W1 ACK 000000000000000000000005 00\r')
        header = self.session.receive(key_frame(5, self.request.name_words))
        self.assertIn(b'R1 FOUND ', header)
        for index in range(12):
            self.session.receive(ack(self.request, index))
        self.assertIsNone(self.session.receive(ack(self.request, 12)))

    def test_no_commit_until_all_words_and_explicit_commit(self):
        self.prepare()
        for index, word in enumerate(self.store.record.words, 1):
            response = self.session.receive(put(5, index, word))
            self.assertEqual(response.count(b'\r'), 1)
            self.assertFalse(self.store.commits)
        result = self.session.receive(commit(5, self.store.record))
        self.assertIn(b' COMMITTED\r', result)
        self.assertEqual(self.store.commits, [(99, self.request.name_words, self.store.record)])

    def test_partial_wrong_epoch_and_duplicate_upload_never_commit(self):
        self.prepare()
        self.session.receive(put(5, 1, 7))
        with self.assertRaises(ValueError):
            self.session.receive(put(5, 1, 7))
        self.assertFalse(self.store.commits)

    def test_early_commit_is_rejected(self):
        self.prepare()
        with self.assertRaises(ValueError):
            self.session.receive(commit(5, self.store.record))
        self.assertFalse(self.store.commits)

    def test_commit_requires_end_to_end_upload_checksum(self):
        self.prepare()
        for index, word in enumerate(self.store.record.words, 1):
            self.session.receive(put(5, index, word))
        with self.assertRaises(ValueError):
            self.session.receive(b'W1 COMMIT 000000000000000000000005\r')
        self.assertFalse(self.store.commits)

    def test_changed_data_with_original_checksum_never_commits(self):
        self.prepare()
        for index, word in enumerate(self.store.record.words, 1):
            self.session.receive(put(5, index, word ^ (1 if index == 4 else 0)))
        with self.assertRaises(ValueError):
            self.session.receive(commit(5, self.store.record))
        self.assertFalse(self.store.commits)

    def test_new_owner_discards_uncommitted_upload(self):
        self.prepare()
        self.session.receive(put(5, 1, 7))
        self.session.epoch_factory = lambda: 6
        self.session.receive(hello(2))
        self.session.receive(accept(2, 6))
        with self.assertRaises(ValueError):
            self.session.receive(commit(5, self.store.record))
        self.assertFalse(self.store.commits)

    def test_resolution_uses_durable_operation_not_current_epoch(self):
        result = self.session.receive(resolve(5, self.operation))
        self.assertIn(b' ABORTED\r', result)
        self.assertEqual(self.store.resolutions, [99])

    def test_read_protocol_remains_available(self):
        result = self.session.receive(encode_get(self.request))
        self.assertEqual(result, encode_result(self.request, ReadResult('FOUND', self.store.record)).splitlines(keepends=True)[0])

    def test_every_write_frame_fits_native_line_limit(self):
        for frame in (begin(5, 99), key_frame(5, self.request.name_words), put(5, 11, (1 << 36)-1), commit(5, self.store.record), resolve(5, 99)):
            self.assertLessEqual(len(frame), 80)
            self.assertTrue(frame.endswith(b'\r'))
            self.assertNotIn(b'\n', frame)
