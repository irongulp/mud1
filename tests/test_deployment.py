import hashlib
import io
import json
from pathlib import Path
import shutil
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from tools.deploy import install_image, validate_domain, nginx_config, write_backup, install_control
from server.runtime import Runtime, simulator_config


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.archive = self.root / 'runtime.tar.gz'
        self.files = {'guest.dsk': b'clean disk', 't10boot.tap': b'boot media'}

    def bundle(self, extra=None):
        with tarfile.open(self.archive, 'w:gz') as archive:
            for name, data in {**self.files, **(extra or {})}.items():
                member = tarfile.TarInfo(name)
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
        return {'version': 1, 'release': 'test', 'availability': 'always-open',
                'archive': {'sha256': hashlib.sha256(self.archive.read_bytes()).hexdigest()},
                'files': {name: {'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                          for name, data in self.files.items()}}

    def test_install_then_rerun_preserves_changed_disk(self):
        manifest = self.bundle()
        target = self.root / 'game'
        self.assertTrue(install_image(self.archive, manifest, target))
        self.assertEqual((target / 'guest.dsk').stat().st_mode & 0o777, 0o600)
        (target / 'guest.dsk').write_bytes(b'saved players')
        self.assertFalse(install_image(self.archive, manifest, target))
        self.assertEqual((target / 'guest.dsk').read_bytes(), b'saved players')

    def test_corrupt_archive_is_rejected_without_installing(self):
        manifest = self.bundle()
        self.archive.write_bytes(b'corrupt')
        with self.assertRaises(ValueError):
            install_image(self.archive, manifest, self.root / 'game')
        self.assertFalse((self.root / 'game').exists())

    def test_traversal_and_extra_members_are_rejected(self):
        for name in ('../escape', '/escape', 'private/passwords.json'):
            with self.subTest(name=name):
                manifest = self.bundle({name: b'bad'})
                with self.assertRaises(ValueError):
                    install_image(self.archive, manifest, self.root / 'game')
                self.assertFalse((self.root / 'game').exists())

    def test_existing_unrecognized_directory_is_not_overwritten(self):
        manifest = self.bundle()
        target = self.root / 'game'
        target.mkdir()
        (target / 'guest.dsk').write_bytes(b'important')
        with self.assertRaises(ValueError):
            install_image(self.archive, manifest, target)
        self.assertEqual((target / 'guest.dsk').read_bytes(), b'important')

    def test_member_hash_mismatch_is_rejected_atomically(self):
        manifest = self.bundle()
        manifest['files']['guest.dsk']['sha256'] = '0' * 64
        with self.assertRaises(ValueError):
            install_image(self.archive, manifest, self.root / 'game')
        self.assertFalse((self.root / 'game').exists())

    def test_existing_disk_symlink_is_rejected(self):
        manifest = self.bundle()
        target = self.root / 'game'
        install_image(self.archive, manifest, target)
        disk = target / 'guest.dsk'
        disk.unlink()
        disk.symlink_to(self.archive)
        with self.assertRaises(ValueError):
            install_image(self.archive, manifest, target)

    def test_backup_is_private_and_partial_archive_is_not_published(self):
        for name in ('game', 'private'):
            (self.root / name).mkdir()
            (self.root / name / 'fixture').write_text(name)
        directory = self.root / 'backups'
        archive = write_backup(self.root, directory)
        self.assertEqual(archive.stat().st_mode & 0o777, 0o600)
        with tarfile.open(archive) as backup:
            self.assertEqual(backup.extractfile('game/fixture').read(), b'game')
            self.assertEqual(backup.extractfile('private/fixture').read(), b'private')
        before = set(directory.iterdir())
        with patch('tools.deploy.tarfile.TarFile.add', side_effect=OSError('interrupted')):
            with self.assertRaises(OSError):
                write_backup(self.root, directory)
        self.assertEqual(set(directory.iterdir()), before)

    def test_domain_cannot_inject_proxy_or_shell_configuration(self):
        self.assertEqual(validate_domain('mud.etimbo.com'), 'mud.etimbo.com')
        for domain in ('localhost', '*.example.com', 'mud.example.com; reboot',
                       'mud.example.com\nserver {}', '-bad.example.com', 'https://example.com'):
            with self.subTest(domain=domain), self.assertRaises(ValueError):
                validate_domain(domain)

    def test_runtime_uses_private_transport_and_original_tape_boot(self):
        text = simulator_config(self.root, 3020, False)
        self.assertIn('127.0.0.1:3020,SPEED=*8', text)
        self.assertIn('boot tu0', text)
        self.assertIn('set cpu noidle', text)
        self.assertIn('set throttle 5M', text)
        self.assertNotIn('boot rp0', text)
        with self.assertRaises(ValueError):
            simulator_config(Path('/tmp/bad\nquit'), 3020, False)

    def test_https_bootstrap_only_exposes_acme_until_certificate_exists(self):
        text = nginx_config('mud.etimbo.com', challenge_only=True)
        self.assertIn('/.well-known/acme-challenge/', text)
        self.assertIn('return 503', text)
        self.assertNotIn('proxy_pass', text)
        secure = nginx_config('mud.etimbo.com', tls=True)
        self.assertIn('listen 443 ssl', secure)
        self.assertIn('proxy_set_header Host $http_host', secure)
        self.assertIn('return 301 https://mud.etimbo.com', secure)

    def test_new_boot_invalidates_previous_clean_shutdown_marker(self):
        (self.root / 'shutdown.json').write_text('{"clean": true}')
        runtime = Runtime(self.root, '/nonexistent')
        def boot():
            runtime.stopping.set()
            self.assertFalse(json.loads((self.root / 'shutdown.json').read_text())['clean'])
            raise InterruptedError()
        with patch.object(runtime, 'boot', side_effect=boot), patch('server.runtime.signal.signal'):
            with self.assertRaises(InterruptedError):
                runtime.run()

    def test_control_is_found_without_usr_local_bin_and_survives_rerun(self):
        control = self.root / 'usr/local/bin/mud86ctl'
        alias = self.root / 'usr/bin/mud86ctl'
        for _ in range(2):
            install_control(control, alias)
            self.assertEqual(shutil.which('mud86ctl', path=str(alias.parent)), str(alias))
            self.assertEqual(alias.resolve(), control.resolve())
            self.assertEqual(control.stat().st_mode & 0o777, 0o755)
            self.assertIn('/opt/mud86/current/tools/deploy.py "$@"', control.read_text())

    def test_control_install_preserves_unrelated_existing_command(self):
        control = self.root / 'usr/local/bin/mud86ctl'
        alias = self.root / 'usr/bin/mud86ctl'
        alias.parent.mkdir(parents=True)
        alias.write_text('existing command')
        with self.assertRaises(FileExistsError):
            install_control(control, alias)
        self.assertEqual(alias.read_text(), 'existing command')
        self.assertFalse(control.exists())


if __name__ == '__main__':
    unittest.main()
