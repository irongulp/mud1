import asyncio
import unittest

from server.external_bootstrap import ExternalBootstrap
from tools.persona_bootstrap import BOOT_MARKER


class Terminal:
    def __init__(self, marker=BOOT_MARKER):
        self.marker = marker
        self.commands = []
        self.next = b''
        self.initial = b'By what name shall I call you?'
    def write(self, command):
        self.commands.append(command)
        if command.startswith('examine '):
            address = int(command.split()[1], 8)
            word = self.marker if address == 0o140 else 0
            self.next = f'{address:06o}/ {word >> 18:06o} {word & ((1<<18)-1):06o}   .'.encode()
        elif command.startswith('run dskb:roseed'): self.next = b'ROSEED READY\r\n'
        elif command.strip() == 'start': self.next = b'Welcome! By what name shall I call you?'
        elif len(command.strip()) == 24: self.next = b'ROSEED SET\r\n.'
        else: self.next = b'\r\n.'
    async def readuntil(self, marker):
        if marker == b'By what name shall I call you?' and not self.commands:
            return b'By what name shall I call you?'
        self.assert_marker(marker)
        return self.next
    async def read(self, count):
        if not self.commands:
            value,self.initial=self.initial[:count],self.initial[count:]
        else:
            value,self.next=self.next[:count],self.next[count:]
        return value.decode('ascii')
    def assert_marker(self, marker):
        if not self.next.endswith(marker): raise AssertionError('Unexpected bootstrap sequence')


class ExternalBootstrapTests(unittest.IsolatedAsyncioTestCase):
    async def test_private_seed_provisioned_and_only_new_intro_returned(self):
        bootstrap = ExternalBootstrap(token_factory=iter((1 << 36, (1 << 36) + 1)).__next__)
        first, second = Terminal(), Terminal()
        self.assertIn(b'By what name', await bootstrap(first, first))
        await bootstrap(second, second)
        self.assertIn(f'{1<<36:024o}\r', first.commands)
        self.assertIn(f'{(1<<36)+1:024o}\r', second.commands)
        self.assertEqual(first.commands[-2:], ['examine 140\r', 'start\r'])
    async def test_wrong_image_never_receives_seed(self):
        terminal = Terminal(marker=0)
        with self.assertRaises(OSError): await ExternalBootstrap()(terminal, terminal)
        self.assertFalse(any('roseed' in command for command in terminal.commands))
    async def test_session_deadline_bounds_silent_monitor(self):
        class Silent(Terminal):
            async def readuntil(self, marker): await asyncio.sleep(10)
            async def read(self, count): await asyncio.sleep(10)
        with self.assertRaises(asyncio.TimeoutError):
            await ExternalBootstrap(timeout=0.01)(Silent(), Silent())

    async def test_closed_game_at_monitor_fails_immediately(self):
        terminal=Terminal()
        terminal.initial=b"MUD isn't available at the moment. Try again tomorrow?\r\n\r\n."
        with self.assertRaises(OSError): await ExternalBootstrap()(terminal,terminal)
        self.assertFalse(terminal.commands)
