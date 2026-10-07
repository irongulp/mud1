import unittest
from unittest.mock import patch

from tools.persona_bootstrap import BOOT_MARKER, SeedIssuer, examined_word


class Monitor:
    def __init__(self, marker=BOOT_MARKER):
        self.words = {0o140: marker, 0o141: 0, 0o142: 0}
        self.seeds = []

    def command(self, text, marker=None):
        args = text.split()
        if args[0] == 'examine':
            address = int(args[1], 8)
            word = self.words[address]
            return f'{address:o}/\t{word >> 18:o} {word & 0o777777:o}\t\r\n.'
        if args[0].isdigit():
            self.seeds.append(int(args[0], 8))
            return 'ROSEED SET\r\n.'
        return '\r\n.'


class BootstrapTests(unittest.TestCase):
    def test_wrong_image_and_stale_image_are_never_modified(self):
        for monitor in (Monitor(0), Monitor()):
            if monitor.words[0o140]:
                monitor.words[0o141] = 1
            with self.assertRaises(ValueError):
                SeedIssuer().load(monitor)
            self.assertFalse(monitor.seeds)

    def test_full_72_bits_provisioned_only_after_image_validation(self):
        monitor = Monitor()
        seed = (1 << 72) - 1
        with patch('tools.persona_bootstrap.new_token', return_value=seed):
            self.assertEqual(SeedIssuer().load(monitor), seed)
        self.assertEqual(monitor.words[0o141], 0)
        self.assertEqual(monitor.words[0o142], 0)
        self.assertEqual(monitor.seeds, [seed])

    def test_ambiguous_monitor_output_is_rejected(self):
        with self.assertRaises(ValueError):
            examined_word('141/ 0 0\n141/ 1 1', 0o141)
