import asyncio
import json
import unittest
from unittest.mock import AsyncMock, Mock

from tests.logout_observer import observe_logout


class LogoutObserverTests(unittest.IsolatedAsyncioTestCase):
    async def test_eof_records_partial_structure_without_payload(self):
        reader=asyncio.StreamReader()
        reader.feed_data(b'private tail')
        reader.feed_eof()
        emit=Mock()
        self.assertFalse(await observe_logout(AsyncMock(return_value=False),reader,Mock(),emit=emit))
        record=emit.call_args.args[0]
        self.assertEqual(record['outcome'],'read-error')
        self.assertTrue(record['after']['eof'])
        self.assertNotIn('private tail',json.dumps(record))

    async def test_late_report_preserves_failure_without_input_or_payload_logging(self):
        reader=asyncio.StreamReader()
        writer=Mock()
        original=AsyncMock(return_value=False)
        emit=Mock()
        task=asyncio.create_task(observe_logout(original,reader,writer,emit=emit,seconds=.2))
        await asyncio.sleep(.01)
        reader.feed_data(b'kjob\r\nprivate person\r\nLogged-off TTY0\r\n'
                         b'Runtime: 0\r\nDisk Reads:1, Writes:2, Blocks saved:0\r\n\r\n.')
        self.assertFalse(await task)
        original.assert_awaited_once()
        writer.write.assert_not_called()
        record=emit.call_args.args[0]
        self.assertTrue(record['late_complete'])
        self.assertNotIn('private person',json.dumps(record))

    async def test_silence_is_bounded_and_success_never_observed(self):
        for success in (False,True):
            reader=asyncio.StreamReader()
            writer=Mock()
            emit=Mock()
            result=await observe_logout(AsyncMock(return_value=success),reader,writer,
                                        emit=emit,seconds=.01)
            self.assertEqual(result,success)
            writer.write.assert_not_called()
            self.assertEqual(emit.call_count,0 if success else 1)
            if not success:
                self.assertEqual(emit.call_args.args[0]['outcome'],'timeout')

    async def test_cancelled_observation_reports_and_propagates(self):
        emit=Mock()
        task=asyncio.create_task(observe_logout(AsyncMock(return_value=False),
                                 asyncio.StreamReader(),Mock(),emit=emit,seconds=1))
        await asyncio.sleep(.01)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(emit.call_args.args[0]['outcome'],'cancelled')
