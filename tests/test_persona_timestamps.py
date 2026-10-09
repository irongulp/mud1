import datetime as dt
import random
import unittest

from tools.persona_columns import FLAG_COLUMNS
from tools.persona_protocol import LogicalRecord, pack_name, WORD_MASK
from tools.persona_timestamps import native_datetime, datetime_native, timestamp_values, timestamp_record, TIMESTAMP_COLUMNS


def record(time=0,flags=0):
    return LogicalRecord((7,*pack_name('fred'),123,WORD_MASK,time,flags,123,9,10,11))


class PersonaTimestampTests(unittest.TestCase):
    def test_known_date_and_zero(self):
        self.assertIsNone(native_datetime(0))
        self.assertEqual(datetime_native(None),0)
        self.assertEqual(native_datetime(61301<<18),dt.datetime(2026,9,18))
        value=(61301<<18)|62002
        self.assertEqual(native_datetime(value),dt.datetime(2026,9,18,5,40,35,229492))
        self.assertEqual(datetime_native(native_datetime(value)),value)

    def test_every_fraction_and_boundary_round_trips(self):
        for fraction in range(1<<18):
            value=(61301<<18)|fraction
            self.assertEqual(datetime_native(native_datetime(value)),value)
        generator=random.Random(17)
        for value in (0,1,WORD_MASK,1<<35,*[generator.getrandbits(36) for _ in range(2000)]):
            self.assertEqual(datetime_native(native_datetime(value)),value)

    def test_timezone_normalization_and_invalid_values(self):
        utc=dt.datetime(2026,9,18,12,tzinfo=dt.timezone.utc)
        other=utc.astimezone(dt.timezone(dt.timedelta(hours=2)))
        self.assertEqual(datetime_native(utc),datetime_native(other))
        for value in (dt.datetime(1800,1,1),'2026-09-18',True):
            with self.assertRaises(ValueError): datetime_native(value)
        for value in (-1,WORD_MASK+1,True):
            with self.assertRaises(ValueError): native_datetime(value)

    def test_flags_observed_on_insert_without_altering_native_words(self):
        observation=dt.datetime(2026,10,5,12,34,56)
        original=record((61301<<18)|62002,(1<<35)|511)
        values=timestamp_values(original,observation)
        for flag in FLAG_COLUMNS:
            self.assertEqual(values[TIMESTAMP_COLUMNS.index(flag+'_at')],observation)
        self.assertEqual(timestamp_record(values),original)

    def test_unset_flags_are_null_and_invalid_state_dates_fail(self):
        values=list(timestamp_values(record(),dt.datetime(2026,10,5)))
        self.assertTrue(all(values[TIMESTAMP_COLUMNS.index(flag+'_at')] is None for flag in FLAG_COLUMNS))
        for bad in (True,1,'enabled',dt.datetime(2026,10,5,0,0,0,1)):
            changed=list(values); changed[TIMESTAMP_COLUMNS.index('invisible_at')]=bad
            with self.assertRaises(ValueError): timestamp_record(changed)
