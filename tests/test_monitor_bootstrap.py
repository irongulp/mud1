from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock

from server.monitor_bootstrap import MonitorBootstrap, SimulatorConsole
from server.monitor_scope import MonitorCompatibilityError


class MonitorBootstrapTests(unittest.TestCase):
    def test_evidence_failure_cannot_hide_an_incompatible_monitor(self):
        scope = MonitorBootstrap.__new__(MonitorBootstrap)
        scope.child = MagicMock()
        scope.child.expect_exact.return_value = 0  # OPR before the required breakpoint.
        scope.stage = 'armed'
        scope.record = MagicMock(side_effect=OSError('evidence unavailable'))
        with self.assertRaises(MonitorCompatibilityError):
            scope.install_before_operator(1)
        self.assertFalse(scope.verified)

    def test_scp_input_requires_a_witnessed_prompt(self):
        child = MagicMock()
        console = SimulatorConsole(child)
        with self.assertRaises(RuntimeError):
            console.command('deposit PC 1')
        child.send.assert_not_called()

    def test_expired_installation_does_not_send_another_command(self):
        child = MagicMock()
        console = SimulatorConsole(child)
        console.at_prompt = True
        console.deadline = 0
        with self.assertRaises(RuntimeError):
            console.command('deposit PC 1')
        child.send.assert_not_called()

    def test_profile_mismatch_cannot_allocate_or_write(self):
        scope = MonitorBootstrap.__new__(MonitorBootstrap)
        scope.record = MagicMock()
        scope.console = MagicMock()
        scope.console.register.side_effect = lambda name: {'PC': 0o506703, 'EBR': 3}[name]
        with self.assertRaises(MonitorCompatibilityError):
            scope._install()
        scope.console.deposit.assert_not_called()
        scope.console.words.assert_not_called()

    def test_private_memory_queries_are_not_transcripted(self):
        child = SimpleNamespace(logfile='combined', logfile_read='read', logfile_send='send')
        scope = MonitorBootstrap.__new__(MonitorBootstrap)
        scope.child = child
        with scope.private_console():
            self.assertIsNone(child.logfile)
            self.assertIsNone(child.logfile_read)
            self.assertIsNone(child.logfile_send)
        self.assertEqual((child.logfile, child.logfile_read, child.logfile_send),
                         ('combined', 'read', 'send'))

    def test_failed_memory_read_cannot_leak_pending_output_during_cleanup(self):
        child = SimpleNamespace(logfile='combined', logfile_read='read', logfile_send='send')
        scope = MonitorBootstrap.__new__(MonitorBootstrap)
        scope.child = child
        with self.assertRaises(TimeoutError):
            with scope.private_console():
                raise TimeoutError('private memory output still queued')
        self.assertEqual((child.logfile, child.logfile_read, child.logfile_send), (None, None, None))

    def test_evidence_is_private_and_each_boot_has_its_own_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            first = MonitorBootstrap(MagicMock(), Path(directory))
            second = MonitorBootstrap(MagicMock(), Path(directory))
            first.record('armed')
            self.assertNotEqual(first.evidence, second.evidence)
            self.assertEqual(first.evidence.stat().st_mode & 0o777, 0o700)
            self.assertEqual((first.evidence/'01-armed.json').stat().st_mode & 0o777, 0o600)
