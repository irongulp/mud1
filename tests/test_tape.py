import io
import struct
import unittest

from tools.source_tape import pack_text, write_record, write_tape


class TapeTests(unittest.TestCase):
    def test_seven_bit_characters_are_packed_in_36_bit_words(self):
        # Five 7-bit characters occupy bits 35..1; bit 0 is zero.
        word = (65 << 29) | (66 << 22) | (67 << 15) | (68 << 8) | (69 << 1)
        self.assertEqual(pack_text(b"ABCDE"), (word >> 4).to_bytes(4, "big") + bytes([word & 15]))
        with self.assertRaises(ValueError):
            pack_text(b"\xff")

    def test_simh_record_framing_and_odd_byte_padding(self):
        output = io.BytesIO()
        write_record(output, b"abc")
        self.assertEqual(output.getvalue(), struct.pack("<I", 3) + b"abc\0" + struct.pack("<I", 3))

    def test_files_are_separated_by_tape_marks_and_text_uses_crlf(self):
        output = io.BytesIO()
        write_tape(output, [b"A\n", b"B\r\n"])
        data = output.getvalue()
        length = struct.unpack("<I", data[:4])[0]
        self.assertEqual(data[4:9], pack_text(b"A\r\n"))
        self.assertEqual(data[8 + length:12 + length], b"\0" * 4)
        self.assertTrue(data.endswith(b"\0" * 8))


if __name__ == "__main__":
    unittest.main()
