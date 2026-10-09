from pathlib import Path
import tempfile
import unittest
from tools.prepare import prepare, normalize

ROOT = Path(__file__).resolve().parents[1]


class AdminPreparationTests(unittest.TestCase):
    def test_password_policy_and_purge_menu_remain_bcpl(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'admin'
            report = prepare(ROOT / 'source', ROOT / 'upstream/mud1', output, external_admin=True)
            self.assertEqual(report['persona_storage'], 'external-admin')
            five, seven = (output / 'MUD5.BCL').read_text(), (output / 'MUD7.BCL').read_text()
            original = normalize((ROOT / 'source/MUD5.BCL').read_bytes()).decode()
            password = original.split('\t\t$(\tlet opret, one, two=pretend, ?, ?\n', 1)[1].split('\t\tcase SF.HOURS:', 1)[0]
            self.assertIn(password, five)
            self.assertNotIn('PASSWORD unavailable', five)
            self.assertNotIn('PURGE unavailable', seven)
            for policy in ('if fight!player.no', 'if us(me) psw_PSWD of rec', 'if PSWD of rec=psw/\\WRD1 of rec',
                           'unless WIZARD of profile resultis true', 'Save, delete or finish?'):
                self.assertIn(policy, seven)
            purge = seven.split('and purge()', 1)[1].split('and bug()', 1)[0]
            self.assertNotIn('dofile(', purge)
            self.assertNotIn('load.block', purge)
            self.assertIn('purge.act(selected)', purge)
            self.assertIn('purge.pending', five)

    def test_other_modes_still_gate_admin(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'creation'
            prepare(ROOT / 'source', ROOT / 'upstream/mud1', output, external_creation=True)
            self.assertIn('PASSWORD unavailable', (output / 'MUD5.BCL').read_text())
            self.assertIn('PURGE unavailable', (output / 'MUD7.BCL').read_text())

    def test_admin_mode_is_mutually_exclusive(self):
        for flag in ('external_readonly', 'external_save_existing', 'external_exit_existing',
                     'external_death_existing', 'external_creation'):
            with tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
                prepare(ROOT / 'source', ROOT / 'upstream/mud1', Path(directory) / 'bad',
                        external_admin=True, **{flag: True})
