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

MIDNIGHT_BOOT = '2ba24b03760142a28e17a1fc1df615b1'
MIDNIGHT_LOG = '''Job 2BA24B Req #4 for OPR [1,2] in stream 0
 0:26:22 COMENT ;MUD86 batch probe 2ba24b03760142a28e17a1fc1df615b1
 0:26:22 BATCH  DAYTIME
 0:26:22 MONITR Saturday 21-Nov-126 :26:23
 0:26:22 BATCH  .KJOB/BATCH
 0:26:22 USER   Logged-off TTY43  at  0:26:23  on 21-Nov-126
'''


class BatchReadinessTests(unittest.TestCase):
    def test_witnessed_midnight_daytime_requires_identity_result_and_logout(self):
        for label in ('BATCH  DAYTIME', 'MONITR .DAYTIME'):
            log = MIDNIGHT_LOG.replace('BATCH  DAYTIME', label)
            with self.subTest(label=label):
                self.assertTrue(completed_probe(log, '2ba24b', MIDNIGHT_BOOT, 4))
                self.assertFalse(completed_probe(log, '2ba24b', '0'*32, 4))
                self.assertFalse(completed_probe(log, '2ba24b', MIDNIGHT_BOOT, 5))
                for altered in (
                        log.replace('MONITR Saturday', 'USER Saturday'),
                        log.replace('Saturday 21-Nov-126 :26:23', ''),
                        log.replace('Logged-off', ''),
                        log.replace('.KJOB/BATCH', ''),
                        log.replace(':26:23\n', ':26:\n'),
                        log.replace(':26:23\n', ':99:23\n'),
                        log.replace(':26:23\n', ':26:23garbage\n')):
                    self.assertFalse(completed_probe(altered, '2ba24b', MIDNIGHT_BOOT, 4))

    def test_midnight_probe_accepts_first_completed_log_without_resubmission(self):
        with tempfile.TemporaryDirectory() as directory:
            machine = self.machine(directory)
            original = machine.command.side_effect
            log = MIDNIGHT_LOG.replace('2BA24B', 'ABCDEF').replace(
                MIDNIGHT_BOOT, BOOT).replace('Req #4', 'Req #7')
            def command(text, **kwargs):
                return log if text == 'type abcdef.log' else original(text, **kwargs)
            machine.command.side_effect = command
            prepare_batch(machine)
            self.assertTrue(machine._batch_verified)
            self.assertEqual([call.args[0] for call in machine.command.call_args_list],
                             ['directory abcdef.*', 'submit abcdef.ctl/time:0:00:10/output:nolog',
                              'systat', 'type abcdef.log'])
            machine.copy_text.assert_called_once()

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
