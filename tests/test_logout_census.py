import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from server.runtime import MONITOR_PROMPT
from tests.logout_census import service_request, install_owner


class CensusTests(unittest.TestCase):
    def test_cancelled_pending_request_sends_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            runtime=Mock(booted=True,control_prompt=MONITOR_PROMPT)
            (root/'request.json').write_text('{"token":"boot"}')
            (root/'cancelled').touch()
            service_request(runtime,root,'boot')
            runtime.command.assert_not_called()

    def test_owner_hook_does_not_reenter_during_command_reads(self):
        with tempfile.TemporaryDirectory() as directory:
            state=Path(directory)
            (state/'ready').write_text('ready')
            runtime=Mock(state=state,booted=True,control_prompt=MONITOR_PROMPT)
            runtime.stopping.is_set.return_value=False
            runtime.child.read_nonblocking.return_value='bytes'
            install_owner(runtime)
            token=json.loads((state/'logout-census/owner.json').read_text())['token']
            root=state/'logout-census'/token
            (root/'request.json').write_text(json.dumps(dict(token=token,line=0)))
            runtime.command.side_effect=lambda *a,**k:runtime.child.read_nonblocking(10)
            runtime.child.read_nonblocking(4096,timeout=1)
            runtime.command.assert_called_once()

    def test_current_request_runs_once_on_owner_and_preserves_line(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            runtime=Mock(booted=True,control_prompt=MONITOR_PROMPT)
            runtime.stopping.is_set.return_value=False
            runtime.command.return_value='SYSTAT'
            (root/'request.json').write_text(json.dumps(dict(token='boot',connection='abc',line=2)))
            service_request(runtime,root,'boot')
            service_request(runtime,root,'boot')
            runtime.command.assert_called_once_with('systat',timeout=8)
            result=json.loads((root/'response.json').read_text())
            self.assertEqual(result['line'],2)
            self.assertTrue(result['completed'])

    def test_stale_request_sends_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            runtime=Mock()
            (root/'request.json').write_text('{"token":"old"}')
            service_request(runtime,root,'new')
            runtime.command.assert_not_called()

    def test_uncertain_census_fences_shutdown_without_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            runtime=Mock(booted=True,control_prompt=MONITOR_PROMPT)
            runtime.stopping.is_set.return_value=False
            runtime.command.side_effect=TimeoutError('private')
            (root/'request.json').write_text('{"token":"boot","line":0}')
            with self.assertRaises(RuntimeError):
                service_request(runtime,root,'boot')
            self.assertFalse(runtime.booted)
            self.assertIsNone(runtime.control_prompt)
            runtime.stopping.set.assert_called_once()
            self.assertNotIn('private',(root/'response.json').read_text())
