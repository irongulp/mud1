import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

from aiohttp import ClientSession, WSMsgType
from aiohttp.test_utils import TestServer

from server.gateway import create_app, wake_monitor


class CarrierAdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_or_invalid_banner_sends_no_guest_input(self):
        for data in (b'no banner\r\n.',b'Connected to the PDP-10 simulator DZ device, line invalid\r\n'):
            reader=asyncio.StreamReader()
            reader.feed_data(data)
            reader.feed_eof()
            writer=Mock()
            with self.assertRaises((OSError,asyncio.IncompleteReadError)):
                await wake_monitor(reader,writer)
            writer.write.assert_not_called()

    async def test_timeout_does_not_repeat_initial_cr(self):
        reader=asyncio.StreamReader()
        reader.feed_data(b'Connected to the PDP-10 simulator DZ device, line 0\r\n')
        writer=Mock()
        with patch('server.gateway.TTY_CARRIER_SETTLE_SECONDS',0):
            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(wake_monitor(reader,writer),.05)
        writer.write.assert_called_once_with('\r')

    async def test_gateway_does_not_lose_wakeup_before_line_banner(self):
        reader=asyncio.StreamReader()
        original_read=reader.read
        async def read_text(size):
            return (await original_read(size)).decode('ascii')
        reader.read=read_text
        writer=Mock()
        writer.drain=AsyncMock()
        writer.wait_closed=AsyncMock()
        ready=False
        sent=[]
        def write(data):
            sent.append((ready,data))
            if data=='\r' and not ready:
                return  # Carrier establishment discards pre-ready typeahead.
            if data=='\r' or data.startswith('set tty') or '\x03' in data:
                reader.feed_data(b'\r\n.')
            elif data=='login mudguest\r':
                reader.feed_data(b'By what name shall I call you?\r\n*')
            elif data=='kjob\r':
                reader.feed_data(b'Logged-off\r\n.')
        writer.write.side_effect=write
        async def banner():
            nonlocal ready
            await asyncio.sleep(.05)
            reader.feed_data(b'Connected to the PDP-10 simulator DZ device, line ')
            await asyncio.sleep(.05)
            ready=True
            reader.feed_data(b'0\r\n')
        task=asyncio.create_task(banner())
        with patch('server.gateway.telnetlib3.open_connection',new=AsyncMock(return_value=(reader,writer))), \
                patch('server.gateway.CONNECT_TIMEOUT',1):
            async with TestServer(create_app(maintenance_file=None)) as server,ClientSession() as client:
                async with client.ws_connect(server.make_url('/terminal')) as websocket:
                    message=await asyncio.wait_for(websocket.receive(),2)
                    self.assertEqual(message.type,WSMsgType.TEXT)
                    self.assertIn('By what name shall I call you?',message.data)
        await task
        self.assertTrue(all(was_ready for was_ready,_ in sent))
        self.assertEqual(sum(data=='\r' for _,data in sent),1)
