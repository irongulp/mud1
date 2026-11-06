import subprocess
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from tests import deployment_diagnostics
from tests.integration_external_deployment import invoke


class DeploymentDiagnosticsTests(unittest.TestCase):
    def test_failed_command_retains_redacted_log_before_raising(self):
        result = subprocess.CompletedProcess([], 1, 'Roy: abcdefgh — initial\n', 'shutdown failed\n')
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / 'backup.log'
            with patch('tests.integration_external_deployment.subprocess.run', return_value=result):
                with self.assertRaisesRegex(AssertionError, 'shutdown failed'):
                    invoke('fixture', 'mud86ctl', 'backup', log=log)
            self.assertEqual(log.read_text(), 'Roy: [redacted] — initial\nshutdown failed\n')

    def test_collects_both_containers_before_and_after_cleanup(self):
        commands = []
        def run(command, **kwargs):
            commands.append(command)
            self.assertGreater(kwargs['timeout'], 0)
            return subprocess.CompletedProcess(command, 0, 'diagnostic output\n', '')
        with tempfile.TemporaryDirectory() as directory:
            with patch('tests.deployment_diagnostics.subprocess.run', side_effect=run):
                deployment_diagnostics.collect(Path(directory))
            for container in deployment_diagnostics.CONTAINERS:
                root = Path(directory) / container
                for phase in ('before-stop', 'after-stop'):
                    self.assertIn('diagnostic output', (root / (phase + '-services.log')).read_text())
                    self.assertTrue((root / (phase + '-shutdown.log')).is_file())
                stop = ['docker', 'exec', container, 'systemctl', 'stop', 'mud86-runtime.service']
                index = commands.index(stop)
                journals = [i for i, command in enumerate(commands)
                            if command[:3] == ['docker', 'exec', container] and 'journalctl' in command]
                self.assertLess(journals[0], index)
                self.assertGreater(journals[-1], index)
            self.assertFalse(any('persona-admin.json' in str(command) for command in commands))

    def test_missing_container_and_timeout_do_not_hide_other_evidence(self):
        def run(command, **kwargs):
            if command[2] == deployment_diagnostics.CONTAINERS[0]:
                raise subprocess.TimeoutExpired(command, kwargs['timeout'], output=b'partial output')
            return subprocess.CompletedProcess(command, 1, '', 'container unavailable')
        with tempfile.TemporaryDirectory() as directory:
            with patch('tests.deployment_diagnostics.subprocess.run', side_effect=run):
                deployment_diagnostics.collect(Path(directory))
            logs = list(Path(directory).rglob('*.log'))
            self.assertEqual(len(logs), len(deployment_diagnostics.CONTAINERS) * 7)
            self.assertTrue(any('partial output' in log.read_text() for log in logs))
            self.assertTrue(any('container unavailable' in log.read_text() for log in logs))
