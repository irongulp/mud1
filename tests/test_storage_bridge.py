"""The experimental transport must preserve words and reject mixed sessions."""
import socket
import threading
import unittest

from tools.storage_bridge import Frame, FrameDecoder, ProtocolError, WORD_MASK, respond


class FrameTests(unittest.TestCase):
    def test_host_sends_single_cr_for_tops10_input(self):
        self.assertEqual(Frame('PONG', 1, 1, 0).encode(),
                         b'B1 PONG 000001 000001 000000000000\r')

    def test_every_word_bit_survives_fragmented_frames(self):
        values = [0, WORD_MASK, 1 << 35, (1 << 35) - 1]
        values += [1 << bit for bit in range(36)]
        expected = [Frame('PING', 1, index + 1, word) for index, word in enumerate(values)]
        decoder = FrameDecoder()
        actual = []
        for byte in b''.join(frame.encode() for frame in expected):
            actual.extend(decoder.feed(bytes([byte])))
        self.assertEqual(expected, actual)

    def test_cr_and_crlf_frames_can_share_a_read(self):
        wire = b'B1 PING 000001 000001 777777777777\rB1 PONG 000002 000001 400000000000\r\n'
        self.assertEqual(FrameDecoder().feed(wire),
                         [Frame('PING', 1, 1, WORD_MASK), Frame('PONG', 2, 1, 1 << 35)])

    def test_malformed_and_monitor_text_is_not_a_request(self):
        for wire in (b'\r', b'.kjob\r', b'B2 PING 000001 000001 000000000000\r',
                     b'B1 PING 000001 000001 000000000008\r',
                     b'B1 PING 000001 000001 000000000000 EXTRA\r', b'\xff\r'):
            with self.subTest(wire=wire), self.assertRaises(ProtocolError):
                FrameDecoder().feed(wire)

    def test_unterminated_input_is_bounded(self):
        with self.assertRaises(ProtocolError):
            FrameDecoder().feed(b'X' * 65)

    def test_encoder_rejects_truncation_and_invalid_identity(self):
        for frame in (Frame('PING', 1, 1, -1), Frame('PING', 1, 1, WORD_MASK + 1),
                      Frame('PING', 1 << 18, 1, 0), Frame('PING', 1, 0, 0),
                      Frame('QUIT', 1, 1, 0)):
            with self.subTest(frame=frame), self.assertRaises(ProtocolError):
                frame.encode()


class ResponderTests(unittest.TestCase):
    def start(self, timeout=1):
        host, guest = socket.socketpair()
        guest.settimeout(2)
        errors = []
        def worker():
            with host:
                try:
                    respond(host, timeout=timeout)
                except (ProtocolError, TimeoutError) as error:
                    errors.append(type(error))
        thread = threading.Thread(target=worker)
        thread.start()
        self.addCleanup(thread.join, 3)
        # Cleanup is LIFO: close the client before joining the worker.
        self.addCleanup(guest.close)
        return guest, thread, errors

    def receive(self, guest):
        decoder = FrameDecoder()
        while True:
            data = guest.recv(256)
            self.assertTrue(data, 'Responder closed before PONG')
            frames = decoder.feed(data)
            if frames:
                return frames[0]

    def test_two_connections_isolate_identical_request_numbers(self):
        clients = [self.start()[0] for _ in range(2)]
        for session, client in enumerate(clients, 1):
            client.sendall(Frame('PING', session, 1, WORD_MASK - session).encode())
        for session, client in enumerate(clients, 1):
            self.assertEqual(self.receive(client), Frame('PONG', session, 1, WORD_MASK - session))

    def test_duplicate_or_changed_session_is_rejected(self):
        for second in (Frame('PING', 1, 1, 0), Frame('PING', 2, 2, 0), Frame('PONG', 1, 2, 0)):
            client, thread, errors = self.start()
            client.sendall(Frame('PING', 1, 1, 0).encode())
            self.receive(client)
            client.sendall(second.encode())
            self.assertEqual(client.recv(256), b'')
            thread.join(2)
            self.assertEqual(errors, [ProtocolError])

    def test_partial_frame_deadline_closes_connection(self):
        client, thread, errors = self.start(timeout=0.05)
        client.sendall(b'B1 PING ')
        self.assertEqual(client.recv(256), b'')
        thread.join(2)
        self.assertEqual(errors, [TimeoutError])

    def test_truncated_disconnect_is_not_a_success(self):
        client, thread, errors = self.start()
        client.sendall(b'B1 PING 000001')
        client.shutdown(socket.SHUT_WR)
        self.assertEqual(client.recv(256), b'')
        thread.join(2)
        self.assertEqual(errors, [ProtocolError])
