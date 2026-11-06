import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import deploy


class DeploymentShutdownTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.app, self.state, self.config = (self.root / name for name in ('app', 'state', 'config'))
        for directory in (self.app, self.state, self.config, self.state / 'game'):
            directory.mkdir()
        self.marker = self.state / 'shutdown.json'
        for name, path in (('APP', self.app), ('STATE', self.state), ('CONFIG', self.config)):
            self.stack.enter_context(patch.object(deploy, name, path))
        self.run = self.stack.enter_context(patch.object(deploy, 'run'))

    def test_installer_does_not_activate_or_start_after_failed_stop(self):
        old, new = self.app / 'old', self.app / 'new'
        old.mkdir()
        new.mkdir()
        (self.app / 'current').symlink_to(old)
        unit = self.root / 'runtime.service'
        unit.touch()
        original_path = Path
        def path(value):
            return unit if str(value) == '/etc/systemd/system/mud86-runtime.service' else original_path(value)
        self.stack.enter_context(patch.object(deploy, 'Path', side_effect=path))
        self.stack.enter_context(patch.object(deploy, 'install_image'))
        self.stack.enter_context(patch.object(deploy, 'application_release', return_value=new))
        self.stack.enter_context(patch.object(deploy, 'build_simh', return_value=Path('/fixture/pdp10')))
        self.stack.enter_context(patch.object(deploy.shutil, 'chown'))
        self.stack.enter_context(patch.object(deploy.subprocess, 'run', return_value=Mock(returncode=0)))
        self.marker.write_text('{"clean": true}')
        def run(*command):
            if command == ('systemctl', 'stop', 'mud86-runtime.service'):
                self.marker.write_text('{"clean": false, "failure": {"phase": "ksys"}}')
        self.run.side_effect = run
        args = argparse.Namespace(domain='mud.example.org', http_only=True, image=None, persona_storage=None)
        with self.assertRaisesRegex(RuntimeError, 'shutdown was not confirmed clean'):
            deploy.install(args)
        self.assertEqual((self.app / 'current').resolve(), old.resolve())
        self.assertFalse(any(call.args[:2] == ('systemctl', 'start') for call in self.run.call_args_list))

    def test_backup_never_restarts_after_unclean_or_missing_shutdown(self):
        self.stack.enter_context(patch.object(deploy.subprocess, 'run', return_value=Mock(returncode=0)))
        archive = self.stack.enter_context(patch.object(deploy, 'write_backup'))
        for contents in (None, '{"clean": false}', '{"clean": "true"}', 'broken json'):
            with self.subTest(contents=contents):
                if contents is None:
                    self.marker.unlink(missing_ok=True)
                else:
                    self.marker.write_text(contents)
                self.run.reset_mock()
                with self.assertRaisesRegex(RuntimeError, 'shutdown was not confirmed clean'):
                    deploy.backup()
                archive.assert_not_called()
                self.assertEqual([call.args for call in self.run.call_args_list],
                                 [('systemctl', 'stop', 'mud86-runtime.service')])

    def test_backup_restarts_after_confirmed_stop_even_if_archive_fails(self):
        self.stack.enter_context(patch.object(deploy.subprocess, 'run', return_value=Mock(returncode=0)))
        self.marker.write_text(json.dumps({'clean': True}))
        self.stack.enter_context(patch.object(deploy, 'write_backup', side_effect=OSError('archive failed')))
        with self.assertRaisesRegex(OSError, 'archive failed'):
            deploy.backup()
        self.run.assert_called_with('systemctl', 'start', 'mud86-runtime.service', 'mud86-gateway.service')
