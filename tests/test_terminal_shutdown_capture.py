"""Failure ownership for the disposable shutdown diagnostic."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from server.runtime import MONITOR_PROMPT
from tests import integration_terminal_lifecycle as fixture


class ShutdownCaptureTests(unittest.TestCase):
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
