"""CI failures retain evidence from the container that actually failed."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import integration_external_deployment


class FailedInvocationTests(unittest.TestCase):
    def test_failed_rerun_retains_redacted_stdout_and_stderr(self):
        result = subprocess.CompletedProcess([], 1,
            'Roy: abcdef12 — initial password\n', 'Maintenance query timed out\n')
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / 'rerun.log'
            with patch.object(integration_external_deployment.subprocess, 'run', return_value=result):
                with self.assertRaisesRegex(AssertionError, 'Maintenance query timed out') as error:
                    integration_external_deployment.invoke('fresh', 'setup.sh', log=log)
            self.assertEqual(log.read_text(), str(error.exception))
            self.assertIn('Roy: [redacted]', log.read_text())
            self.assertNotIn('abcdef12', log.read_text())

    def test_timed_out_invocation_retains_redacted_partial_output(self):
        error = subprocess.TimeoutExpired(['setup.sh'], 3600,
            output=b'Roy: abcdef12 \xe2\x80\x94 initial password\n', stderr=b'last stage\n')
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / 'install.log'
            with patch.object(integration_external_deployment.subprocess, 'run', side_effect=error):
                with self.assertRaises(subprocess.TimeoutExpired):
                    integration_external_deployment.invoke('fresh', 'setup.sh', log=log)
            self.assertIn('last stage', log.read_text())
            self.assertNotIn('abcdef12', log.read_text())

    def test_timeout_during_credential_line_does_not_publish_password_prefix(self):
        error = subprocess.TimeoutExpired(['setup.sh'], 3600, output=b'Roy: abcde')
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / 'install.log'
            with patch.object(integration_external_deployment.subprocess, 'run', side_effect=error):
                with self.assertRaises(subprocess.TimeoutExpired):
                    integration_external_deployment.invoke('fresh', 'setup.sh', log=log)
            self.assertEqual(log.read_text(), 'Roy: [redacted]')


class ContainerDiagnosticsTests(unittest.TestCase):
    def test_unavailable_container_does_not_prevent_other_container_capture(self):
        from tests import deployment_diagnostics

        def run(command, **kwargs):
            self.assertGreater(kwargs['timeout'], 0)
            failed = 'mud86-external-fresh' in command
            return subprocess.CompletedProcess(command, int(failed),
                                               '' if failed else 'healthy evidence\n',
                                               'No such container\n' if failed else '')

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(deployment_diagnostics.subprocess, 'run', side_effect=run) as invoked:
                deployment_diagnostics.collect_all(Path(directory))
            for container in ('mud86-external-fresh', 'mud86-install-test'):
                for name in ('services', 'status', 'nginx', 'guest-systat'):
                    text = (Path(directory) / container / (name + '.log')).read_text()
                    self.assertIn('No such container' if container.endswith('fresh') else 'healthy evidence', text)
            guests = [call.args[0] for call in invoked.call_args_list
                      if 'tests.deployment_guest_status' in call.args[0]]
            self.assertEqual(len(guests), 2)
            for command in guests:
                self.assertIn('--signal=INT', command)
                self.assertIn('--kill-after=100s', command)

    def test_timeout_keeps_partial_diagnostic_output_and_continues(self):
        from tests import deployment_diagnostics

        def run(command, **kwargs):
            if 'journalctl' in command:
                raise subprocess.TimeoutExpired(command, kwargs['timeout'], output=b'partial journal\n')
            return subprocess.CompletedProcess(command, 0, 'next diagnostic\n', '')

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(deployment_diagnostics.subprocess, 'run', side_effect=run):
                deployment_diagnostics.collect_all(Path(directory))
            root = Path(directory) / 'mud86-external-fresh'
            self.assertIn('partial journal', (root / 'services.log').read_text())
            self.assertIn('timed out', (root / 'services.log').read_text())
            self.assertIn('next diagnostic', (root / 'guest-systat.log').read_text())
