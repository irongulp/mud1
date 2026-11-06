import unittest
from unittest.mock import Mock, patch

from tools.inspect_game import NativeInspector, InspectionError


class CompanionTransferTests(unittest.TestCase):
    def test_fragmented_echo_is_accumulated_before_advancing(self):
        native=NativeInspector()
        native.connection=Mock()
        native.connection.read_until.side_effect=[b'fi',b'rst\r',b'\n',b'\r\n.',b'\r\n.',b'\r\n.']
        native.begin_copy=Mock()
        native.command=Mock()
        with patch('tools.inspect_game.time.sleep'),patch('tools.build_external_guest.read_back',return_value='first'):
            native.install_source('pmsnap','first\n')
        self.assertEqual(native.connection.write.call_args_list[0].args,(b'first\r',))

    def test_eof_and_flow_control_are_not_treated_as_successful_source_echo(self):
        for response in (EOFError('private'), '\x13first\r\n', '\r\n.', 'first\r\nEXTRA'):
            with self.subTest(response=type(response).__name__):
                native=self.native([response])
                with patch('tools.inspect_game.time.sleep'),self.assertRaises(InspectionError):
                    native.install_source('pmsnap','first\nsecond\n')
                native.connection.write.assert_called_once_with(b'first\r')
                native.command.assert_not_called()

    def native(self, replies):
        native=NativeInspector()
        native.connection=Mock()
        native.begin_copy=Mock()
        native.receive=Mock(side_effect=replies)
        native.command=Mock()
        return native

    def test_wrong_echo_stops_before_next_line_eof_or_compile(self):
        native=self.native(['private unexpected content\r\n'])
        with patch('tools.inspect_game.time.sleep'):
            with self.assertRaisesRegex(InspectionError,'phase=echo line=1') as error:
                native.install_source('pmsnap','GET "LIBHDR"\nFINISH\n')
        self.assertNotIn('private unexpected content',str(error.exception))
        self.assertEqual([c.args[0] for c in native.connection.write.call_args_list],[b'GET "LIBHDR"\r'])
        native.command.assert_not_called()

    def test_line_timeout_reports_position_without_replay_or_private_buffer(self):
        native=self.native(['first\r\n',InspectionError('private buffer')])
        with patch('tools.inspect_game.time.sleep'):
            with self.assertRaisesRegex(InspectionError,'phase=echo line=2') as error:
                native.install_source('pmsnap','first\nsecond\nthird\n')
        self.assertNotIn('private buffer',str(error.exception))
        self.assertEqual(native.connection.write.call_count,2)
        native.command.assert_not_called()

    def test_full_source_mismatch_blocks_compilation_despite_matching_echoes(self):
        native=self.native(['first\r\n','\r\n.'])
        with patch('tools.inspect_game.time.sleep'), \
                patch('tools.build_external_guest.read_back',return_value='corrupt'):
            with self.assertRaisesRegex(InspectionError,'phase=read-back'):
                native.install_source('pmsnap','first\n')
        native.command.assert_not_called()

    def test_verified_tabs_and_blank_lines_compile_only_after_complete_readback(self):
        native=self.native(['        first\r\n','\r\n','end\r\n','\r\n.','\r\n.','\r\n.'])
        events=[]
        native.command.side_effect=lambda *a:events.append('compile')
        def readback(*args):
            self.assertEqual(events,[])
            events.append('verified')
            return '        first\n\nend\n'
        with patch('tools.inspect_game.time.sleep'),patch('tools.build_external_guest.read_back',side_effect=readback):
            native.install_source('pmsnap','\tfirst\n\nend\n')
        self.assertEqual(events[0],'verified')
        self.assertIn('compile',events)
