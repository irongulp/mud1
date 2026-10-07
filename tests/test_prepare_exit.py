from pathlib import Path
import tempfile
import unittest

from tools.prepare import prepare, normalize

ROOT = Path(__file__).resolve().parents[1]


def routine(text, name, following):
    return text.split('and ' + name + '(', 1)[1].split('and ' + following + '(', 1)[0]


class ExitPreparationTests(unittest.TestCase):
    def test_exit_mode_preserves_native_policy_and_uses_teardown_safe_helpers(self):
        original = normalize((ROOT / 'source/MUDLIB.BCL').read_bytes()).decode()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'exit'
            report = prepare(ROOT / 'source', ROOT / 'upstream/mud1', output, external_exit_existing=True)
            self.assertEqual(report['persona_storage'], 'external-exit-existing')
            library = (output / 'MUDLIB.BCL').read_text()
            native = routine(original, 'writeprofile', 'load.block')
            external = routine(library, 'writeprofile', 'load.block')
            self.assertEqual(native.split('\ttest (ATTED', 1)[0], external.split('   output_tty\n   unless xw.exitready()', 1)[0])
            predicate = native.split('\ttest (ATTED', 1)[1].split('then\t//hmm...', 1)[0]
            self.assertEqual(predicate, external.split('\ttest (ATTED', 1)[1].split('then\t//hmm...', 1)[0])
            self.assertIn('STAMINA of profile le 0', external)
            self.assertIn('xw.exitsave()', external)
            self.assertNotIn('.pm', external.lower())
            self.assertNotIn('error(', external)
            helpers = library.split('and xw.exitready()', 1)[1].split('/* rda,', 1)[0]
            self.assertNotIn('error(', helpers)
            self.assertNotIn('quit(', helpers)
            self.assertIn('savescr_xw.savedscore', helpers)

    def test_modes_are_mutually_exclusive(self):
        for flag in ('external_readonly', 'external_save_existing'):
            with tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
                prepare(ROOT / 'source', ROOT / 'upstream/mud1', Path(directory) / 'bad',
                        external_exit_existing=True, **{flag: True})
