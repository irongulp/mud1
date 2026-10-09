"""Creation requires opt-in, a credited template and a complete confirmed upload."""
import unittest
from unittest.mock import patch

from tools.persona_protocol import GetRequest, LogicalRecord, pack_name
from tools.persona_session import hello, accept, ack
from tools.persona_write_session import WriteSession, begin_create, key_frame, put, commit, delete
from tools.persona_writes import WriteResult, IsolatedWriteStore
from tools.persona_errors import StoreUnavailable


class Store:
    def __init__(self):
        self.record = LogicalRecord((0, *pack_name('newborn'), 0, 0, 0, 0, 0, 0, 0, 0))
        self.created = []

    def get(self, key): return None
    def begin_create(self, operation, key): return WriteResult('OPEN', self.record)
    def create(self, *args):
        self.created.append(args)
        return WriteResult('COMMITTED')


class CreateSessionTests(unittest.TestCase):
    def prepare(self, enabled=True):
        store = Store()
        session = WriteSession(store, allow_create=enabled, epoch_factory=lambda: 5)
        session.receive(hello(1)); session.receive(accept(1, 5))
        return store, session, GetRequest(5, 1, pack_name('newborn'))

    def snapshot(self, session, request):
        session.receive(begin_create(5, 99))
        session.receive(key_frame(5, request.name_words))
        for index in range(13): session.receive(ack(request, index))

    def test_creation_disabled_by_default(self):
        store, session, _ = self.prepare(False)
        with self.assertRaises(ValueError): session.receive(begin_create(5, 99))
        self.assertFalse(store.created)

    def test_confirmed_upload_creates_not_updates(self):
        store, session, request = self.prepare()
        self.snapshot(session, request)
        for index, word in enumerate(store.record.words, 1):
            session.receive(put(5, index, word))
        self.assertFalse(store.created)
        self.assertIn(b' COMMITTED\r', session.receive(commit(5, store.record)))
        self.assertEqual(store.created, [(99, request.name_words, store.record)])

    def test_partial_bad_checksum_and_delete_cannot_create(self):
        for fault in ('partial', 'checksum', 'delete'):
            store, session, request = self.prepare()
            self.snapshot(session, request)
            if fault != 'partial':
                for index, word in enumerate(store.record.words, 1): session.receive(put(5, index, word))
            frame = delete(5) if fault == 'delete' else commit(5, store.record)
            if fault == 'checksum': frame = frame[:-2] + (b'1' if frame[-2:-1] != b'1' else b'2') + b'\r'
            with self.assertRaises(ValueError): session.receive(frame)
            self.assertFalse(store.created)

    def test_new_owner_retires_creation_upload(self):
        store, session, request = self.prepare()
        self.snapshot(session, request)
        for index, word in enumerate(store.record.words, 1): session.receive(put(5, index, word))
        session.epoch_factory = lambda: 6
        session.receive(hello(2)); session.receive(accept(2, 6))
        with self.assertRaises(ValueError): session.receive(commit(5, store.record))
        self.assertFalse(store.created)

    def test_expired_session_cannot_publish_creation(self):
        store, session, request = self.prepare()
        self.snapshot(session, request)
        for index, word in enumerate(store.record.words, 1): session.receive(put(5, index, word))
        deadline = session.deadline
        session.clock = lambda: deadline + 1
        with self.assertRaises(TimeoutError): session.receive(commit(5, store.record))
        self.assertFalse(store.created)

    def test_late_create_acknowledgement_is_unknown(self):
        store, session, request = self.prepare()
        self.snapshot(session, request)
        for index, word in enumerate(store.record.words, 1): session.receive(put(5, index, word))
        clock = [session.deadline - 1]
        session.clock = lambda: clock[0]
        original = store.create
        def late(*args):
            result = original(*args)
            clock[0] += 2
            return result
        store.create = late
        self.assertIn(b' UNKNOWN\r', session.receive(commit(5, store.record)))
        self.assertEqual(len(store.created), 1)

    def test_inconclusive_create_worker_is_unknown(self):
        store = IsolatedWriteStore(('unused',), {})
        try:
            with patch.object(store, 'call', side_effect=StoreUnavailable()):
                key = pack_name('newborn')
                self.assertEqual(store.begin_create(99, key).status, 'UNAVAILABLE')
                self.assertEqual(store.create(99, key, Store().record).status, 'UNKNOWN')
        finally:
            store.close()
