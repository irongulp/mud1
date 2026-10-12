import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from tools import inspect_game, reset_permissions, terminal_config
from server.runtime import Runtime


class VerifiedControllerTests(unittest.TestCase):
    def test_inspector_verifies_only_confirmed_monitor_commands(self):
        native = inspect_game.NativeInspector()
        native.connection = Mock()
        native.at_monitor = True
        with patch('tools.inspect_game.submit_line', return_value=b'run mvtxt') as submit, \
                patch.object(native, 'receive', return_value='\r\nMVTXT READY\r\n'):
            self.assertEqual(native.command('run mvtxt', b'MVTXT READY\r\n'),
                             'run mvtxt\r\nMVTXT READY\r\n')
        submit.assert_called_once()
        self.assertFalse(native.at_monitor)
        # Program payloads, including opaque bootstrap values, are not monitor
        # commands and must not be subjected to a printable echo protocol.
        with patch('tools.inspect_game.submit_line') as submit, \
                patch.object(native, 'receive', return_value='\r\n.'):
            native.command('1234567')
        submit.assert_not_called()
        native.connection.write.assert_called_once_with(b'1234567\r')

    def test_lost_completion_is_not_replayed_by_inspector(self):
        native = inspect_game.NativeInspector()
        native.connection = Mock()
        native.at_monitor = True
        with patch('tools.inspect_game.submit_line', return_value=b'protect mud.exe<051>') as submit, \
                patch.object(native, 'receive', side_effect=inspect_game.InspectionError('completion lost')):
            with self.assertRaises(inspect_game.InspectionError):
                native.command('protect mud.exe<051>')
        submit.assert_called_once()
        self.assertFalse(native.at_monitor)

    def test_console_refuses_commands_when_prompt_state_is_unknown(self):
        machine = Runtime(Path('/unused'), '/unused')
        machine.child = Mock()
        with self.assertRaisesRegex(RuntimeError, 'prompt'):
            machine.command('r opr')
        machine.child.send.assert_not_called()

    def test_console_changes_state_only_after_expected_completion(self):
        machine = Runtime(Path('/unused'), '/unused')
        machine.child = Mock(before='\r\n', after='OPR>')
        machine.control_prompt = r'\n\.'
        with patch('server.runtime.submit_line', return_value=b'r opr') as submit:
            self.assertEqual(machine.command('r opr', 'OPR>'), 'r opr\r\nOPR>')
        submit.assert_called_once()
        self.assertEqual(machine.control_prompt, 'OPR>')

    def test_operator_notifications_resynchronize_before_any_input(self):
        from tools.guest_control import ControlError
        machine = Runtime(Path('/unused'), '/unused')
        machine.child = Mock(before='', after='KSYS processing completed')
        machine.control_prompt = 'OPR>'
        notice = ControlError('pending operator notification', input_started=False)
        with patch.object(machine, '_submit_control', side_effect=[notice, 'set ksys now']) as submit:
            machine.command('set ksys now', 'KSYS processing completed')
        self.assertEqual(submit.call_count, 2)
        self.assertEqual([call.args[0] for call in machine.child.expect.call_args_list],
                         ['OPR>', 'KSYS processing completed'])

    def test_operator_never_replays_a_partially_typed_command(self):
        from tools.guest_control import ControlError
        machine = Runtime(Path('/unused'), '/unused')
        machine.child = Mock()
        machine.control_prompt = 'OPR>'
        with patch.object(machine, '_submit_control',
                          side_effect=ControlError('bad echo', input_started=True)) as submit:
            with self.assertRaises(ControlError):
                machine.command('set ksys now', 'KSYS processing completed')
        submit.assert_called_once()
        machine.child.expect.assert_not_called()

    def test_copy_deadline_covers_header_payload_and_completion(self):
        machine = Runtime(Path('/unused'), '/unused')
        machine.child = Mock()
        machine.control_prompt = r'\n\.'
        now = [0]
        def header(*args):
            now[0] = 61
            return 'copy stage.tmp=tty:'
        with patch('server.runtime.time.monotonic', side_effect=lambda: now[0]), \
                patch('server.runtime.time.sleep'), patch.object(machine, '_submit_control', side_effect=header):
            with self.assertRaises(TimeoutError):
                machine.copy_text('stage.tmp', '\n')
        machine.child.send.assert_not_called()
        machine.child.sendcontrol.assert_not_called()
        self.assertIsNone(machine.control_prompt)

    def test_shutdown_does_not_type_operator_commands_into_failed_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            machine = Runtime(Path(directory), '/unused')
            machine.child = Mock()
            machine.child.isalive.return_value = True
            machine.booted = True
            def expect(marker, **kwargs):
                if marker == '^C':
                    raise TimeoutError('monitor recovery failed')
            machine.child.expect_exact.side_effect = expect
            with patch.object(machine, '_submit_control') as submit:
                self.assertFalse(machine.stop())
            submit.assert_not_called()

    def test_permission_recovery_reads_back_before_any_second_write(self):
        first, second = Mock(), Mock()
        first.__enter__ = Mock(return_value=first)
        first.__exit__ = Mock(return_value=False)
        first.cleanup_confirmed = True
        second.__enter__ = Mock(return_value=second)
        second.__exit__ = Mock(return_value=False)
        first.command.side_effect = ['MUD EXE 492 <055> date\r\n.',
                                     inspect_game.InspectionError('reply lost')]
        second.command.return_value = 'MUD EXE 492 <051> date\r\n.'
        with self.assertLogs('tools.reset_permissions', level='WARNING') as logged, \
                patch.object(reset_permissions, 'NativeInspector', side_effect=[first, second]):
            reset_permissions.configure_port(2020)
        self.assertIn('read-back', logged.output[0])
        second.command.assert_called_once_with('directory ' + reset_permissions.EXECUTABLE)
        self.assertEqual(first.command.call_count, 2)

    def test_permission_recovery_requires_confirmed_cleanup(self):
        native = Mock(cleanup_confirmed=False)
        native.__enter__ = Mock(return_value=native)
        native.__exit__ = Mock(return_value=False)
        native.command.side_effect = inspect_game.InspectionError('timeout')
        with patch.object(reset_permissions, 'NativeInspector', return_value=native) as factory:
            with self.assertRaises(inspect_game.InspectionError):
                reset_permissions.configure_port(2020)
        factory.assert_called_once()

    def test_permission_reconciliation_is_not_an_admission_retry(self):
        native = Mock(cleanup_confirmed=True)
        native.__enter__ = Mock(side_effect=inspect_game.InspectionError('login failed'))
        native.__exit__ = Mock(return_value=False)
        with patch.object(reset_permissions, 'NativeInspector', return_value=native) as factory:
            with self.assertRaises(inspect_game.InspectionError):
                reset_permissions.configure_port(2020)
        factory.assert_called_once()


class StagedTerminalConfigTests(unittest.TestCase):
    original = 'ALL KSYS LC WIDTH:255\nCTY: GALOPR\nSTOMP ACCOUNT "SYSTEM"\n'
    desired = 'ALL KSYS LC WIDTH:255\nCTY: GALOPR\n'

    def machine(self, staged=None, listing='?No such file\r\n.'):
        machine = Mock()
        def command(text):
            if text == 'type sys:tty.ini':
                contents = self.desired if 'copy sys:tty.ini=sys:xtty.tmp' in [
                    call.args[0] for call in machine.command.call_args_list] else self.original
                return text + '\r\n' + contents.replace('\n', '\r\n') + '\r\n.'
            if text == 'directory sys:xtty.tmp':
                return listing
            if text == 'type sys:xtty.tmp':
                return text + '\r\n' + (staged if staged is not None else self.desired) + '\r\n.'
            return '\r\n.'
        machine.command.side_effect = command
        return machine

    def test_bad_staged_content_never_replaces_active_configuration(self):
        machine = self.machine(staged='damaged\n')
        with self.assertRaises(RuntimeError):
            terminal_config.protect_bridge_terminals(machine)
        machine.copy_text.assert_called_once_with('sys:xtty.tmp', self.desired)
        self.assertNotIn('copy sys:tty.ini=sys:xtty.tmp',
                         [call.args[0] for call in machine.command.call_args_list])

    def test_verified_stage_is_activated_then_read_back(self):
        machine = self.machine()
        self.assertTrue(terminal_config.protect_bridge_terminals(machine))
        machine.copy_text.assert_called_once_with('sys:xtty.tmp', self.desired)
        commands = [call.args[0] for call in machine.command.call_args_list]
        self.assertLess(commands.index('type sys:xtty.tmp'), commands.index('copy sys:tty.ini=sys:xtty.tmp'))
        self.assertEqual(commands[-1], 'type sys:tty.ini')

    def test_native_wldnsf_confirms_missing_staging_file(self):
        machine = self.machine(listing='%WLDNSF No such files as sys:xtty.tmp\r\n.')
        self.assertTrue(terminal_config.protect_bridge_terminals(machine))

    def test_existing_or_unreadable_stage_is_preserved(self):
        for listing in ('XTTY TMP 1 <057> date\r\n.', '?Protection failure\r\n.',
                        '%WLDNSF No such files as other.tmp\r\n.', '?No such file other.tmp\r\n.'):
            machine = self.machine(listing=listing)
            with self.subTest(listing=listing), self.assertRaises(RuntimeError):
                terminal_config.protect_bridge_terminals(machine)
            machine.copy_text.assert_not_called()
