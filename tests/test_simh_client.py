"""Deterministic event ordering for the pinned Telnet client's close race."""
import asyncio
import unittest
from unittest.mock import MagicMock

from server.gateway import SimhClient


class SimhClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.transport = MagicMock(spec=asyncio.Transport)
        self.transport.get_extra_info.side_effect = lambda name, default=None: default
        self.transport.is_closing.return_value = False
        self.protocol = SimhClient(encoding='ascii', connect_minwait=0, connect_maxwait=0)
        self.protocol.connection_made(self.transport)
        await asyncio.wait_for(self.protocol._waiter_connected, 1)
        self.rx_tasks = []

    async def asyncTearDown(self):
        self.protocol.connection_lost(None)
        await asyncio.gather(*self.rx_tasks, return_exceptions=True)

    def enqueue(self, data):
        self.protocol.data_received(data)
        if self.protocol._rx_task is not None:
            self.rx_tasks.append(self.protocol._rx_task)

    async def assert_rx_finished_without_error(self):
        outcomes = await asyncio.gather(*self.rx_tasks, return_exceptions=True)
        self.assertFalse([outcome for outcome in outcomes
                          if isinstance(outcome, Exception)], outcomes)
        self.assertEqual(self.protocol._rx_bytes, 0)
        self.assertFalse(self.protocol._rx_queue)

    async def test_queued_logout_acknowledgement_precedes_remote_eof(self):
        self.enqueue(b'Goodbye\r\nLogged-off\r\n.')
        self.protocol.eof_received()
        self.protocol.connection_lost(None)  # The transport can notify again.
        await self.assert_rx_finished_without_error()
        self.assertEqual(await self.protocol.reader.read(), 'Goodbye\r\nLogged-off\r\n.')
        self.assertEqual(await self.protocol.reader.read(), '')

    async def test_local_writer_close_preserves_fragmented_telnet_and_final_text(self):
        self.enqueue(b'Final text\r\n\xff')
        self.enqueue(b'\xfb\x22Logged-off\r\n')  # Split WILL LINEMODE.
        self.protocol.writer.close()
        await self.assert_rx_finished_without_error()
        self.assertEqual(await self.protocol.reader.read(), 'Final text\r\nLogged-off\r\n')
        self.assertIn(b'\xff\xfe\x22', [call.args[0] for call in self.transport.write.call_args_list])
        await self.protocol.writer.wait_closed()

    async def test_close_after_receive_task_has_yielded_keeps_remaining_chunks(self):
        first = b'x' * (128 * 1024)
        self.enqueue(first)
        self.enqueue(b'\r\nLogged-off')
        await asyncio.sleep(0)  # _process_rx yields after its first large chunk.
        self.protocol.connection_lost(None)
        await self.assert_rx_finished_without_error()
        self.assertEqual(await self.protocol.reader.read(), first.decode() + '\r\nLogged-off')

    async def test_data_callback_after_close_does_not_restart_receive_task(self):
        self.protocol.connection_lost(None)
        self.enqueue(b'late callback')
        await self.assert_rx_finished_without_error()
        self.assertEqual(await self.protocol.reader.read(), '')

    async def test_connection_reset_remains_visible_to_reader(self):
        self.enqueue(b'pending')
        error = ConnectionResetError('upstream reset')
        self.protocol.connection_lost(error)
        await self.assert_rx_finished_without_error()
        with self.assertRaises(ConnectionResetError):
            await self.protocol.reader.read()

    async def test_fragmented_telnet_command_is_not_exposed_during_normal_reads(self):
        self.enqueue(b'hello\xff')
        await self.assert_rx_finished_without_error()
        self.enqueue(b'\xfb\x22world')
        await self.assert_rx_finished_without_error()
        self.protocol.connection_lost(None)
        self.assertEqual(await self.protocol.reader.read(), 'helloworld')

    async def test_close_before_negotiation_callback_does_not_leave_failed_handles(self):
        loop = asyncio.get_running_loop()
        errors = []
        original = loop.get_exception_handler()
        protocol = SimhClient(encoding='ascii', connect_minwait=0, connect_maxwait=0)
        loop.set_exception_handler(lambda loop, context: errors.append(context))
        try:
            protocol.connection_made(self.transport)
            protocol.data_received(b'Logged-off')
            task = protocol._rx_task
            protocol.connection_lost(None)
            await asyncio.gather(task, return_exceptions=True)
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            self.assertEqual(errors, [])
            self.assertEqual(await protocol.reader.read(), 'Logged-off')
        finally:
            loop.set_exception_handler(original)
            protocol.connection_lost(None)

    async def test_bad_fragmented_telnet_command_retains_library_warning_handling(self):
        self.enqueue(b'\xff')
        await self.assert_rx_finished_without_error()
        with self.assertLogs('telnetlib3.client', level='WARNING'):
            self.enqueue(b'\x01')  # Invalid two-byte Telnet command.
            await self.assert_rx_finished_without_error()
