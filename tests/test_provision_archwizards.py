import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.provision_archwizards import (
    ARCHWIZARDS, CREDENTIAL_FILE, ProvisionError, generate_password, provision,
    render_credentials, credential_journal,
)


class NativeFixture:
    """Fake native records; these numbers are not the game's password algorithm."""
    def __init__(self, directory):
        self.directory = directory
        self.personas = {}
        self.created = []
        self.fail_before_save = False

    def records(self):
        return {name: dict(record) for name, record in self.personas.items()}

    def create_and_save(self, name, password):
        journal = json.loads((self.directory / CREDENTIAL_FILE).read_text())
        assert journal['credentials'][name]['initial_password'] == password
        if self.fail_before_save:
            raise ProvisionError('Interrupted before SAVE')
        self.created.append((name, password))
        self.personas[name.lower()] = {'password_word': len(self.created), 'games': 1}


class ProvisionArchwizardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / 'private'
        self.native = NativeFixture(self.directory)

    def test_base64_generator_rejects_incompatible_alphabet(self):
        with patch('tools.provision_archwizards.secrets.token_bytes',
                   side_effect=[b'\xff' * 6, base64.b64decode('abc123xy')]):
            self.assertEqual(generate_password(), 'abc123xy')

    def test_all_seven_are_saved_with_distinct_compatible_journalled_credentials(self):
        result = provision(self.native, self.directory)
        self.assertEqual([name for name, _ in self.native.created], list(ARCHWIZARDS))
        passwords = [password for _, password in self.native.created]
        self.assertEqual(len(set(passwords)), 7)
        for password in passwords:
            self.assertRegex(password, r'^[a-z0-9]{8}$')
        self.assertTrue(all(row['status'] == 'created' for row in result))
        self.assertEqual(self.directory.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.directory / CREDENTIAL_FILE).stat().st_mode & 0o777, 0o600)

    def test_rerun_preserves_records_and_journal_without_generating_passwords(self):
        provision(self.native, self.directory)
        before = (self.directory / CREDENTIAL_FILE).read_bytes()
        records = self.native.records()
        self.native.created.clear()
        with patch('tools.provision_archwizards.generate_password', side_effect=AssertionError):
            result = provision(self.native, self.directory)
        self.assertFalse(self.native.created)
        self.assertEqual(self.native.records(), records)
        self.assertEqual((self.directory / CREDENTIAL_FILE).read_bytes(), before)
        self.assertTrue(all(row['status'] == 'preserved' for row in result))

    def test_existing_personas_are_preserved_and_changed_passwords_are_not_presented_as_current(self):
        provision(self.native, self.directory)
        initial = json.loads((self.directory / CREDENTIAL_FILE).read_text())
        old_password = initial['credentials']['Richard']['initial_password']
        self.native.personas['richard']['password_word'] = 12345
        self.native.created.clear()
        result = provision(self.native, self.directory)
        richard = next(row for row in result if row['name'] == 'Richard')
        self.assertEqual(richard['status'], 'changed')
        self.assertNotIn('password', richard)
        self.assertNotIn(old_password, render_credentials(result, reveal=True))
        self.assertFalse(self.native.created)

    def test_unknown_existing_password_is_not_overwritten(self):
        self.native.personas['richard'] = {'password_word': 321, 'games': 8}
        result = provision(self.native, self.directory)
        self.assertNotIn('Richard', [name for name, _ in self.native.created])
        self.assertEqual(result[0], {'name': 'Richard', 'status': 'existing'})
        self.assertEqual(self.native.personas['richard']['password_word'], 321)

    def test_fully_preexisting_install_keeps_an_empty_journal_and_generates_nothing(self):
        self.native.personas = {name.lower(): {'password_word': 123, 'games': 1} for name in ARCHWIZARDS}
        with patch('tools.provision_archwizards.generate_password', side_effect=AssertionError):
            result = provision(self.native, self.directory)
        self.assertTrue(all(row['status'] == 'existing' for row in result))
        self.assertEqual(json.loads((self.directory / CREDENTIAL_FILE).read_text())['credentials'], {})

    def test_duplicate_generated_password_is_retried(self):
        values = ['aaaaaa01', 'aaaaaa01'] + [f'aaaaaa0{number}' for number in range(2, 8)]
        with patch('tools.provision_archwizards.generate_password', side_effect=values):
            provision(self.native, self.directory)
        self.assertEqual(len({password for _, password in self.native.created}), 7)

    def test_existing_zero_password_fails_before_creating_anything(self):
        self.native.personas['roy'] = {'password_word': 0, 'games': 1}
        with self.assertRaisesRegex(ProvisionError, 'Roy.*no password'):
            provision(self.native, self.directory)
        self.assertFalse(self.native.created)

    def test_interrupted_unsaved_creation_reuses_its_journalled_password(self):
        self.native.fail_before_save = True
        with self.assertRaises(ProvisionError):
            provision(self.native, self.directory)
        pending = json.loads((self.directory / CREDENTIAL_FILE).read_text())
        self.native.fail_before_save = False
        provision(self.native, self.directory)
        self.assertEqual(self.native.created[0][1], pending['credentials']['Richard']['initial_password'])

    def test_ambiguous_saved_creation_requires_reconciliation_without_replacing_password(self):
        self.native.fail_before_save = True
        with self.assertRaises(ProvisionError):
            provision(self.native, self.directory)
        self.native.personas['richard'] = {'password_word': 123, 'games': 1}
        self.native.fail_before_save = False
        with self.assertRaisesRegex(ProvisionError, 'Richard.*unverified'):
            provision(self.native, self.directory)
        self.assertFalse(self.native.created)
        self.assertEqual(self.native.personas['richard']['password_word'], 123)

    def test_passwords_are_only_rendered_when_explicitly_requested(self):
        result = provision(self.native, self.directory)
        hidden = render_credentials(result)
        visible = render_credentials(result, reveal=True)
        for _, password in self.native.created:
            self.assertNotIn(password, hidden)
            self.assertIn(password, visible)
        self.assertIn('password manager', visible)
        self.assertIn('attachment', visible.lower())
        self.assertIn('SAVE', visible)
        self.assertIn('QUIT', visible)

    def test_world_readable_journal_is_rejected(self):
        provision(self.native, self.directory)
        (self.directory / CREDENTIAL_FILE).chmod(0o644)
        self.native.created.clear()
        with self.assertRaises(ProvisionError):
            provision(self.native, self.directory)
        self.assertFalse(self.native.created)

    def test_symlinked_journal_is_rejected(self):
        self.directory.mkdir(mode=0o700)
        target = Path(self.temp.name) / 'other.json'
        target.write_text('{}')
        (self.directory / CREDENTIAL_FILE).symlink_to(target)
        with self.assertRaises(ProvisionError):
            provision(self.native, self.directory)
        self.assertEqual(target.read_text(), '{}')

    def test_concurrent_journal_use_is_rejected_before_native_writes(self):
        with credential_journal(self.directory):
            with self.assertRaisesRegex(ProvisionError, 'Another provisioner'):
                provision(self.native, self.directory)
        self.assertFalse(self.native.created)

    def test_malformed_journal_is_retained_without_native_writes(self):
        self.directory.mkdir(mode=0o700)
        path = self.directory / CREDENTIAL_FILE
        path.write_text('{broken')
        path.chmod(0o600)
        with self.assertRaisesRegex(ProvisionError, 'Invalid credential journal'):
            provision(self.native, self.directory)
        self.assertEqual(path.read_text(), '{broken')
        self.assertFalse(self.native.created)


if __name__ == '__main__':
    unittest.main()
