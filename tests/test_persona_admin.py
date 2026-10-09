import unittest
from tools.persona_protocol import GetRequest, LogicalRecord, pack_name
from tools.persona_session import hello, accept, ack
from tools.persona_write_session import WriteSession, admin_start, next_frame, fetch, key_frame
from tools.persona_writes import WriteResult


class Store:
    def __init__(self):
        self.record = LogicalRecord((1, *pack_name('fred'), 0, 0, 0, 0, 123, 0, 0, 0))
        self.deleted = []
    def get(self, key): return self.record
    def begin_purge(self, op, key): return WriteResult('OPEN', self.record)
    def begin_next(self, op, after): return WriteResult('OPEN', self.record)
    def purge(self, op, key):
        self.deleted.append((op, key))
        return WriteResult('COMMITTED')


class AdminSessionTests(unittest.TestCase):
    def session(self, enabled=True, epoch=5):
        store = Store()
        session = WriteSession(store, allow_admin=enabled, epoch_factory=lambda: epoch)
        session.receive(hello(1)); session.receive(accept(1, epoch))
        return session, store

    def test_admin_is_opt_in(self):
        for tag in ('PSTART', 'NSTART', 'PDELETE'):
            session, store = self.session(False)
            with self.assertRaises(ValueError): session.receive(admin_start(tag, 5, 99))
            self.assertFalse(store.deleted)

    def test_view_retires_transport_and_does_not_delete(self):
        session, store = self.session()
        session.receive(admin_start('PSTART', 5, 99))
        session.receive(key_frame(5, pack_name('fred')))
        for index in range(13): session.receive(ack(GetRequest(5, 1, pack_name('fred')), index))
        self.assertEqual(session.state, 'idle')
        self.assertFalse(store.deleted)

    def test_next_requires_name_credit_before_record(self):
        session, store = self.session()
        session.receive(admin_start('NSTART', 5, 99))
        self.assertIn(b'W1 NAME ', session.receive(next_frame(5, None)))
        self.assertFalse(store.deleted)
        self.assertIn(b'R1 FOUND ', session.receive(fetch(5)))
        for index in range(13): session.receive(ack(GetRequest(5, 1, pack_name('fred')), index))
        self.assertEqual(session.state, 'idle')

    def test_explicit_confirmation_uses_original_operation(self):
        session, store = self.session(epoch=6)
        session.receive(admin_start('PDELETE', 6, 99))
        self.assertIn(b' COMMITTED\r', session.receive(key_frame(6, pack_name('fred'))))
        self.assertEqual(store.deleted, [(99, pack_name('fred'))])

    def test_old_epoch_and_nonadvancing_cursor_are_rejected(self):
        session, store = self.session()
        session.receive(admin_start('NSTART', 5, 99))
        with self.assertRaises(ValueError): session.receive(next_frame(5, pack_name('fred')))
        self.assertFalse(store.deleted)
        session, store = self.session()
        session.receive(admin_start('PDELETE', 5, 99))
        with self.assertRaises(ValueError): session.receive(key_frame(6, pack_name('fred')))
        self.assertFalse(store.deleted)

    def test_expired_confirmation_never_mutates(self):
        session, store = self.session()
        session.receive(admin_start('PDELETE', 5, 99))
        deadline = session.deadline
        session.clock = lambda: deadline + 1
        with self.assertRaises(TimeoutError): session.receive(key_frame(5, pack_name('fred')))
        self.assertFalse(store.deleted)

    def test_late_purge_result_is_unknown(self):
        session, store = self.session()
        session.receive(admin_start('PDELETE', 5, 99))
        clock = [session.deadline - 1]
        session.clock = lambda: clock[0]
        original = store.purge
        def late(*args):
            result = original(*args)
            clock[0] += 2
            return result
        store.purge = late
        self.assertIn(b' UNKNOWN\r', session.receive(key_frame(5, pack_name('fred'))))
        self.assertEqual(len(store.deleted), 1)
