import random
import unittest
from tools.persona_protocol import LogicalRecord, pack_name, WORD_MASK
from tools.persona_columns import ColumnPersona, DATA_COLUMNS


class PersonaColumnTests(unittest.TestCase):
    def test_named_fields_and_signed_score(self):
        record = LogicalRecord(((0o2776 << 18) | 7, pack_name('fred')[0] | 1, 1,
                                WORD_MASK, (75 << 27) | (61 << 18) | (40 << 9) | 80,
                                (123 << 18) | 456, (1 << 35) | 289, 123, 99, 88, 77))
        fields = ColumnPersona.from_record(record)
        self.assertEqual((fields.name, fields.sex, fields.asleep, fields.games_played), ('fred', 'female', True, 7))
        self.assertEqual((fields.score, fields.strength, fields.stamina), (-1, 75, 40))
        self.assertTrue(fields.wizard_mode and fields.brief and fields.wizard_eligible)
        self.assertEqual(fields.unknown_state_bits, 1 << 35)
        self.assertEqual(fields.to_record(), record)
        self.assertNotIn('password_word=123', repr(fields))

    def test_every_bit_and_random_values_round_trip(self):
        generator = random.Random(83)
        for name in ('a', 'fred', 'abcde', 'abcdefghi', 'abc123'):
            for attempt in range(72):
                words = [generator.getrandbits(36) for _ in range(11)]
                words[1:3] = pack_name(name)
                words[1] |= attempt & 1; words[2] |= (attempt >> 1) & 1
                words[attempt % 11] = 1 << (attempt % 36) if attempt % 11 not in (1, 2) else words[attempt % 11]
                record = LogicalRecord(words)
                fields = ColumnPersona.from_record(record)
                self.assertEqual(ColumnPersona.from_values(fields.values()).to_record(), record)
                self.assertEqual(len(fields.values()), len(DATA_COLUMNS))

    def test_invalid_column_values_fail_without_truncation(self):
        original = ColumnPersona.from_record(LogicalRecord((0, *pack_name('fred'), 0, 0, 0, 0, 123, 0, 0, 0))).values()
        for field, invalid in (('name','Fred'), ('score',1 << 35), ('score',-(1<<35)-1),
                               ('strength',512), ('games_played',1<<18), ('sex','other'),
                               ('wizard_mode',2), ('unknown_state_bits',1), ('password_word',1<<36),
                               ('opaque_9',None), ('native_day_fraction',1<<18)):
            values = list(original); values[DATA_COLUMNS.index(field)] = invalid
            with self.subTest(field=field), self.assertRaises(ValueError): ColumnPersona.from_values(values)

    def test_sql_edit_maps_back_to_original_record(self):
        fields = ColumnPersona.from_record(LogicalRecord((0, *pack_name('fred'), 0, 0, 0, 0, 123, 0, 0, 0)))
        values = list(fields.values())
        values[DATA_COLUMNS.index('score')] = 1500
        values[DATA_COLUMNS.index('strength')] = 80
        changed = ColumnPersona.from_values(values).to_record()
        self.assertEqual(changed.words[3], 1500)
        self.assertEqual(changed.words[4] >> 27, 80)
        self.assertEqual(changed.words[7], 123)
