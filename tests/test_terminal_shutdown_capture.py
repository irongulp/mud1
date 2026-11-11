"""Failure ownership for the disposable shutdown diagnostic."""
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import Mock

from server.runtime import MONITOR_PROMPT
from tests import integration_terminal_lifecycle as fixture
from tests.shutdown_capture import capture_runtime_shutdown


class ShutdownCaptureTests(unittest.TestCase):
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
