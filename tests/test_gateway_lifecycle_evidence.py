import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from server.gateway import wake_monitor, logout_guest
from tests.integration_terminal_lifecycle import native_state

COMPLETE=(b'kjob\r\nJob 12 User MUDGUEST\r\nLogged-off TTY0\r\n'
          b'Runtime: 0:00:00\r\nDisk Reads:1, Writes:2, Blocks saved:0\r\n\r\n.')


class LifecycleEvidenceTests(unittest.IsolatedAsyncioTestCase):
    def test_failed_diagnostic_resume_forbids_guest_cleanup_at_scp(self):
        runtime=Mock(booted=True)
        runtime.command.return_value='SYSTAT fixture'
        runtime.scope.console.at_prompt=True
        runtime.scope.console.command.return_value='DZ fixture'
        runtime.scope.console.resume.side_effect=TimeoutError('uncertain')
        evidence={}
        with tempfile.TemporaryDirectory() as directory:
            native_state(runtime,Path(directory),evidence)
        self.assertFalse(runtime.booted)
        self.assertIsNone(runtime.control_prompt)
        self.assertEqual(evidence['resume_error_type'],'TimeoutError')
        runtime.command.assert_called_once()
        runtime.scope.console.command.assert_called_once_with('show dz')

    async def test_timeout_identifies_assigned_line_and_submitted_wakeup(self):
        reader=asyncio.StreamReader()
        reader.feed_data(b'Connected to the PDP-10 simulator DZ device, line 0\r\n')
        writer=Mock()
        progress={}
        with patch('server.gateway.TTY_CARRIER_SETTLE_SECONDS',0):
            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(wake_monitor(reader,writer,progress=progress),.02)
        self.assertEqual(progress['stage'],'monitor-response')
        self.assertEqual(progress['line'],0)
        self.assertTrue(progress['wakeup_submitted'])
        self.assertFalse(progress['monitor_seen'])
        writer.write.assert_called_once_with('\r')

    async def test_partial_banner_records_no_line_or_submitted_input(self):
        reader=asyncio.StreamReader()
        reader.feed_data(b'Connected to the PDP-10 simulator DZ device, line ')
        progress={}
        writer=Mock()
        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(wake_monitor(reader,writer,progress=progress),.02)
        self.assertEqual(progress['stage'],'line-assignment')
        self.assertIsNone(progress['line'])
        self.assertFalse(progress['wakeup_submitted'])
        writer.write.assert_not_called()

    async def test_logout_prefix_does_not_release_line_before_accounting_and_prompt(self):
        reader=asyncio.StreamReader()
        writer=Mock()
        before,after=COMPLETE.split(b'Logged-off',1)
        reader.feed_data(before+b'Logged-off')
        task=asyncio.create_task(logout_guest(reader,writer,entered=True,monitor=True,connection_id='fixture'))
        try:
            await asyncio.sleep(.02)
            self.assertFalse(task.done(),'Logged-off prefix is not completed logout')
            reader.feed_data(after)
            self.assertTrue(await asyncio.wait_for(task,1))
            writer.write.assert_called_once_with('kjob\r')
        finally:
            task.cancel()
            await asyncio.gather(task,return_exceptions=True)

    async def test_incomplete_logout_reports_structural_flags_without_payload(self):
        reader=asyncio.StreamReader()
        writer=Mock()
        reader.feed_data(b'kjob\r\nprivate secret body\r\nLogged-off TTY0\r\n')
        with patch('server.gateway.LOGOUT_TIMEOUT',.02),self.assertLogs('server.gateway',level='WARNING') as logs:
            self.assertFalse(await logout_guest(reader,writer,entered=True,monitor=True,connection_id='fixture'))
        message=' '.join(logs.output)
        self.assertIn('logged_off_seen=True',message)
        self.assertIn('final_prompt_seen=False',message)
        self.assertNotIn('private secret',message)
        writer.write.assert_called_once_with('kjob\r')
