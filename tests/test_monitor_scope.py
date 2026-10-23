import hashlib
import unittest

from server.monitor_scope import (MonitorCompatibilityError, build_patch, parse_words,
                                  verify_fingerprints, bitmap_block, stack_push)


def instruction(op, ac=0, address=0, index=0):
    return (op << 27) | (ac << 23) | (index << 18) | (address & 0o777777)


class MonitorScopeTests(unittest.TestCase):
    def source(self):
        words = {address: instruction(0o255) for first, last in (
            (0o506703, 0o506744), (0o506756, 0o506763), (0o510516, 0o510522))
                 for address in range(first, last + 1)}
        words.update({
            0o506703: instruction(0o303, 0o15, 0o43),
            0o506704: instruction(0o254, address=0o506713),
            0o506705: instruction(0o260, 1, 0o351177),
            0o506716: instruction(0o254, address=0o506756),
            0o506720: instruction(0o254, address=0o510516),
            0o506743: instruction(0o260, 1, 0o506745),
            0o506744: instruction(0o254, address=0o506071),
            0o506763: instruction(0o254, address=0o506335),
            0o510522: instruction(0o254, address=0o506756),
        })
        return words

    def test_patch_cannot_escape_failure_or_break_high_segment_path(self):
        plan = build_patch(self.source(), 0o100000, 0o100)
        for caller, target in ((0o506716, 0o506756), (0o506720, 0o510516),
                               (0o510522, 0o506756), (0o506704, 0o506713)):
            self.assertEqual(plan['payload'][plan['relocations'][caller]] & 0o777777,
                             plan['relocations'][target])
        self.assertEqual(plan['payload'][plan['relocations'][0o506763]],
                         instruction(0o254, address=0o344247))
        self.assertEqual(plan['payload'][plan['relocations'][0o506743]],
                         instruction(0o260, 1, 0o506745))

    def test_only_three_original_words_and_owned_storage_are_used(self):
        plan = build_patch(self.source(), 0o100000, 0o100)
        self.assertEqual(set(plan['replacements']), {0o506703, 0o506704, 0o506705})
        self.assertEqual(len(plan['payload']), 63)
        with self.assertRaises(ValueError):
            build_patch(self.source(), 0o100000, 4)

    def test_unknown_source_layout_is_rejected(self):
        source = self.source()
        source[0o506704] = 0
        with self.assertRaises(MonitorCompatibilityError):
            build_patch(source, 0o100000, 0o100)

    def test_full_36_bit_code_fingerprint_is_checked(self):
        words = {0o100: 1 << 35, 0o101: 1}
        digest = hashlib.sha256(b''.join(words[a].to_bytes(5, 'big') for a in sorted(words))).hexdigest()
        verify_fingerprints(words, {(0o100, 0o101): digest})
        words[0o100] = 0
        with self.assertRaises(MonitorCompatibilityError):
            verify_fingerprints(words, {(0o100, 0o101): digest})

    def test_missing_or_truncated_snapshot_is_not_accepted(self):
        self.assertEqual(parse_words('20:\t000000000004\n21: thru 23: same as above.\n',
                                     0o20, 0o23), dict.fromkeys(range(0o20, 0o24), 4))
        with self.assertRaises(ValueError):
            parse_words('20:\t000000000004\n22:\t000000000000\n', 0o20, 0o22)

    def test_kernel_bitmap_and_stack_geometry(self):
        self.assertEqual(bitmap_block(0o62452, 0o62452, 0o61330), (0o61330, 1 << 35))
        self.assertEqual(bitmap_block(0o62452+36*4, 0o62452, 0o61330), (0o61331, 1 << 35))
        self.assertEqual(stack_push(0o777575017730), 0o777576017731)
        with self.assertRaises(ValueError):
            bitmap_block(0o62453, 0o62452, 0o61330)
