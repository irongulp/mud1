"""Corrupted input must not execute or replace active guest configuration."""
from pathlib import Path
import unittest
from unittest.mock import Mock

from server.runtime import Runtime
from tools import terminal_config


class CorruptConsole:
    delaybeforesend = 0
    before = ''
    after = ''

    def __init__(self):
        self.pending = bytearray()
        self.typed = bytearray()
        self.executed = []
        self.sent = []

    def send(self, text):
        self.sent.append(text)
        # Whole-line input models the witnessed tty.ini -> tyt.ini corruption.
        # For verified byte input, the first t is corrupted and echoed as y.
        if len(text) > 1:
            damaged = text.replace('tty.ini', 'tyt.ini')
            self.pending.extend(damaged.encode())
            if damaged.endswith('\r'):
                self.executed.append(damaged.rstrip('\r'))
        elif text == '\r':
            self.executed.append(self.typed.decode())
        else:
            damaged = 'y' if text == 't' else text
            self.typed.extend(damaged.encode())
            self.pending.extend(damaged.encode())

    def expect(self, pattern, **kwargs):
        if pattern == r'[\s\S]':
            if not self.pending:
                import pexpect
                raise pexpect.TIMEOUT('no echo')
            self.after = chr(self.pending.pop(0))
        else:
            self.before = self.pending.decode()
            self.after = '\n.'


class ControlStagingTests(unittest.TestCase):
    original = 'ALL KSYS LC WIDTH:255\nCTY: GALOPR\nSTOMP ACCOUNT "SYSTEM"\n'
    desired = 'ALL KSYS LC WIDTH:255\nCTY: GALOPR\n'

    def test_corrupted_echo_never_submits_copy(self):
        runtime = Runtime(Path('/unused'), '/unused')
        runtime.child = CorruptConsole()
        runtime.control_prompt = r'\n\.'
        with self.assertRaises(RuntimeError):
            runtime.command('copy sys:tty.ini=tty:')
        self.assertEqual(runtime.child.executed, [])
        self.assertNotIn('\r', runtime.child.sent)

    def machine(self, staged=None, listing='%WLDNSF No such files as sys:xtty.tmp\r\n.'):
        machine = Mock()
        def command(text):
            if text == 'type sys:tty.ini':
                active = any(call.args[0] == 'copy sys:tty.ini=sys:xtty.tmp'
                             for call in machine.command.call_args_list)
                contents = self.desired if active else self.original
            elif text == 'directory sys:xtty.tmp':
                return listing
            elif text == 'type sys:xtty.tmp':
                contents = self.desired if staged is None else staged
            else:
                return '\r\n.'
            return text + '\r\n' + contents.replace('\n', '\r\n') + '\r\n.'
        machine.command.side_effect = command
        return machine

    def test_bad_stage_cannot_replace_active_configuration(self):
        machine = self.machine(staged='damaged\n')
        with self.assertRaises(RuntimeError):
            terminal_config.protect_bridge_terminals(machine)
        self.assertFalse(any('copy sys:tty.ini=tty:' in call.args[0]
                             for call in machine.child.send.call_args_list))
        self.assertNotIn('copy sys:tty.ini=sys:xtty.tmp',
                         [call.args[0] for call in machine.command.call_args_list])

    def test_verified_stage_is_activated_only_after_read_back(self):
        machine = self.machine()
        self.assertTrue(terminal_config.protect_bridge_terminals(machine))
        machine.copy_text.assert_called_once_with('sys:xtty.tmp', self.desired)
        commands = [call.args[0] for call in machine.command.call_args_list]
        self.assertLess(commands.index('type sys:xtty.tmp'), commands.index('copy xtty.ini=sys:tty.ini'))
        self.assertLess(commands.index('type sys:xtty.tmp'), commands.index('copy sys:tty.ini=sys:xtty.tmp'))
        self.assertEqual(commands[-1], 'type sys:tty.ini')

    def test_occupied_or_unreadable_stage_is_preserved(self):
        for listing in ('XTTY TMP 1 <057> date\r\n.', '?Protection failure\r\n.',
                        '%WLDNSF No such files as other.tmp\r\n.'):
            machine = self.machine(listing=listing)
            with self.subTest(listing=listing), self.assertRaises(RuntimeError):
                terminal_config.protect_bridge_terminals(machine)
            machine.copy_text.assert_not_called()
            self.assertFalse(any('copy sys:tty.ini=tty:' in call.args[0]
                                 for call in machine.child.send.call_args_list))
