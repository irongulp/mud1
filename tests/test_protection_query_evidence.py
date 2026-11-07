import io
import json
import unittest
from contextlib import redirect_stderr
from unittest.mock import Mock, patch

from tools.reset_permissions import ProtectionInspector, EXECUTABLE
from tools.inspect_game import InspectionError


class ProtectionEvidenceTests(unittest.TestCase):
    def test_partial_listing_timeout_keeps_counts_and_prompt_flags_not_contents(self):
        native=ProtectionInspector()
        native.connection=Mock(eof=False)
        native.at_monitor=True
        now=[0]
        def read_until(*args):
            now[0]=100
            return b'private text\r\nMUD EXE 492 <051> 18-Sep-26\r.'
        native.connection.read_until.side_effect=read_until
        with patch.object(native,'_submit_control',return_value='echo'), \
                patch('tools.inspect_game.time.monotonic',side_effect=lambda:now[0]), \
                redirect_stderr(io.StringIO()) as output:
            with self.assertRaises(InspectionError): native.command('directory '+EXECUTABLE)
        record=json.loads(output.getvalue())
        self.assertTrue(record['echo_confirmed'])
        self.assertTrue(record['directory_entry_seen'])
        self.assertTrue(record['ends_cr_dot'])
        self.assertFalse(record['newline_dot_seen'])
        self.assertNotIn('private text',output.getvalue())
        self.assertIsNone(native._response_observer)

    def test_other_commands_never_enable_query_capture(self):
        native=ProtectionInspector()
        with patch('tools.inspect_game.NativeInspector.command',return_value='ok') as command, \
                redirect_stderr(io.StringIO()) as output:
            native.command('login richard')
        command.assert_called_once()
        self.assertEqual(output.getvalue(),'')
        self.assertIsNone(getattr(native,'_response_observer',None))

    def test_successful_query_is_not_reported_as_failure(self):
        native=ProtectionInspector()
        with patch('tools.inspect_game.NativeInspector.command',return_value='ok'), \
                redirect_stderr(io.StringIO()) as output:
            self.assertEqual(native.command('directory '+EXECUTABLE),'ok')
        self.assertEqual(output.getvalue(),'')
