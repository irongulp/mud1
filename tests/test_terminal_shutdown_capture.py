"""Failure ownership for the disposable shutdown diagnostic."""
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import Mock, patch
from contextlib import nullcontext
import os
import subprocess
import sys

from server.runtime import MONITOR_PROMPT
from tests import integration_terminal_lifecycle as fixture
from tests.shutdown_capture import capture_runtime_shutdown


class ShutdownCaptureTests(unittest.TestCase):
    def test_targeted_capture_only_after_failed_deadline_and_existing_halt(self):
        for outcome in ('completed', 'early-error', 'late-diagnostic', 'timeout', 'capture-error'):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as directory:
                now = [100.]
                events = []
                runtime = Mock(state=Path(directory), booted=True, control_prompt=MONITOR_PROMPT)
                runtime.scope.verified = True
                runtime.scope.private_console.return_value = nullcontext()
                def halt():
                    events.append('halt')
                    if outcome == 'late-diagnostic':
                        now[0] += 2
                runtime.scope.console.halt.side_effect = halt
                runtime.scope.console.command.return_value = 'DZ'
                def command(text, **kwargs):
                    events.append(text)
                    self.assertEqual(kwargs['timeout'], 90)
                    if outcome == 'completed':
                        return 'KSYS processing completed'
                    now[0] += (90 if outcome in ('timeout', 'capture-error') else
                               89 if outcome == 'late-diagnostic' else 1)
                    raise TimeoutError('private console payload')
                runtime.command.side_effect = command
                def stop(instance):
                    try:
                        instance.command('set ksys now', timeout=90)
                    except TimeoutError:
                        return False
                    return True
                def capture(console, report, *, scope_verified):
                    events.append('capture')
                    self.assertTrue(scope_verified)
                    self.assertEqual(console.deadline, 200)
                    if outcome == 'capture-error':
                        raise RuntimeError('private memory payload')
                    report.update(outcome='partial')
                with patch('tests.shutdown_capture.time.monotonic', side_effect=lambda: now[0]), \
                        patch('tests.shutdown_capture.capture_halted', side_effect=capture, create=True) as reader:
                    result = capture_runtime_shutdown(runtime, stop, census=False, ksys=True)
                self.assertEqual(result, outcome == 'completed')
                self.assertEqual(reader.call_count, int(outcome in ('timeout', 'capture-error')))
                if reader.called:
                    self.assertEqual(events, ['set ksys now', 'halt', 'capture'])
                runtime.scope.console.resume.assert_not_called()
                runtime.scope.console.deposit.assert_not_called()
                reports = list((Path(directory) / 'shutdown-capture').glob('*/report.json'))
                self.assertNotIn('private', reports[0].read_text())

    def test_installed_mapping_launcher_without_checkout_tests_package(self):
        checkout = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            release = Path(directory).resolve()
            for name in ('server', 'tools'):
                (release / name).symlink_to(checkout / name, target_is_directory=True)
            result = subprocess.run(
                [sys.executable, '-c',
                 'import sys;sys.path.insert(0,sys.argv[1]);import ksys_capture;'
                 'assert "tests" not in sys.modules;'
                 'import runpy;sys.argv=[sys.argv[1]+"/shutdown_capture.py","--help"];'
                 'runpy.run_path(sys.argv[0],run_name="__main__")',
                 str(checkout / 'tests')],
                cwd=release, env=dict(os.environ, PYTHONPATH=str(release), MUD86_KSYS_MAPPING='1'),
                text=True, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_failure_only_mode_retains_original_commands_and_captures_after_failure(self):
        for failure in (False,True):
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as directory:
                runtime=Mock(state=Path(directory),booted=True,control_prompt=MONITOR_PROMPT)
                def command(text,*args,**kwargs):
                    if text=='show queues': return 'The queues are empty'
                    if text=='set ksys now':
                        if failure: raise TimeoutError('private buffer')
                        return 'KSYS processing completed'
                    self.fail('Unexpected guest command: '+text)
                runtime.command.side_effect=command
                original_command=runtime.command
                def stop(instance):
                    instance.command('show queues',timeout=90)
                    try: instance.command('set ksys now',timeout=89)
                    except TimeoutError: return False
                    return True
                original_stop=Mock(side_effect=stop)
                runtime.scope.console.command.return_value='DZ state'
                self.assertEqual(capture_runtime_shutdown(runtime,original_stop,census=False),not failure)
                original_stop.assert_called_once_with(runtime)
                self.assertEqual([call.args[0] for call in original_command.call_args_list],
                                 ['show queues','set ksys now'])
                self.assertEqual(original_command.call_args_list[-1].kwargs['timeout'],89)
                reports=list((Path(directory)/'shutdown-capture').glob('*/report.json'))
                report=json.loads(reports[0].read_text())
                self.assertFalse(report['shutdown_evidence']['census_enabled'])
                self.assertFalse((reports[0].parent/'pre-shutdown-systat.txt').exists())
                self.assertEqual((reports[0].parent/'shutdown-failure-dz.txt').exists(),failure)
                self.assertEqual(runtime.scope.console.halt.call_count,int(failure))
                runtime.scope.console.resume.assert_not_called()

    def test_installed_wrapper_calls_original_once_and_retains_exception_type(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime=Mock(state=Path(directory),booted=False)
            original=Mock(side_effect=TimeoutError('private buffer'))
            with self.assertRaises(TimeoutError):
                capture_runtime_shutdown(runtime,original)
            original.assert_called_once_with(runtime)
            runtime.stop.assert_not_called()
            reports=list((Path(directory)/'shutdown-capture').glob('*/report.json'))
            self.assertEqual(len(reports),1)
            report=json.loads(reports[0].read_text())
            self.assertFalse(report['shutdown_clean'])
            self.assertEqual(report['error_type'],'TimeoutError')
            self.assertNotIn('private buffer',reports[0].read_text())

    def test_installed_wrapper_without_child_preserves_original_stop(self):
        runtime=Mock(child=None)
        original=Mock(return_value=False)
        self.assertFalse(capture_runtime_shutdown(runtime,original))
        original.assert_called_once_with(runtime)
        runtime.command.assert_not_called()

    def test_failed_ksys_captures_without_guest_replay_or_resume(self):
        runtime=Mock(booted=True,control_prompt=MONITOR_PROMPT)
        def command(text,*args,**kwargs):
            if text=='systat': return 'job census'
            raise TimeoutError('private terminal buffer')
        runtime.command.side_effect=command
        original=runtime.command
        def stop():
            try: runtime.command('set ksys now','KSYS processing completed',timeout=90)
            except TimeoutError: return False
            return True
        runtime.stop.side_effect=stop
        runtime.scope.console.command.return_value='DZ state'
        report={}
        with tempfile.TemporaryDirectory() as directory:
            self.assertFalse(fixture.observed_stop(runtime,Path(directory),report))
            self.assertEqual((Path(directory)/'pre-shutdown-systat.txt').read_text(),'job census')
            self.assertEqual((Path(directory)/'shutdown-failure-dz.txt').read_text(),'DZ state')
        self.assertEqual([call.args[0] for call in original.call_args_list],['systat','set ksys now'])
        runtime.scope.console.halt.assert_called_once()
        runtime.scope.console.command.assert_called_once_with('show dz')
        runtime.scope.console.resume.assert_not_called()
        self.assertEqual(report['shutdown_evidence']['error_type'],'TimeoutError')
        self.assertNotIn('private terminal buffer',str(report))

    def test_completed_shutdown_does_not_halt(self):
        runtime=Mock(booted=True,control_prompt=MONITOR_PROMPT)
        runtime.command.return_value='job census'
        runtime.stop.return_value=True
        with tempfile.TemporaryDirectory() as directory:
            self.assertTrue(fixture.observed_stop(runtime,Path(directory),{}))
        runtime.scope.console.halt.assert_not_called()

    def test_uncertain_census_fences_guest_commands(self):
        runtime=Mock(booted=True,control_prompt=MONITOR_PROMPT)
        runtime.command.side_effect=TimeoutError('uncertain census')
        runtime.stop.return_value=False
        report={}
        with tempfile.TemporaryDirectory() as directory:
            self.assertFalse(fixture.observed_stop(runtime,Path(directory),report))
        self.assertFalse(runtime.booted)
        self.assertIsNone(runtime.control_prompt)
        self.assertEqual(report['shutdown_evidence']['census_error_type'],'TimeoutError')
        runtime.command.assert_called_once()
