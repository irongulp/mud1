from pathlib import Path
import tempfile
import unittest

from tools.prepare import prepare, normalize
from tests.test_prepare_exit import routine

ROOT = Path(__file__).resolve().parents[1]


class DeathPreparationTests(unittest.TestCase):
    def test_native_policy_and_return_only_delete(self):
        original = normalize((ROOT / 'source/MUDLIB.BCL').read_bytes()).decode()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'death'
            report = prepare(ROOT / 'source', ROOT / 'upstream/mud1', output, external_death_existing=True)
            self.assertEqual(report['persona_storage'], 'external-death-existing')
            library = (output / 'MUDLIB.BCL').read_text()
            native = routine(original, 'writeprofile', 'load.block')
            external = routine(library, 'writeprofile', 'load.block')
            predicate = native.split('\ttest (ATTED', 1)[1].split('then\t//hmm...', 1)[0]
            self.assertEqual(predicate, external.split('\ttest (ATTED', 1)[1].split('then\t//hmm...', 1)[0])
            self.assertIn('STAMINA of profile le 0 then\n         deleterec(profile+14)', external)
            self.assertIn('xw.exitsave()', external)
            helper = library.split('and xd.delete(', 1)[1].split('/* rda,', 1)[0]
            for forbidden in ('error(', 'quit(', 'dumpersona(', 'SCRE of rec', 'for attempt'):
                self.assertNotIn(forbidden, helper)
            self.assertIn('W1 DSTART ', library)
            self.assertIn('W1 DELETE ', helper)
            self.assertIn('save.pending_true', helper)
            self.assertIn('xw.resolve()', helper)
            self.assertIn('PURGE unavailable', (output / 'MUD7.BCL').read_text())

    def test_modes_exclusive(self):
        for flag in ('external_readonly', 'external_save_existing', 'external_exit_existing'):
            with tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
                prepare(ROOT / 'source', ROOT / 'upstream/mud1', Path(directory) / 'bad',
                        external_death_existing=True, **{flag: True})
