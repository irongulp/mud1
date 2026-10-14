"""Startup recovery is separate from migration work and keeps its original error."""
import json
import fcntl
import os
from pathlib import Path
import tempfile
import stat
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

import pexpect
from server.runtime import BOOT_ATTEMPTS, Runtime


class RuntimeStartupTests(unittest.TestCase):
    def test_batch_timeout_tail_is_private_and_does_not_include_other_readiness_output(self):
        from tools.batch_readiness import BatchReadinessError
        with tempfile.TemporaryDirectory() as directory:
            runtime = Runtime(Path(directory), '/unused')
            runtime.boot_phase = 'private-readiness'
            runtime.child = Mock(before='unrelated private output')
            failure = BatchReadinessError('allocation failed', phase='allocation')
            failure.response_tail = 'directory reply without final prompt'
            path = runtime.record_startup_failure(1, failure)
            record = json.loads(path.read_text())
            self.assertEqual(record['private_batch_response'], failure.response_tail)
            self.assertNotIn('unrelated private output', path.read_text())

    def test_inherited_lease_is_usable_by_child_and_stays_held_by_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            with (Path(directory) / 'runtime.lock').open('a') as parent:
                fcntl.flock(parent, fcntl.LOCK_EX | fcntl.LOCK_NB)
                program = ('import sys; from pathlib import Path; from server.runtime import runtime_lease\n'
                           'with runtime_lease(Path(sys.argv[1]), lock_fd=int(sys.argv[2])):\n'
                           ' print("lease verified")\n')
                result = subprocess.run([sys.executable, '-c', program, directory, str(parent.fileno())],
                                        pass_fds=(parent.fileno(),), capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                with (Path(directory) / 'runtime.lock').open('a') as competing, \
                        self.assertRaises(BlockingIOError):
                    fcntl.flock(competing, fcntl.LOCK_EX | fcntl.LOCK_NB)
    def test_session_can_borrow_installer_lease_without_releasing_it(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Runtime(Path(directory), '/unused')
            with (Path(directory) / 'runtime.lock').open('a') as parent:
                fcntl.flock(parent, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with patch.object(runtime, 'start'), patch.object(runtime, 'stop', return_value=True):
                    with runtime.session(runtime_lock_fd=parent.fileno()):
                        pass
                os.fstat(parent.fileno())  # Borrowing must not close the parent's descriptor.
                with (Path(directory) / 'runtime.lock').open('a') as competing, \
                        self.assertRaises(BlockingIOError):
                    fcntl.flock(competing, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_unrelated_descriptor_cannot_bypass_runtime_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Runtime(Path(directory), '/unused')
            (Path(directory) / 'runtime.lock').touch()
            with (Path(directory) / 'unrelated.lock').open('a') as unrelated, \
                    patch.object(runtime, 'start') as start, self.assertRaises(ValueError):
                with runtime.session(runtime_lock_fd=unrelated.fileno()):
                    pass
            start.assert_not_called()

    def test_service_final_cleanup_retains_original_startup_error(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Runtime(Path(directory), '/unused')
            failure = pexpect.TIMEOUT('original startup failure')
            with patch.object(runtime, 'start', side_effect=failure), \
                    patch.object(runtime, 'stop', side_effect=OSError('cleanup failed')), \
                    patch('server.runtime.signal.signal'), patch('server.runtime.notify'), \
                    self.assertRaises(pexpect.TIMEOUT) as raised:
                runtime.run()
            self.assertIs(raised.exception, failure)

    def test_boot_failure_retains_bounded_private_prompt_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Runtime(Path(directory), '/unused')
            runtime.boot_phase = 'OPR>'
            runtime.child = Mock(before='x' * 20000, pid=123)
            path = runtime.record_startup_failure(1, pexpect.TIMEOUT('private exception payload'))
            evidence = json.loads(path.read_text())
            self.assertEqual(evidence['phase'], 'OPR>')
            self.assertEqual(evidence['error'], 'TIMEOUT')
            self.assertLessEqual(len(evidence['pending_output']), 8192)
            self.assertNotIn('private exception payload', path.read_text())
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_readiness_errors_do_not_snapshot_unrelated_terminal_payloads(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Runtime(Path(directory), '/unused')
            runtime.boot_phase = 'private-readiness'
            runtime.child = Mock(before='private payload', pid=123)
            path = runtime.record_startup_failure(1, ValueError('private exception payload'))
            self.assertNotIn('private payload', path.read_text())

    def test_start_reaps_failed_guest_before_another_boot(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Runtime(Path(directory), '/unused')
            events = []
            def boot():
                events.append('boot')
                if events.count('boot') == 1:
                    raise pexpect.TIMEOUT('OPR did not start')
            with patch.object(runtime, 'boot', side_effect=boot), \
                    patch.object(runtime, 'stop', side_effect=lambda: events.append('stop') or False), \
                    patch('server.runtime.time.sleep'):
                runtime.start()
            self.assertEqual(events, ['boot', 'stop', 'boot'])
            self.assertFalse(json.loads((Path(directory) / 'shutdown.json').read_text())['clean'])

    def test_exhausted_startup_keeps_original_failure_and_attempt_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Runtime(Path(directory), '/unused')
            failure = pexpect.TIMEOUT('OPR did not start')
            with patch.object(runtime, 'boot', side_effect=failure) as boot, \
                    patch.object(runtime, 'stop', return_value=False) as stop, \
                    patch('server.runtime.time.sleep'), self.assertRaises(pexpect.TIMEOUT) as raised:
                runtime.start()
            self.assertIs(raised.exception, failure)
            self.assertEqual(boot.call_count, BOOT_ATTEMPTS)
            self.assertEqual(stop.call_count, BOOT_ATTEMPTS)

    def test_cleanup_error_cannot_mask_startup_failure_or_start_another_guest(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Runtime(Path(directory), '/unused')
            failure = pexpect.TIMEOUT('original boot failure')
            with patch.object(runtime, 'boot', side_effect=failure) as boot, \
                    patch.object(runtime, 'stop', side_effect=OSError('cannot reap')), \
                    self.assertRaises(pexpect.TIMEOUT) as raised:
                runtime.start()
            self.assertIs(raised.exception, failure)
            boot.assert_called_once()

    def test_session_does_not_replace_body_failure_with_unclean_shutdown(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Runtime(Path(directory), '/unused')
            failure = ValueError('capture failed')
            with patch.object(runtime, 'start'), patch.object(runtime, 'stop', return_value=False), \
                    self.assertRaises(ValueError) as raised:
                with runtime.session():
                    raise failure
            self.assertIs(raised.exception, failure)

    def test_successful_body_requires_clean_shutdown(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Runtime(Path(directory), '/unused')
            with patch.object(runtime, 'start'), patch.object(runtime, 'stop', return_value=False), \
                    self.assertRaisesRegex(RuntimeError, 'shutdown'):
                with runtime.session():
                    pass

    def test_failed_session_start_never_enters_body(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Runtime(Path(directory), '/unused')
            body = Mock()
            failure = pexpect.TIMEOUT('OPR did not start')
            with patch.object(runtime, 'start', side_effect=failure), \
                    patch.object(runtime, 'stop', return_value=False), self.assertRaises(pexpect.TIMEOUT):
                with runtime.session():
                    body()
            body.assert_not_called()

    def test_failed_guest_must_be_gone_before_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Runtime(Path(directory), '/unused')
            failure = pexpect.TIMEOUT('OPR did not start')
            def failed_boot():
                runtime.child = Mock()
                raise failure
            with patch.object(runtime, 'boot', side_effect=failed_boot) as boot, \
                    patch.object(runtime, 'stop', return_value=False), self.assertRaises(pexpect.TIMEOUT):
                runtime.start()
            boot.assert_called_once()

    def test_existing_guest_cannot_be_overwritten_by_start(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Runtime(Path(directory), '/unused')
            runtime.child = Mock()
            with patch.object(runtime, 'boot') as boot, self.assertRaisesRegex(RuntimeError, 'resources'):
                runtime.start()
            boot.assert_not_called()
