"""Contract tests for the proposed read-only persona transport (no database)."""
import unittest

from tools.persona_protocol import (
    GetRequest, LogicalRecord, ReadResult, ResponseDecoder, ProtocolError,
    WORD_MASK, RECORD_WORDS, pack_name, encode_get, decode_get,
    encode_result, lookup_response,
)


class PersonaProtocolTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.request = GetRequest((1 << 71) + 7, 1, pack_name('fred'))
        name = self.request.name_words
        # Offsets 1..11 of the native record; no hash/free-list pointer.
        self.record = LogicalRecord((0o2653 << 18 | 1, name[0] | 1, name[1] | 1,
                                     WORD_MASK, 1 << 35, 123, 511, WORD_MASK - 9,
                                     1, 1 << 35, WORD_MASK))

    def decoder(self, request=None):
        return ResponseDecoder(request or self.request, timeout=5, clock=lambda: self.now)

    def wire(self):
        return encode_result(self.request, ReadResult('FOUND', self.record))

    def test_name_matches_native_packed_layout(self):
        first = (4 << 29) | (ord('f') << 22) | (ord('r') << 15) | (ord('e') << 8) | (ord('d') << 1)
        self.assertEqual(pack_name('fred'), (first, 0))
        self.assertEqual(self.record.name_words, (first, 0))  # Sex/asleep are not key bits.
        for bad in ('', 'abcdefghij', 'Fred', 'fréd', 'a b'):
            with self.subTest(bad=bad), self.assertRaises(ProtocolError):
                pack_name(bad)

    def test_all_native_name_lengths_and_attach_digits(self):
        for name in ('a', 'ab', 'abc', 'abcd', 'abcde', 'abcdef', 'abcdefg', 'abcdefgh', 'abcdefghi', 'test1'):
            with self.subTest(name=name):
                request = GetRequest(1, 2, pack_name(name))
                self.assertEqual(decode_get(encode_get(request)), request)

    def test_request_is_bounded_and_uses_single_cr(self):
        wire = encode_get(self.request)
        self.assertEqual(len(wire), 71)
        self.assertTrue(wire.endswith(b'\r'))
        self.assertNotIn(b'\n', wire)
        self.assertEqual(decode_get(wire + b'\n'), self.request)

    def test_invalid_request_fields_and_versions(self):
        valid = encode_get(self.request)
        for wire in (valid.replace(b'R1', b'R2'), valid.replace(b'GET', b'PUT'),
                     valid[:-1], valid + valid, valid.replace(b'000001 ', b'000008 ', 1)):
            with self.subTest(wire=wire), self.assertRaises(ProtocolError):
                decode_get(wire)
        for epoch, request in ((0, 1), (1 << 72, 1), (1, 0), (1, WORD_MASK + 1)):
            with self.subTest(epoch=epoch, request=request), self.assertRaises(ProtocolError):
                GetRequest(epoch, request, pack_name('fred'))

    def test_noncanonical_name_padding_and_request_flags_rejected(self):
        name = pack_name('fred')
        for words in ((name[0] | 1, 0), (name[0], 2), (0, 0)):
            with self.subTest(words=words), self.assertRaises(ProtocolError):
                GetRequest(1, 1, words)

    def test_complete_record_is_atomic_and_lossless_with_fragmentation(self):
        decoder = self.decoder()
        wire = self.wire()
        for byte in wire[:-1]:
            self.assertIsNone(decoder.feed(bytes([byte])))
            self.assertIsNone(decoder.result)
        result = decoder.feed(wire[-1:])
        self.assertEqual(result, ReadResult('FOUND', self.record))
        self.assertEqual(len(result.record.words), RECORD_WORDS)
        self.assertEqual(result.record.words[-1], WORD_MASK)
        self.assertEqual(decoder.finish(), result)

    def test_crlf_output_is_supported_without_accepting_embedded_lf(self):
        self.assertEqual(self.decoder().feed(self.wire().replace(b'\r', b'\r\n')).record, self.record)
        with self.assertRaises(ProtocolError):
            self.decoder().feed(self.wire()[:10] + b'\n' + self.wire()[10:])

    def test_absence_and_failures_remain_distinct(self):
        for status in ('NOT_FOUND', 'UNAVAILABLE', 'INVALID_RECORD'):
            with self.subTest(status=status):
                result = self.decoder().feed(encode_result(self.request, ReadResult(status)))
                self.assertEqual(result.status, status)
                self.assertIsNone(result.record)

    def test_wrong_identity_on_any_frame_is_rejected(self):
        rows = self.wire().splitlines(keepends=True)
        identity = f'{self.request.epoch:024o} {self.request.sequence:012o}'.encode()
        for index in range(len(rows)):
            for replacement in (f'{self.request.epoch+1:024o} {self.request.sequence:012o}'.encode(),
                                f'{self.request.epoch:024o} {self.request.sequence+1:012o}'.encode()):
                changed = list(rows)
                changed[index] = changed[index].replace(identity, replacement)
                with self.subTest(index=index), self.assertRaises(ProtocolError):
                    self.decoder().feed(b''.join(changed))

    def test_reordered_duplicate_missing_and_extra_words_are_rejected(self):
        rows = self.wire().splitlines(keepends=True)
        for changed in (rows[:2] + rows[1:], rows[:2] + rows[3:],
                        rows[:1] + [rows[2], rows[1]] + rows[3:],
                        rows[:-1] + [rows[-2]] + rows[-1:], rows + [rows[0]]):
            with self.subTest(changed=changed), self.assertRaises(ProtocolError):
                self.decoder().feed(b''.join(changed))

    def test_bad_format_count_or_checksum_is_rejected(self):
        wire = self.wire()
        rows = wire.splitlines(keepends=True)
        for changed in (wire.replace(b' 001 013\r', b' 002 013\r'),
                        wire.replace(b' 001 013\r', b' 001 014\r'),
                        b''.join(rows[:-1]) + rows[-1][:-2] + (b'1' if rows[-1][-2:-1] != b'1' else b'0') + b'\r'):
            with self.subTest(changed=changed), self.assertRaises(ProtocolError):
                self.decoder().feed(changed)

    def test_missing_end_and_deadline_never_publish_partial_record(self):
        decoder = self.decoder()
        decoder.feed(b''.join(self.wire().splitlines(keepends=True)[:-1]))
        self.assertIsNone(decoder.result)
        with self.assertRaises(ProtocolError):
            decoder.finish()
        decoder = self.decoder()
        wire = self.wire()
        decoder.feed(wire[:10])
        self.now = 4.9
        decoder.feed(wire[10:20])
        self.now = 5.1
        with self.assertRaises(TimeoutError):
            decoder.feed(wire[20:])
        self.assertIsNone(decoder.result)

    def test_malformed_input_is_bounded_and_poisoned(self):
        decoder = self.decoder()
        with self.assertRaises(ProtocolError):
            decoder.feed(b'X' * 80)
        with self.assertRaises(ProtocolError):
            decoder.feed(self.wire())
        self.assertIsNone(decoder.result)

    def test_record_shape_range_and_name_are_validated(self):
        for words in (self.record.words[:-1], self.record.words + (0,),
                      (WORD_MASK + 1,) + self.record.words[1:], (-1,) + self.record.words[1:]):
            with self.subTest(words=words), self.assertRaises(ProtocolError):
                LogicalRecord(words)
        words = list(self.record.words)
        words[1:3] = pack_name('other')
        with self.assertRaises(ProtocolError):
            encode_result(self.request, ReadResult('FOUND', LogicalRecord(tuple(words))))

    def test_lookup_errors_never_become_absence(self):
        def unavailable(_):
            raise OSError('private backend detail must not be serialized')
        for getter, expected in ((lambda _: None, 'NOT_FOUND'), (unavailable, 'UNAVAILABLE'),
                                 (lambda _: (0,), 'INVALID_RECORD'),
                                 (lambda _: self.record.words, 'FOUND')):
            wire = lookup_response(self.request, getter)
            self.assertNotIn(b'private', wire)
            self.assertEqual(self.decoder().feed(wire).status, expected)

    def test_independent_epochs_cannot_consume_each_others_record(self):
        other = GetRequest(self.request.epoch + 1, 1, self.request.name_words)
        with self.assertRaises(ProtocolError):
            self.decoder(other).feed(self.wire())
        self.assertEqual(self.decoder(other).feed(encode_result(other, ReadResult('FOUND', self.record))).record,
                         self.record)

    def test_valid_checksum_cannot_hide_the_wrong_persona(self):
        words = list(self.record.words)
        words[1:3] = pack_name('other')
        other = LogicalRecord(words)
        request = GetRequest(self.request.epoch, self.request.sequence, other.name_words)
        # Correlation IDs and checksum are valid, but the payload identity is not.
        wire = encode_result(request, ReadResult('FOUND', other))
        decoder = self.decoder()
        with self.assertRaises(ProtocolError):
            decoder.feed(wire)
        self.assertIsNone(decoder.result)
        self.assertEqual(self.decoder().feed(lookup_response(self.request, lambda _: other)).status,
                         'INVALID_RECORD')

    def test_record_repr_does_not_dump_password_payload(self):
        self.assertNotIn(str(WORD_MASK - 9), repr(self.record))
        self.assertNotIn(str(WORD_MASK - 9), repr(ReadResult('FOUND', self.record)))
