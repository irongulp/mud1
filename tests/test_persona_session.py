"""Epoch retirement and credit-based R1 flow control, without a database."""
import socket
import threading
import time
import unittest
from unittest.mock import Mock

from tools.persona_protocol import GetRequest, ResponseDecoder, pack_name, encode_get, ProtocolError
from tools.persona_session import ReadSession, LineSocket, serve_reads, hello, accept, ack


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.epochs = iter((1 << 71, (1 << 71) + 1, (1 << 71) + 2))
        self.calls = []
        def fetch(name):
            self.calls.append(name)
            return (7, name[0] | 1, name[1] | 1, 1 << 35, (1 << 36) - 1, 0, 511, 123, 0, 1 << 35, 0)
        self.session = ReadSession(fetch, clock=lambda: self.now, epoch_factory=lambda: next(self.epochs))

    def establish(self, challenge=1):
        offered = self.session.receive(hello(challenge))
        epoch = int(offered.split()[3], 8)
        self.assertEqual(offered, f'H1 OFFER {challenge:024o} {epoch:024o}\r'.encode())
        ready = self.session.receive(accept(challenge, epoch))
        self.assertEqual(ready, f'H1 READY {challenge:024o} {epoch:024o}\r'.encode())
        return GetRequest(epoch, 1, pack_name('fred'))

    def test_requires_confirmation_before_get(self):
        self.session.receive(hello(1))
        with self.assertRaises(ProtocolError):
            self.session.receive(encode_get(GetRequest(1 << 71, 1, pack_name('fred'))))
        self.assertFalse(self.calls)

    def test_no_word_is_sent_without_matching_credit(self):
        request = self.establish()
        header = self.session.receive(encode_get(request))
        self.assertIn(b' FOUND ', header)
        for index in range(11):
            row = self.session.receive(ack(request, index))
            self.assertIn(f' {index+1:02o} '.encode(), row)
            self.assertEqual(row.count(b'\r'), 1)
        self.assertIn(b' END ', self.session.receive(ack(request, 11)))
        self.assertIsNone(self.session.receive(ack(request, 12)))
        self.assertIsNone(self.session.deadline)
        with self.assertRaises(ProtocolError):
            self.session.receive(encode_get(request))

    def test_new_owner_retires_pending_record(self):
        old = self.establish(1)
        self.session.receive(encode_get(old))
        self.session.receive(ack(old, 0))
        new = self.establish(2)
        self.assertNotEqual(old.epoch, new.epoch)
        with self.assertRaises(ProtocolError):
            self.session.receive(ack(old, 1))
        self.assertEqual(len(self.calls), 1)

    def test_ready_and_ack_cannot_be_replayed(self):
        request = self.establish()
        self.session.receive(encode_get(request))
        self.session.receive(ack(request, 0))
        with self.assertRaises(ProtocolError):
            self.session.receive(ack(request, 0))
        with self.assertRaises(ProtocolError):
            self.session.receive(hello(1))

    def test_wrong_accept_does_not_establish_epoch(self):
        self.session.receive(hello(1))
        with self.assertRaises(ProtocolError):
            self.session.receive(accept(2, 1 << 71))
        self.assertFalse(self.calls)

    def test_flow_control_does_not_extend_response_deadline(self):
        request = self.establish()
        self.session.receive(encode_get(request))
        self.now = 4.9
        self.session.receive(ack(request, 0))
        self.now = 5.1
        with self.assertRaises(TimeoutError):
            self.session.receive(ack(request, 1))
        self.assertFalse(self.session.active)

    def test_expired_owner_can_be_replaced_but_not_resumed(self):
        old = self.establish()
        self.now = 6
        with self.assertRaises(TimeoutError):
            self.session.expire()
        new = self.establish(2)
        self.assertNotEqual(old.epoch, new.epoch)
        self.assertIn(b' FOUND ', self.session.receive(encode_get(new)))

    def test_error_response_also_requires_final_ack(self):
        session = ReadSession(lambda _: None, epoch_factory=lambda: 5)
        session.receive(hello(1))
        session.receive(accept(1, 5))
        request = GetRequest(5, 1, pack_name('fred'))
        self.assertIn(b' NOT_FOUND ', session.receive(encode_get(request)))
        self.assertIsNone(session.receive(ack(request, 0)))
        self.assertFalse(session.active)

    def test_history_is_bounded_and_epoch_reuse_is_rejected(self):
        session = ReadSession(lambda _: None, epoch_factory=lambda: 5, history_limit=1)
        session.receive(hello(1))
        with self.assertRaises(ProtocolError):
            session.receive(hello(2))
        session = ReadSession(lambda _: None, epoch_factory=lambda: 5)
        session.receive(hello(1))
        with self.assertRaises(ProtocolError):
            session.receive(hello(2))

    def test_malformed_input_fences_active_work(self):
        self.establish()
        with self.assertRaises(ProtocolError):
            self.session.receive(b'kjob\r')
        self.assertFalse(self.session.active)


class SocketTests(unittest.TestCase):
    def test_send_timeout_is_normalized_on_python39(self):
        connection = Mock()
        connection.sendall.side_effect = socket.timeout('private transport detail')
        with self.assertRaisesRegex(TimeoutError, '^Channel output deadline expired$'):
            LineSocket(connection).send(b'frame\r', time.monotonic() + 1)

    def start(self):
        client, server = socket.socketpair()
        errors = []
        def worker():
            with server:
                try:
                    serve_reads(server, lambda name: (1, *name, 0, 0, 0, 0, 0, 0, 0, 0))
                except Exception as error:
                    errors.append(error)
        thread = threading.Thread(target=worker)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(client.close)
        return client, LineSocket(client), errors

    def test_real_socket_full_record_and_credit(self):
        client, wire, errors = self.start()
        client.sendall(hello(9))
        offer = wire.read(time.monotonic() + 1)
        epoch = int(offer.split()[3], 8)
        client.sendall(accept(9, epoch))
        self.assertIn(b' READY ', wire.read(time.monotonic() + 1))
        request = GetRequest(epoch, 1, pack_name('fred'))
        client.sendall(encode_get(request))
        decoder = ResponseDecoder(request)
        decoder.feed(wire.read(time.monotonic() + 1))
        client.settimeout(0.03)
        with self.assertRaises(socket.timeout):
            client.recv(1)  # No word until header ACK.
        for index in range(12):
            client.sendall(ack(request, index))
            decoder.feed(wire.read(time.monotonic() + 1))
        client.sendall(ack(request, 12))
        self.assertEqual(decoder.finish().record.name_words, request.name_words)
        self.assertFalse(errors)

    def test_semantic_rejection_allows_fresh_handover(self):
        client, wire, errors = self.start()
        client.sendall(b'R1 ACK 000000000000000000000001 000000000001 00\r')
        client.sendall(hello(2))
        self.assertIn(b'H1 OFFER', wire.read(time.monotonic() + 1))
        self.assertFalse(errors)

    def test_wire_truncation_and_partial_deadline(self):
        for partial_eof in (True, False):
            client, server = socket.socketpair()
            with client, server:
                client.sendall(b'R1 GET ')
                if partial_eof:
                    client.shutdown(socket.SHUT_WR)
                with self.assertRaises(ProtocolError if partial_eof else TimeoutError):
                    LineSocket(server).read(time.monotonic() + 0.03)
