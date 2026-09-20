import hashlib
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from tools.deploy import application_release, install_image
from tools.fetch_licences import SHA256, XTERM_SOURCE
from tools.licensing import notice_bundle, write_runtime_archive

ROOT = Path(__file__).resolve().parents[1]


class LicensingTests(unittest.TestCase):
    def test_bundle_retains_verbatim_licence_text_and_unresolved_status(self):
        text = notice_bundle(ROOT).decode('utf-8')
        self.assertIn((ROOT / 'COPYING').read_text(), text)
        self.assertEqual(hashlib.sha256((ROOT / 'COPYING').read_bytes()).hexdigest(), SHA256)
        self.assertIn('Roy Trubshaw & Richard Bartle', text)
        self.assertIn('exclusively for not for profit use', text)
        self.assertIn('solely for personal, non-commercial uses', text)
        self.assertIn('HISTORICAL RUNTIME REVIEW IS INCOMPLETE', text)
        self.assertIn('BCPL', text)
        self.assertIn('additional restrictions', text)

    def test_missing_notices_fail_instead_of_silently_packaging(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError):
                notice_bundle(Path(directory))

    def test_xterm_preferred_form_source_is_bundled_with_build_files(self):
        name, _, digest = XTERM_SOURCE
        archive = ROOT / name
        self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), digest)
        with tarfile.open(archive) as bundle:
            names = [member.name for member in bundle]
        self.assertTrue(any(name.endswith('/src/browser/Terminal.ts') for name in names))
        self.assertTrue(any(name.endswith('/package.json') for name in names))
        self.assertTrue(any(name.endswith('/yarn.lock') for name in names))

    def test_format_two_installs_verified_notices_and_preserves_mutable_disk(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = {}
            for name, data in (('guest.dsk', b'fake disk'), ('t10boot.tap', b'fake tape')):
                inputs[name] = root / name
                inputs[name].write_bytes(data)
            archive = root / 'runtime.tar.gz'
            members = write_runtime_archive(archive, inputs, ROOT)
            self.assertEqual(set(members), {'guest.dsk', 't10boot.tap', 'NOTICES.txt'})
            with tarfile.open(archive) as bundle:
                self.assertEqual(bundle.extractfile('NOTICES.txt').read(), notice_bundle(ROOT))
            manifest = {'version': 2, 'availability': 'always-open', 'files': members,
                        'archive': {'sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}}
            target = root / 'game'
            self.assertTrue(install_image(archive, manifest, target))
            self.assertEqual((target / 'NOTICES.txt').read_bytes(), notice_bundle(ROOT))
            (target / 'guest.dsk').write_bytes(b'saved players')
            self.assertFalse(install_image(None, manifest, target))
            self.assertEqual((target / 'guest.dsk').read_bytes(), b'saved players')
            manifest['files']['NOTICES.txt']['sha256'] = '0' * 64
            with self.assertRaises(ValueError):
                install_image(archive, manifest, root / 'bad-game')
            self.assertFalse((root / 'bad-game').exists())

    def test_format_two_cannot_omit_notices(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = {'version': 2, 'availability': 'always-open',
                        'files': {'guest.dsk': {}, 't10boot.tap': {}}, 'archive': {'sha256': ''}}
            with self.assertRaises(ValueError):
                install_image(root / 'unused', manifest, root / 'game')

    def test_installed_application_contains_licences_and_installation_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkout = root / 'checkout'
            checkout.mkdir()
            for name in ('server', 'tools', 'web', 'deploy', 'docs', 'licenses'):
                (checkout / name).mkdir()
            names = ('README.md', 'requirements.lock', 'requirements-deploy.txt',
                     'LICENSE', 'COPYING', 'NOTICE', 'THIRD_PARTY.md', 'setup.sh')
            for name in names:
                (checkout / name).write_text(name)
            (checkout / 'licenses/MUD1-NOTICE.txt').write_text('original notice')
            with patch('tools.deploy.ROOT', checkout), patch('tools.deploy.APP', root / 'app'), patch('tools.deploy.run'):
                release = application_release()
            for name in names:
                self.assertEqual((release / name).read_text(), name)
            self.assertEqual((release / 'licenses/MUD1-NOTICE.txt').read_text(), 'original notice')


if __name__ == '__main__':
    unittest.main()
