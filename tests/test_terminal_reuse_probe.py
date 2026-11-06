import asyncio
import unittest
from unittest.mock import AsyncMock, Mock

from aiohttp import WSMsgType
from tests.integration_terminal_reuse import admit_once, Trace


class ReuseProbeTests(unittest.IsolatedAsyncioTestCase):
    async def test_fragmented_name_prompt_needs_no_persona_or_game_input(self):
        socket=Mock()
        socket.receive=AsyncMock(side_effect=[Mock(type=WSMsgType.TEXT,data='By what name '),
                                             Mock(type=WSMsgType.TEXT,data='shall I call you?')])
        socket.send_str=AsyncMock()
        await admit_once(socket)
        socket.send_str.assert_not_called()

    async def test_closed_socket_is_failure_not_an_admission_retry(self):
        socket=Mock()
        socket.receive=AsyncMock(return_value=Mock(type=WSMsgType.CLOSE,data=1013))
        with self.assertRaisesRegex(RuntimeError,'closed before admission'):
            await admit_once(socket)
        self.assertEqual(socket.receive.await_count,1)

    def test_trace_is_bounded_and_marks_truncation(self):
        trace=Trace(limit=5)
        trace.record('rx',b'abc')
        trace.record('tx',b'defg')
        self.assertEqual(trace.size,5)
        self.assertTrue(trace.truncated)
        self.assertEqual(bytes.fromhex(trace.events[-1]['hex']),b'de')
