from collections import deque
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import MagicMock

import pexpect

from server.local_guest import LocalGuest, MONITOR_PROMPT
from tools.guest_control import ControlError


class WrongEchoConsole:
    def __init__(self):
        self.pending = deque()
        self.sent = []
        self.before = self.after = ''
        self.delaybeforesend = .05

    def send(self, data):
        self.sent.append(data)
        self.pending.extend('?' if data == '=' else data)

    def expect(self, pattern, timeout=None):
        if not self.pending:
            raise pexpect.TIMEOUT('No scripted data')
        self.before, self.after = '', self.pending.popleft()

    def sendcontrol(self, char):
        raise AssertionError('Unverified COPY must not receive EOF')


class LocalConsoleTests(unittest.TestCase):
    def test_shutdown_accepts_a_responsive_nonempty_queue_listing(self):
        self.check_shutdown_queue_response(
            '\r\nOPR>\r\n 3:00:41 -- System Queues Listing --\r\n'
            'Printer Queue:\r\nThere is 1 job in the queue (none in progress); 200 pages\r\nOPR>', True)

    def test_shutdown_accepts_a_responsive_empty_queue_listing(self):
        self.check_shutdown_queue_response('\r\nOPR>\r\n-- The queues are empty --\r\nOPR>', True)

    def test_shutdown_does_not_treat_a_prompt_alone_as_readiness(self):
        self.check_shutdown_queue_response('\r\nOPR>', False)

    def check_shutdown_queue_response(self, queue_response, clean):
        with tempfile.TemporaryDirectory() as directory:
            guest = LocalGuest.__new__(LocalGuest)
            guest.booted, guest.stopped, guest.clean = True, False, False
            guest.failure = None
            guest.control_prompt = MONITOR_PROMPT
            guest.child = MagicMock()
            guest.child.isalive.return_value = True
            guest.child.close.side_effect = lambda **kwargs: setattr(guest.child.isalive, 'return_value', False)
            guest.emulator = MagicMock()
            guest.scope = MagicMock(verified=True, evidence=Path(directory))
            replies = {'r opr': '\r\nOPR>', 'show queues': queue_response,
                'set ksys now': '\r\nOPR>\r\nKSYS processing completed\r\nOPR>'}

            def command(text, prompt=MONITOR_PROMPT, **kwargs):
                guest.control_prompt = None
                if not re.search(prompt, replies[text]):
                    raise pexpect.TIMEOUT('Expected result absent')
                if prompt == 'OPR>':
                    guest.control_prompt = prompt
                return replies[text]

            guest.command = MagicMock(side_effect=command)
            self.assertEqual(guest.stop(), clean)
            self.assertEqual([call.args[0] for call in guest.command.call_args_list],
                             ['r opr', 'show queues']+(['set ksys now'] if clean else []))

    def test_bad_copy_header_never_submits_enter_or_payload(self):
        guest = LocalGuest.__new__(LocalGuest)
        guest.child = WrongEchoConsole()
        guest.control_prompt = MONITOR_PROMPT
        guest.failure = None
        with self.assertRaises(ControlError):
            guest.copy_text('sys:tty.ini', 'ALL KSYS TEXT FILL:0\n')
        self.assertNotIn('\r', ''.join(guest.child.sent))
        self.assertNotIn('ALL', ''.join(guest.child.sent))
        self.assertIsNone(guest.control_prompt)
        self.assertEqual(guest.failure['phase'], 'copy-header')
        self.assertFalse(guest.failure['submitted'])
        with self.assertRaises(RuntimeError):
            guest.command('r opr')
