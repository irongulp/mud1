"""Delete framing must be explicit, optional and tied to a snapshot operation."""
import unittest
from unittest.mock import patch

from tools.persona_protocol import GetRequest, LogicalRecord, pack_name
from tools.persona_session import hello, accept, ack
from tools.persona_write_session import WriteSession, begin_delete, delete, key_frame, put, commit
from tools.persona_writes import WriteResult, IsolatedWriteStore
from tools.persona_errors import StoreUnavailable


class Store:
    def __init__(self):
        self.record = LogicalRecord((1, *pack_name('mortal'), 0, 0, 0, 0, 123, 0, 0, 0))
        self.deleted = []
        self.updated = []
    def get(self, key): return self.record
    def begin_delete(self, operation, key): return WriteResult('OPEN', self.record)
    def delete(self, operation, key):
        self.deleted.append((operation, key))
        return WriteResult('COMMITTED')
    def commit(self, *args):
        self.updated.append(args)
        return WriteResult('COMMITTED')


class DeleteSessionTests(unittest.TestCase):
    def session(self, allow=True):
        store = Store()
        session = WriteSession(store, allow_delete=allow, epoch_factory=lambda: 5)
        session.receive(hello(1)); session.receive(accept(1, 5))
        return session, store, GetRequest(5, 1, pack_name('mortal'))

    def prepare(self, session, request):
        session.receive(begin_delete(5, 99))
        self.assertIn(b'R1 FOUND ', session.receive(key_frame(5, request.name_words)))
        for index in range(13):
            session.receive(ack(request, index))

    def test_opt_in_required(self):
        session, store, request = self.session(False)
        with self.assertRaises(ValueError): session.receive(begin_delete(5, 99))
        self.assertFalse(store.deleted)

    def test_delete_needs_snapshot_and_explicit_confirmation(self):
        session, store, request = self.session()
        self.prepare(session, request)
        self.assertFalse(store.deleted)
        self.assertIn(b' COMMITTED\r', session.receive(delete(5)))
        self.assertEqual(store.deleted, [(99, request.name_words)])
        self.assertFalse(store.updated)

    def test_early_delete_and_wrong_epoch_are_rejected(self):
        for early in (True, False):
            session, store, request = self.session()
            session.receive(begin_delete(5, 99))
            if not early:
                session.receive(key_frame(5, request.name_words))
                for index in range(13): session.receive(ack(request, index))
            with self.assertRaises(ValueError): session.receive(delete(5 if early else 6))
            self.assertFalse(store.deleted)

    def test_delete_cannot_upload_or_switch_to_update(self):
        for frame in (put(5, 1, 1), commit(5, Store().record)):
            session, store, request = self.session()
            self.prepare(session, request)
            with self.assertRaises(ValueError): session.receive(frame)
            self.assertFalse(store.deleted or store.updated)

    def test_new_owner_cannot_confirm_old_delete(self):
        session, store, request = self.session()
        self.prepare(session, request)
        session.epoch_factory = lambda: 6
        session.receive(hello(2)); session.receive(accept(2, 6))
        with self.assertRaises(ValueError): session.receive(delete(5))
        self.assertFalse(store.deleted)

    def test_expired_session_never_issues_delete(self):
        session, store, request = self.session()
        self.prepare(session, request)
        session.clock = lambda: session.deadline + 1
        with self.assertRaises(TimeoutError): session.receive(delete(5))
        self.assertFalse(store.deleted)

    def test_late_success_remains_unknown(self):
        session, store, request = self.session()
        self.prepare(session, request)
        clock = [session.deadline - 1]
        session.clock = lambda: clock[0]
        original = store.delete
        def delayed(*args):
            result = original(*args)
            clock[0] += 2
            return result
        store.delete = delayed
        self.assertIn(b' UNKNOWN\r', session.receive(delete(5)))
        self.assertEqual(len(store.deleted), 1)

    def test_worker_failure_does_not_claim_definite_mutation_outcome(self):
        store = IsolatedWriteStore(('unused',), {})
        try:
            with patch.object(store, 'call', side_effect=StoreUnavailable()):
                self.assertEqual(store.begin_delete(99, pack_name('mortal')).status, 'UNAVAILABLE')
                self.assertEqual(store.delete(99, pack_name('mortal')).status, 'UNKNOWN')
        finally:
            store.close()
