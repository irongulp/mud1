import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from server.runtime import MONITOR_PROMPT, OPERATOR_PROMPT, Runtime
from tools.guest_control import ControlError
from tools.inspect_game import InspectionError, NativeInspector


class VerifiedControllerTests(unittest.TestCase):
    def test_unknown_prompt_cannot_submit_console_commands(self):
        runtime = Runtime(Path('/unused'), '/unused')
        runtime.child = Mock()
        with self.assertRaisesRegex(RuntimeError, 'prompt'):
            runtime.command('r opr')
        runtime.child.send.assert_not_called()

    def test_program_dialogue_does_not_use_monitor_echo_protocol(self):
        native = NativeInspector()
        native.connection = Mock()
        native.at_monitor = False
        with patch('tools.inspect_game.submit_line') as submit, patch.object(native, 'receive', return_value='\r\n.'):
            native.command('1234567')
        submit.assert_not_called()
        native.connection.write.assert_called_once_with(b'1234567\r')

    def test_lost_inspector_completion_is_not_replayed(self):
        native = NativeInspector()
        native.connection = Mock()
        native.at_monitor = True
        with patch('tools.inspect_game.submit_line', return_value=b'copy fixture.tmp=tty:') as submit, \
                patch.object(native, 'receive', side_effect=InspectionError('completion lost')):
            with self.assertRaises(InspectionError):
                native.command('copy fixture.tmp=tty:')
        submit.assert_called_once()
        self.assertFalse(native.at_monitor)

    def test_operator_can_resynchronize_only_before_input_started(self):
        for started in (False, True):
            runtime = Runtime(Path('/unused'), '/unused')
            runtime.child = Mock(before='', after='KSYS processing completed')
            runtime.control_prompt = OPERATOR_PROMPT
            failure = ControlError('pending notice', input_started=started)
            with patch.object(runtime, '_submit_control', side_effect=[failure, 'set ksys now']) as submit:
                if started:
                    with self.assertRaises(ControlError):
                        runtime.command('set ksys now', 'KSYS processing completed')
                    submit.assert_called_once()
                else:
                    runtime.command('set ksys now', 'KSYS processing completed')
                    self.assertEqual(submit.call_count, 2)

    def test_copy_deadline_covers_header_payload_and_completion(self):
        runtime = Runtime(Path('/unused'), '/unused')
        runtime.child = Mock()
        runtime.control_prompt = MONITOR_PROMPT
        now = [0]
        def header(*args):
            now[0] = 61
            return 'copy stage.tmp=tty:'
        with patch('server.runtime.time.monotonic', side_effect=lambda: now[0]), \
                patch('server.runtime.time.sleep'), patch.object(runtime, '_submit_control', side_effect=header):
            with self.assertRaises(TimeoutError):
                runtime.copy_text('stage.tmp', '\n')
        runtime.child.send.assert_not_called()
        runtime.child.sendcontrol.assert_not_called()
        self.assertIsNone(runtime.control_prompt)

    def test_shutdown_never_types_os_commands_into_unfinished_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Runtime(Path(directory), '/unused')
            runtime.child = Mock()
            runtime.booted = True
            def expect(marker, **kwargs):
                if marker == '^C':
                    raise TimeoutError('monitor recovery failed')
            runtime.child.expect_exact.side_effect = expect
            with patch.object(runtime, '_submit_control') as submit:
                self.assertFalse(runtime.stop())
            submit.assert_not_called()
