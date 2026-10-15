"""Polling boundaries must not lose a complete marker or its trailing reply."""
import unittest
import socket
import telnetlib
from unittest.mock import Mock, patch

from tools.capture_personas import SnapshotInspector
from tools.inspect_game import NativeInspector
from tools.inspect_game import InspectionError
from tools.build_external_guest import read_back


class PollingConnection:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.now = 0
        self.reads = 0

    def read_until(self, marker, timeout):
        self.reads += 1
        self.now += timeout
        return self.chunks.pop(0) if self.chunks else b''


class NativeResponseFramingTests(unittest.TestCase):
    def test_real_telnet_partial_poll_can_overread_the_completed_marker(self):
        client, peer = socket.socketpair()
        with client, peer:
            connection = telnetlib.Telnet()
            connection.sock = client
            peer.sendall(b'first\r\nfinal source ')
            first = connection.read_until(b'final source line\r\n', 0)
            peer.sendall(b'line\r\n\r\n.')
            second = connection.read_until(b'final source line\r\n', 0)
            self.assertEqual(first + second, b'first\r\nfinal source line\r\n\r\n.')
            self.assertFalse((first + second).endswith(b'final source line\r\n'))
            self.assertIn(b'final source line\r\n', first + second)

    def test_missing_marker_retains_existing_deadline_failure(self):
        for inspector in (NativeInspector, SnapshotInspector):
            native = inspector()
            native._command_deadline = 3
            connection = PollingConnection([b'incomplete'])
            native.connection = connection
            with self.subTest(inspector=inspector.__name__), \
                    patch('tools.inspect_game.time.monotonic', side_effect=lambda: connection.now), \
                    self.assertRaises(InspectionError):
                native.receive(b'END')
            self.assertEqual(connection.now, 3)

    def test_existing_response_size_bound_still_applies(self):
        native = NativeInspector()
        native._command_deadline = 5
        connection = PollingConnection([b'oversized END'])
        native.connection = connection
        with patch('tools.inspect_game.MAX_RESPONSE', 4), \
                patch('tools.inspect_game.time.monotonic', side_effect=lambda: connection.now), \
                self.assertRaisesRegex(InspectionError, 'size'):
            native.receive(b'END')

    def test_snapshot_ascii_validation_is_still_strict(self):
        native = SnapshotInspector()
        native._command_deadline = 5
        connection = PollingConnection([b'\xffEND'])
        native.connection = connection
        with patch('tools.inspect_game.time.monotonic', side_effect=lambda: connection.now), \
                self.assertRaises(UnicodeDecodeError):
            native.receive(b'END')

    def test_split_marker_with_trailing_prompt_is_preserved(self):
        for inspector in (NativeInspector, SnapshotInspector):
            with self.subTest(inspector=inspector.__name__):
                native = inspector()
                native._command_deadline = 5
                connection = PollingConnection([b'first\r\nfinal source ', b'line\r\n\r\n.'])
                native.connection = connection
                with patch('tools.inspect_game.time.monotonic', side_effect=lambda: connection.now):
                    self.assertEqual(native.receive(b'final source line\r\n'),
                                     'first\r\nfinal source line\r\n')
                    self.assertEqual(native.receive(b'.'), '\r\n.')
                self.assertEqual(connection.reads, 2, 'Buffered prompt must not wait for new transport data')

    def test_complete_marker_and_following_frame_in_one_poll(self):
        native = NativeInspector()
        native._command_deadline = 5
        connection = PollingConnection([b'first\r\nEND\r\nNEXT\r\n'])
        native.connection = connection
        with patch('tools.inspect_game.time.monotonic', side_effect=lambda: connection.now):
            self.assertEqual(native.receive(b'END\r\n'), 'first\r\nEND\r\n')
            self.assertEqual(native.receive(b'NEXT\r\n'), 'NEXT\r\n')
        self.assertEqual(connection.reads, 1)

    def test_source_readback_does_not_timeout_after_complete_type_output(self):
        native = SnapshotInspector()
        native._command_deadline = 5
        connection = PollingConnection([b'\r\nfirst\r\nlast sou', b'rce line\r\n\r\n.'])
        native.connection = connection
        with patch.object(native, 'send_control', return_value='type rdtest.bcl'), \
                patch('tools.inspect_game.time.monotonic', side_effect=lambda: connection.now):
            actual = read_back(native, 'rdtest.bcl', 'first\nlast source line\n')
        self.assertEqual(actual.strip(), 'first\nlast source line')
        self.assertTrue(native.at_monitor)

    def test_control_echo_consumes_owned_buffer_before_transport(self):
        native = NativeInspector()
        native.connection = Mock()
        native._response_pending = bytearray(b'x')
        with patch('tools.inspect_game.telnet_byte', return_value=b'y') as transport:
            self.assertEqual(native._control_byte(0), b'x')
            transport.assert_not_called()
            self.assertEqual(native._control_byte(0), b'y')
