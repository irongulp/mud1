import json
from pathlib import Path
import tempfile
import unittest

from tools.persona_protocol import LogicalRecord, pack_name, WORD_MASK
from tools.persona_snapshot import NativeSnapshot, MigrationError, read_snapshot, write_snapshot, parse_native_dump


def image(names=('fred', 'alice')):
    words = [0] * (256 + 12 * len(names))
    words[255] = len(words)
    for index, name in enumerate(names):
        key = pack_name(name)
        bucket = ((sum(key) & WORD_MASK) >> 1) % 253
        offset = 256 + 12 * index
        record = [words[bucket], (0o2653 << 18) | 7, key[0] | 1, key[1], WORD_MASK,
                  WORD_MASK, 123, (1 << 35) | 255, 0o123456765432, WORD_MASK, 1 << 35, 99]
        words[offset:offset+12] = record
        words[bucket] = offset
    return words


class NativeSnapshotTests(unittest.TestCase):
    def test_all_logical_bits_preserved_and_private_repr(self):
        words = image()
        snapshot = NativeSnapshot(words)
        self.assertEqual(snapshot.records[pack_name('fred')], LogicalRecord(words[257:268]))
        self.assertNotIn(str(words[264]), repr(snapshot))
        self.assertEqual(snapshot.report()['personas'], 2)

    def test_deleted_slot_is_validated_but_not_imported(self):
        words = image(('fred',))
        words[254] = 256
        words[((sum(pack_name('fred')) & WORD_MASK) >> 1) % 253] = 0
        words[256] = 0; words[257] &= ~((1 << 18)-1); words[258] = words[259] = 0
        snapshot = NativeSnapshot(words)
        self.assertFalse(snapshot.records)
        self.assertEqual(snapshot.report()['deleted_slots'], 1)

    def test_empty_native_header(self):
        self.assertFalse(NativeSnapshot([0] * 256).records)

    def test_corrupt_images_are_rejected_without_dumping_words(self):
        cases = []
        words = image(); words[255] -= 1; cases.append(words)
        words = image(); words[256] = 256; cases.append(words)
        words = image(); words[254] = 257; cases.append(words)
        words = image(); words[254] = 256; cases.append(words)
        words = image(); words[264] = WORD_MASK + 1; cases.append(words)
        words = image(); words[264] = True; cases.append(words)
        words = image(); words[((sum(pack_name('fred')) & WORD_MASK) >> 1) % 253] = 0; cases.append(words)
        words = image(('fred', 'fred')); cases.append(words)
        words = image(); key_bucket = ((sum(pack_name('fred')) & WORD_MASK) >> 1) % 253
        words[(key_bucket+1) % 253] = words[key_bucket]; words[key_bucket] = 0; cases.append(words)
        for words in cases:
            with self.subTest(case=cases.index(words)), self.assertRaises(MigrationError): NativeSnapshot(words)

    def test_archive_is_private_nonoverwriting_and_checksummed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'native.json'
            snapshot = NativeSnapshot(image())
            write_snapshot(path, snapshot)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(read_snapshot(path).words, snapshot.words)
            with self.assertRaises(FileExistsError): write_snapshot(path, snapshot)
            data = json.loads(path.read_text()); data['words'][264] ^= 1
            path.write_text(json.dumps(data))
            with self.assertRaises(MigrationError): read_snapshot(path)

    def test_native_stream_requires_complete_order_and_checksum(self):
        words = image(('fred',))
        check = 0
        for word in words: check ^= word
        lines = ['NS1 BEGIN ' + str(len(words))]
        for offset in range(0, len(words), 4):
            lines.append('NS1 DATA ' + str(offset) + ' ' + ' '.join(f'{word:o}' for word in words[offset:offset+4]))
        lines.append(f'NS1 END {len(words)} {check:o}')
        stream = '\r\n'.join(lines)
        self.assertEqual(parse_native_dump(stream).words, tuple(words))
        for invalid in ('\r\n'.join(lines[:-1]), stream.replace('DATA 4 ', 'DATA 0 '),
                        stream + '\r\nNS1 DATA 0 0', stream.replace(f'END {len(words)} {check:o}', f'END {len(words)} 0')):
            with self.assertRaises(MigrationError): parse_native_dump(invalid)
