import hashlib
from pathlib import Path
import tempfile
import unittest

from tools.prepare import prepare, normalize

ROOT = Path(__file__).resolve().parents[1]


class ReadOnlyPreparationTests(unittest.TestCase):
    def test_existing_save_mode_keeps_native_policy_and_other_gates(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'writes'
            report = prepare(ROOT / 'source', ROOT / 'upstream/mud1', output, external_save_existing=True)
            self.assertEqual(report['persona_storage'], 'external-save-existing')
            library = (output / 'MUDLIB.BCL').read_text()
            original = normalize((ROOT / 'source/MUDLIB.BCL').read_bytes()).decode()
            def serializer(text):
                return text.split('and dumpersona(place)', 1)[1].split('and realwiz', 1)[0]
            self.assertEqual(serializer(library), serializer(original))
            self.assertIn('unless SCRE of rec ge savescr', library)
            self.assertIn('dumpersona(rec)', library)
            self.assertIn('automatic persistence unavailable', library)
            self.assertNotIn('$6".pm"', library)
            dispatcher = (output / 'MUD5.BCL').read_text()
            self.assertNotIn('SAVE unavailable', dispatcher)
            self.assertIn('PASSWORD unavailable', dispatcher)
            self.assertIn('savescr=SCORE of profile', dispatcher)
            self.assertIn('PURGE unavailable', (output / 'MUD7.BCL').read_text())
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
            prepare(ROOT / 'source', ROOT / 'upstream/mud1', Path(directory) / 'bad',
                    external_readonly=True, external_save_existing=True)

    def test_explicit_variant_preserves_authentication_and_original_files(self):
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT / 'source').iterdir() if p.is_file()}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'readonly'
            report = prepare(ROOT / 'source', ROOT / 'upstream/mud1', output, external_readonly=True)
            self.assertEqual(report['persona_storage'], 'external-readonly')
            original = normalize((ROOT / 'source/MUDLIB.BCL').read_bytes()).decode()
            modified = (output / 'MUDLIB.BCL').read_text()
            def authentication(text):
                return text.split('\t\t\ttest PSWD of rec then', 1)[1].split('and rationalise', 1)[0].split('\t\tquitflg_1\n')[0]
            self.assertEqual(authentication(modified), authentication(original))
            self.assertNotIn('$6".pm"', modified)
            self.assertNotIn('$6".pm"', (output / 'MUD7.BCL').read_text())
            self.assertIn('findchannel()', modified.lower())
            self.assertIn('xr.started_xr.millis()', modified)
            self.assertLess(modified.index('and xr.lookup('), modified.index('/* rda, rdb, wrb,'))
            self.assertIn('Read-only external persona storage', modified)
            self.assertIn('case SF.PASSWORD:', (output / 'MUD5.BCL').read_text())
            self.assertIn('ROMAGC', (output / 'ROBOOT.MAC').read_text())
            self.assertIn('ROBOOT.MAC', (output / 'local.diff').read_text())
        self.assertEqual(before, {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT / 'source').iterdir() if p.is_file()})

    def test_default_native_mode_does_not_include_adapter(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'native'
            report = prepare(ROOT / 'source', ROOT / 'upstream/mud1', output)
            self.assertEqual(report['persona_storage'], 'native')
            self.assertEqual((output / 'MUDLIB.BCL').read_bytes(), normalize((ROOT / 'source/MUDLIB.BCL').read_bytes()))
            self.assertFalse((output / 'ROBOOT.MAC').exists())

    def test_unknown_source_fails_before_publishing_variant(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source'
            source.mkdir()
            for name in ('MUD.TXT', 'MUDLIB.BCL', 'MUD5.BCL', 'MUD7.BCL'):
                (source / name).write_text('*rooms 0\n' if name == 'MUD.TXT' else 'unexpected\n')
            with self.assertRaises(ValueError):
                prepare(source, ROOT / 'upstream/mud1', root / 'output', external_readonly=True)
            self.assertFalse((root / 'output').exists())
