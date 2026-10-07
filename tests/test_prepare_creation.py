from pathlib import Path
import tempfile
import unittest

from tools.prepare import prepare

ROOT = Path(__file__).resolve().parents[1]


class CreationPreparationTests(unittest.TestCase):
    def test_opt_in_creation_preserves_native_character_and_serialization(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'create'
            report = prepare(ROOT / 'source', ROOT / 'upstream/mud1', output, external_creation=True)
            self.assertEqual(report['persona_storage'], 'external-creation')
            library = (output / 'MUDLIB.BCL').read_text()
            self.assertIn('xc.register(name)', library)
            self.assertIn('W1 CSTART ', library)
            self.assertIn('checksum,creating=?,xc.fresh(nam)', library)
            self.assertIn('xc.saved(xw.name)', library)
            self.assertIn('unless creating \\/ SCRE of rec ge savescr', library)
            self.assertIn('dumpersona(rec)', library)
            self.assertIn('STRENGTH of profile\t_\tcrechar()', library)
            self.assertNotIn('creation is unavailable in this read-only build', library)
            self.assertIn('PASSWORD unavailable', (output / 'MUD5.BCL').read_text())
            self.assertIn('PURGE unavailable', (output / 'MUD7.BCL').read_text())
            self.assertIn('searchrec(objname)=2', (output / 'MUD7.BCL').read_text())

    def test_modes_exclusive(self):
        for flag in ('external_readonly', 'external_save_existing', 'external_exit_existing', 'external_death_existing'):
            with tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
                prepare(ROOT / 'source', ROOT / 'upstream/mud1', Path(directory) / 'bad',
                        external_creation=True, **{flag: True})
