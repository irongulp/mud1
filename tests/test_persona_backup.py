import json
from pathlib import Path
import tempfile
import sys
import unittest
import zipfile

from tools.persona_backup import read_bundle, write_bundle, MigrationError, capture_dump


class BackupBundleTests(unittest.TestCase):
    def test_private_atomic_bundle_and_tamper_detection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sql = root / 'dump.sql'; sql.write_bytes(b'SELECT 1;\n')
            archive = root / 'backup.zip'
            state = {'objects': {}, 'settings': ['ascii', 'ascii_bin'], 'tables': {}}
            write_bundle(archive, sql, {'database': 'mud', 'snapshot': state, 'restored': state})
            self.assertEqual(archive.stat().st_mode & 0o777, 0o600)
            with read_bundle(archive) as (manifest, extracted):
                self.assertEqual(extracted.read_bytes(), sql.read_bytes())
                self.assertEqual(manifest['database'], 'mud')
            with self.assertRaises(FileExistsError): write_bundle(archive, sql, {})
            with zipfile.ZipFile(archive) as source: manifest = source.read('manifest.json')
            with zipfile.ZipFile(archive, 'w') as changed:
                changed.writestr('manifest.json', manifest)
                changed.writestr('database.sql', 'SELECT 2;\n')
            with self.assertRaises(MigrationError), read_bundle(archive): pass

    def test_missing_verification_metadata_is_not_a_valid_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sql = root / 'input.sql'; sql.write_text('SELECT 1;')
            archive = root / 'bad.zip'
            write_bundle(archive, sql, {'database': 'mud', 'snapshot': {}, 'restored': {}})
            with self.assertRaises(MigrationError), read_bundle(archive): pass

    def test_extra_or_duplicate_archive_members_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / 'bad.zip'
            with zipfile.ZipFile(archive, 'w') as output:
                output.writestr('../outside.sql', 'bad')
            archive.chmod(0o600)
            with self.assertRaises(MigrationError), read_bundle(archive): pass

    def test_dump_process_is_bounded_and_failure_removes_partial_file(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'dump.sql'
            for program in ("import time; time.sleep(10)",
                            "import sys; sys.stdout.write('x'*4096)",
                            "import sys; print('partial'); sys.exit(2)"):
                with self.assertRaises(MigrationError):
                    capture_dump([sys.executable, '-c', program], target, timeout=0.2, limit=128)
                self.assertFalse(target.exists())
            capture_dump([sys.executable, '-c', "print('complete')"], target, timeout=2, limit=128)
            self.assertEqual(target.read_bytes(), b'complete\n')
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
