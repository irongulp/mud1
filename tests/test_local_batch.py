from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock

from server.local_batch import BatchBootstrapError, completed_probe, prepare_batch

BOOT = 'abcdef0123456789abcdef0123456789'
LOG = '''Job ABCDEF Req #7 for OPR [1,2]
 3:00:36 COMENT ;MUD86 batch probe abcdef0123456789abcdef0123456789
 3:00:36 MONITR .DAYTIME
 3:00:36 MONITR Friday 18-Sep-126 3:00:38
 3:00:36 BATCH  .KJOB/BATCH
 3:00:36 USER   Logged-off TTY43 at 3:00:37
'''


class BatchReadinessTests(unittest.TestCase):
    def machine(self, directory):
        evidence = Path(directory)/BOOT
        evidence.mkdir()
        machine = MagicMock()
        machine.scope = SimpleNamespace(evidence=evidence, record=MagicMock())
        machine.monitor_scope_verified = True
        machine._batch_verified = False

        def command(text, **kwargs):
            if text == 'directory abcdef.*':
                return '%WLDNSF No such files as abcdef.*'
            if text.startswith('submit '):
                return '[Batch job ABCDEF queued, request #7, limit 0:00:10]'
            if text == 'systat':
                return ' 1 [OPR] DET41 BATCON 48+40 SL 0'
            if text == 'type abcdef.log':
                return LOG
            raise AssertionError(text)

        machine.command.side_effect = command
        return machine

    def test_readiness_requires_completed_current_boot_native_probe(self):
        with tempfile.TemporaryDirectory() as directory:
            machine = self.machine(directory)
            prepare_batch(machine)
            self.assertTrue(machine._batch_verified)
            self.assertTrue((machine.scope.evidence/'batch-probe.json').is_file())
            machine.copy_text.assert_called_once()
            self.assertIn('/output:nolog', machine.command.call_args_list[1].args[0])

    def test_occupied_native_filenames_are_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            machine = self.machine(directory)
            machine.command.side_effect = None
            machine.command.return_value = 'ABCDEF CTL 1 <057>'
            with self.assertRaises(BatchBootstrapError):
                prepare_batch(machine)
            machine.copy_text.assert_not_called()
            self.assertFalse(machine._batch_verified)

    def test_lost_submit_reply_cannot_replay_the_submission(self):
        with tempfile.TemporaryDirectory() as directory:
            machine = self.machine(directory)
            machine.command.side_effect = ['%WLDNSF No such files as abcdef.*', TimeoutError()]
            with self.assertRaises(BatchBootstrapError):
                prepare_batch(machine)
            submissions = [call for call in machine.command.call_args_list if call.args[0].startswith('submit ')]
            self.assertEqual(len(submissions), 1)
            self.assertFalse(machine._batch_verified)

    def test_evidence_error_cannot_turn_an_uncertain_submit_into_a_retryable_error(self):
        with tempfile.TemporaryDirectory() as directory:
            machine = self.machine(directory)
            machine.command.side_effect = ['%WLDNSF No such files as abcdef.*', TimeoutError()]
            machine.scope.record.side_effect = OSError('evidence unavailable')
            with self.assertRaises(BatchBootstrapError):
                prepare_batch(machine)
            self.assertFalse(machine._batch_verified)

    def test_stale_log_or_echo_without_daytime_result_is_not_execution_proof(self):
        self.assertTrue(completed_probe(LOG, 'abcdef', BOOT, 7))
        self.assertFalse(completed_probe(LOG, 'abcdef', '0'*32, 7))
        self.assertFalse(completed_probe(LOG, 'abcdef', BOOT, 8))
        self.assertFalse(completed_probe(LOG.replace('MONITR Friday', 'USER Friday'), 'abcdef', BOOT, 7))

    def test_native_batch_labeled_daytime_still_requires_the_monitor_result(self):
        native = LOG.replace('MONITR .DAYTIME', 'BATCH  DAYTIME')
        self.assertTrue(completed_probe(native, 'abcdef', BOOT, 7))
        self.assertFalse(completed_probe(native.replace('MONITR Friday', 'USER Friday'), 'abcdef', BOOT, 7))
