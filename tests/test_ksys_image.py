"""Offline layout qualification: no guest or historical binaries required."""
import struct
import unittest

from tests import ksys_image as image


PAGE = 512
HALF = (1 << 18) - 1
MASK = (1 << 36) - 1


def executable(memory):
    pages = (len(memory) + PAGE - 1) // PAGE
    header = [(0o1776 << 18) | 3, (1 << 33) | 1,
              ((pages - 1) << 27), (0o1777 << 18) | 1]
    return header + [0] * (PAGE - len(header)) + memory + [0] * (-len(memory) % PAGE)


class ImageTests(unittest.TestCase):
    def test_backup_character_encoding_preserves_every_bit(self):
        # t10backup pars_5chars: four 7-bit chars, then 7 bits plus bit35.
        words = [0, MASK] + [1 << bit for bit in range(36)]
        raw = b''.join(bytes([(w >> 29) & 127, (w >> 22) & 127,
                              (w >> 15) & 127, (w >> 8) & 127,
                              ((w >> 1) & 127) | ((w & 1) << 7)]) for w in words)
        self.assertEqual(image.backup_words(raw), words)
        for invalid in (raw[:-1], b'\x80\0\0\0\0'):
            with self.assertRaises(ValueError):
                image.backup_words(invalid)

    def test_exe_pages_use_directory_instead_of_assuming_one_page_offset(self):
        words = [(0o1776 << 18) | 5, 2, 3, 0, (1 << 27) | 7,
                 (0o1775 << 18) | 3, 0, 3 * PAGE]
        words += [0] * (3 * PAGE - len(words))
        words[2 * PAGE:] = [0o123456701234] * PAGE
        memory = image.load_exe(words)
        self.assertEqual(memory[3 * PAGE], 0o123456701234)
        self.assertEqual(memory[8 * PAGE + PAGE - 1], 0)
        self.assertNotIn(0, memory)

    def test_exe_rejects_truncation_overlap_and_unknown_format(self):
        valid = executable([0] * PAGE)
        overlap = valid[:]
        overlap[:8] = [(0o1776 << 18) | 5, 1, 0, 1, 0,
                       (0o1777 << 18) | 1, 0, 0]
        for words in (valid[:-1], [0], [(0o1776 << 18) | 2, 1],
                      [(0o1773 << 18) | 1], overlap,
                      executable([MASK + 1])):
            with self.subTest(words=words[:8]), self.assertRaises(ValueError):
                image.load_exe(words)

    def test_radix50_known_native_symbol_and_invalid_code(self):
        # Witnessed first .JBSYM entry, including GLOBAL flag.
        self.assertEqual(image.symbol_name(0o040400617555), 'PAT..')
        # Highest name code remains separate from suppressed-local flags.
        self.assertEqual(image.symbol_name(0o500000000000 | 40**6 - 1), '%%%%%%')
        with self.assertRaises(ValueError):
            image.symbol_name(40**6)

    def test_symbol_pointer_and_flags_keep_values_distinct(self):
        memory = {0o116: ((-4 & HALF) << 18) | 0o200,
                  0o200: 0o040400617555, 0o201: 0o25707,
                  0o202: 0o000400617555, 0o203: 0o777774025707}
        symbols = image.symbols(memory)
        self.assertEqual(image.unique_symbol(symbols, 'PAT..', flags=1), 0o25707)
        self.assertEqual(len(symbols), 2)
        with self.assertRaises(ValueError):
            image.unique_symbol(symbols, 'MISSING', flags=1)
        with self.assertRaises(ValueError):
            image.unique_symbol(symbols + symbols, 'PAT..', flags=1)

    def test_missing_odd_or_unmapped_symbol_table_is_not_empty_success(self):
        for memory in ({}, {0o116: 0},
                       {0o116: ((-3 & HALF) << 18) | 0o200},
                       {0o116: ((-2 & HALF) << 18) | 0o200},
                       {0o116: (2 << 18) | 0o200}):
            with self.subTest(memory=memory), self.assertRaises(ValueError):
                image.symbols(memory)

    def test_full_aligned_matches_do_not_select_one_installed_copy(self):
        words = executable([MASK, 0o123456700001])
        raw = struct.pack('<%dQ' % len(words), *words)
        disk = bytes(1024) + raw + bytes(1024) + raw
        self.assertEqual(image.disk_matches(disk, words), [1024, 2048 + len(raw)])
        self.assertEqual(image.disk_matches(b'X' + raw, words), [])
        corrupt = raw[:-1] + b'\xff'
        self.assertEqual(image.disk_matches(corrupt, words), [])
        with self.assertRaises(ValueError):
            image.disk_matches(disk, [])


if __name__ == '__main__':
    unittest.main()
