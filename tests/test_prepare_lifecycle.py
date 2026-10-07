from pathlib import Path
import tempfile
import unittest
from tools.prepare import prepare

ROOT = Path(__file__).resolve().parents[1]


class LifecyclePreparationTests(unittest.TestCase):
    def test_shared_creation_and_lifetime_checks_are_opt_in(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'life'
            report = prepare(ROOT / 'source', ROOT / 'upstream/mud1', output, external_lifecycle=True)
            self.assertEqual(report['persona_storage'], 'external-lifecycle')
            library = (output / 'MUDLIB.BCL').read_text()
            self.assertNotIn('xc.names', library)
            self.assertIn('life.prepare(nam)', library)
            self.assertIn('life.init()', library)
            self.assertIn('life.select()', (output / 'MUD7.BCL').read_text())
            self.assertIn('life.current()', (output / 'MUD3.BCL').read_text())
            self.assertIn('XLTABL::', (output / 'XLSTATE.MAC').read_text())
            self.assertIn('xw.resolve()', library.split('and life.prepare(', 1)[1])

    def test_native_remains_free_of_lifetime_adapter(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'native'
            prepare(ROOT / 'source', ROOT / 'upstream/mud1', output, always_open=True)
            self.assertFalse((output / 'XLSTATE.MAC').exists())
            self.assertNotIn('life.current()', (output / 'MUD3.BCL').read_text())

    def test_chaining_requires_explicit_compatible_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'chain'
            report = prepare(ROOT / 'source', ROOT / 'upstream/mud1', output,
                             external_lifecycle=True, chain_targets=('mud', 'valley'))
            library = (output / 'MUDLIB.BCL').read_text()
            seven = (output / 'MUD7.BCL').read_text()
            self.assertEqual(report['chain_targets'], ['mud', 'valley'])
            self.assertIn('chain.in()', library)
            self.assertIn('chain.out(nextgame,nextrm,logs)', seven)
            self.assertIn('chain.ready_false', seven)
            self.assertIn('Chained persona is missing', library)
            self.assertNotIn('chain_findtmp', library)
            self.assertIn('xr.calls_data!10', library)
            self.assertIn('data!1=mud6', library)

    def test_unsafe_or_wrong_mode_chain_configuration_rejected(self):
        for options in ({'chain_targets': ('mud',)},
                        {'external_lifecycle': True, 'chain_targets': ('../mud',)}):
            with tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
                prepare(ROOT / 'source', ROOT / 'upstream/mud1', Path(directory) / 'bad', **options)
