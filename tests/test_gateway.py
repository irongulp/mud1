import asyncio
import unittest
from unittest.mock import patch

import telnetlib3
from aiohttp import ClientSession, WSMsgType, web
from aiohttp.client_exceptions import ClientConnectionResetError
from aiohttp.test_utils import TestServer

from server.gateway import create_app


class GatewayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.inputs = asyncio.Queue()
        self.closed = asyncio.Queue()
        self.count = 0
        self.reject_entry = False
        self.terminal_setups = []
        self.allow_logout = asyncio.Event()
        self.allow_logout.set()
        self.handler_errors = []

        async def shell(reader, writer):
            self.count += 1
            identifier = self.count
            try:
                await reader.readuntil(b"\r")
                writer.write("\r\n.")
                login = (await reader.readuntil(b"\r")).decode("ascii")
                while login.startswith("set tty"):
                    self.terminal_setups.append(login)
                    writer.write("\r\n.")
                    login = (await reader.readuntil(b"\r")).decode("ascii")
                await self.inputs.put(login)
                greeting = '' if self.reject_entry else 'Hello, test!\r\n'
                writer.write(f"By what name shall I call you?\r\n{greeting}SESSION {identifier}\r\n*")
                while True:
                    data = await reader.read(100)
                    if not data:
                        break
                    await self.inputs.put(data)
                    if self.reject_entry and data.startswith('bad'):
                        writer.write('\r\nNo!\r\n.')
                    elif "quit\r" in data or '\x03' in data:
                        writer.write("\r\n.")
                    elif "kjob\r" in data:
                        await self.allow_logout.wait()
                        writer.write("Logged-off\r\n.")
                        break
                    else:
                        writer.write(data)
            finally:
                writer.close()
                await self.closed.put(identifier)

        self.backend = await telnetlib3.create_server(host="127.0.0.1", port=0, shell=shell,
                                                     encoding="ascii", connect_maxwait=0.2)
        port = self.backend.sockets[0].getsockname()[1]
        @web.middleware
        async def record_errors(request, handler):
            try:
                return await handler(request)
            except Exception as error:
                self.handler_errors.append(error)
                raise
        app = create_app(upstream_port=port)
        app.middlewares.append(record_errors)
        self.server = TestServer(app)
        await self.server.start_server()
        self.client = ClientSession()

    async def asyncTearDown(self):
        await self.client.close()
        await self.server.close()
        self.backend.close()
        await self.backend.wait_closed()

    async def receive_until(self, socket, text):
        result = ""
        while text not in result:
            message = await asyncio.wait_for(socket.receive(), 5)
            self.assertEqual(message.type, WSMsgType.TEXT)
            result += message.data
        return result

    async def test_each_browser_gets_its_own_terminal_and_unmodified_output(self):
        first = await self.client.ws_connect(self.server.make_url("/terminal"))
        second = await self.client.ws_connect(self.server.make_url("/terminal"))
        try:
            self.assertIn("SESSION 1\r\n*", await self.receive_until(first, "*"))
            self.assertIn("SESSION 2\r\n*", await self.receive_until(second, "*"))
            self.assertEqual(self.terminal_setups.count("set tty type vt100\r"), 2)
            self.assertEqual(self.terminal_setups.count("set tty width 80\r"), 2)
            self.assertEqual(await asyncio.wait_for(self.inputs.get(), 5), "login mudguest\r")
            self.assertEqual(await asyncio.wait_for(self.inputs.get(), 5), "login mudguest\r")
            await first.send_str("look\r")
            self.assertEqual(await asyncio.wait_for(self.inputs.get(), 5), "look\r")
            self.assertEqual(await self.receive_until(first, "look\r"), "look\r")
        finally:
            await first.close()
            await second.close()
        self.assertEqual({await asyncio.wait_for(self.closed.get(), 5),
                          await asyncio.wait_for(self.closed.get(), 5)}, {1, 2})
        cleanup = "".join([await asyncio.wait_for(self.inputs.get(), 5) for _ in range(4)])
        self.assertEqual(cleanup.count("quit\r"), 2)
        self.assertEqual(cleanup.count("kjob\r"), 2)

    async def test_non_ascii_input_closes_only_that_session(self):
        socket = await self.client.ws_connect(self.server.make_url("/terminal"))
        await self.receive_until(socket, "*")
        await socket.send_str("\u00e9")
        message = await asyncio.wait_for(socket.receive(), 5)
        self.assertEqual(message.type, WSMsgType.CLOSE)
        self.assertEqual(message.data, 1007)
        await asyncio.wait_for(self.closed.get(), 5)

    async def check_browser_send_failure(self, stage):
        """Make a browser send fail while socket.closed still reports False."""
        original_send = web.WebSocketResponse.send_str
        original_connect = telnetlib3.open_connection
        attempted, failures = [], []

        async def send(socket, data, *args, **kwargs):
            attempted.append(data)
            fail = (stage == 'introduction' or
                    stage == 'gameplay' and 'look' in data or
                    stage == 'notification' and 'unavailable' in data)
            if fail:
                failures.append(socket.closed)
                raise ClientConnectionResetError('Cannot write to closing transport')
            return await original_send(socket, data, *args, **kwargs)

        async def connect(*args, **kwargs):
            reader, writer = await original_connect(*args, **kwargs)
            original_read = reader.read
            async def read(size):
                data = await original_read(size)
                if stage == 'notification' and 'look' in data:
                    raise OSError('upstream read failed')
                return data
            reader.read = read
            return reader, writer

        with patch.object(web.WebSocketResponse, 'send_str', send), \
                patch('server.gateway.telnetlib3.open_connection', connect), \
                patch('server.gateway.LOG.warning') as warnings:
            socket = await self.client.ws_connect(self.server.make_url('/terminal'))
            try:
                if stage != 'introduction':
                    await self.receive_until(socket, '*')
                    await socket.send_str('look\r')
                self.assertEqual((await asyncio.wait_for(socket.receive(), 5)).type, WSMsgType.CLOSE)
                await asyncio.wait_for(self.closed.get(), 5)
                await self.server.close()  # Wait for the entire request handler.
                self.assertEqual(self.handler_errors, [])
                self.assertEqual(failures, [False], 'The failed browser send must not be retried')
                if stage == 'notification':
                    warnings.assert_called_once()
                else:
                    warnings.assert_not_called()
                    self.assertFalse(any('unavailable' in data for data in attempted))
                commands = ''.join(self.inputs.get_nowait() for _ in range(self.inputs.qsize()))
                self.assertIn('kjob\r', commands)
                self.assertIn('\x03' if stage == 'introduction' else 'quit\r', commands)
            finally:
                await socket.close()

    async def test_browser_disconnect_during_introduction_still_logs_out(self):
        await self.check_browser_send_failure('introduction')

    async def test_browser_disconnect_during_gameplay_still_logs_out(self):
        await self.check_browser_send_failure('gameplay')

    async def test_browser_disconnect_during_failure_notification_is_best_effort(self):
        await self.check_browser_send_failure('notification')

    async def test_monitor_escape_controls_are_not_forwarded(self):
        socket = await self.client.ws_connect(self.server.make_url('/terminal'))
        await self.receive_until(socket, '*')
        await socket.send_str('\x03login richard\r')
        message = await asyncio.wait_for(socket.receive(), 5)
        self.assertEqual(message.type, WSMsgType.CLOSE)
        self.assertEqual(message.data, 1008)
        await asyncio.wait_for(self.closed.get(), 5)
        commands = ''.join(self.inputs.get_nowait() for _ in range(self.inputs.qsize()))
        self.assertNotIn('login richard', commands)

    async def test_pasted_commands_cannot_continue_after_quit(self):
        socket = await self.client.ws_connect(self.server.make_url('/terminal'))
        await self.receive_until(socket, '*')
        await socket.send_str('quit\rlogin richard\r')
        while (await asyncio.wait_for(socket.receive(), 5)).type == WSMsgType.TEXT:
            pass
        await asyncio.wait_for(self.closed.get(), 5)
        commands = ''.join(self.inputs.get_nowait() for _ in range(self.inputs.qsize()))
        self.assertNotIn('login richard', commands)

    async def test_pasted_commands_cannot_continue_after_rejected_entry(self):
        self.reject_entry = True
        socket = await self.client.ws_connect(self.server.make_url('/terminal'))
        await self.receive_until(socket, '*')
        await socket.send_str('bad\rlogin richard\r')
        while (await asyncio.wait_for(socket.receive(), 5)).type == WSMsgType.TEXT:
            pass
        await asyncio.wait_for(self.closed.get(), 5)
        commands = ''.join(self.inputs.get_nowait() for _ in range(self.inputs.qsize()))
        self.assertNotIn('login richard', commands)

    async def test_restart_waits_for_logout_before_closing_browser(self):
        socket = await self.client.ws_connect(self.server.make_url('/terminal'))
        await self.receive_until(socket, '*')
        self.allow_logout.clear()
        await socket.send_bytes(b'restart')
        closing = asyncio.create_task(socket.receive())
        try:
            await asyncio.sleep(0.1)
            self.assertFalse(closing.done(), 'Browser was closed before TOPS-10 logout')
            self.allow_logout.set()
            message = await asyncio.wait_for(closing, 5)
            self.assertEqual(message.type, WSMsgType.CLOSE)
            self.assertEqual(message.data, 1000)
            self.assertEqual(await asyncio.wait_for(self.closed.get(), 5), 1)
            commands = ''.join([await self.inputs.get() for _ in range(3)])
            self.assertIn('quit\r', commands)
            self.assertIn('kjob\r', commands)
            self.assertNotIn('restart', commands)
        finally:
            self.allow_logout.set()
            closing.cancel()
            await asyncio.gather(closing, return_exceptions=True)
            await socket.close()

    async def test_server_shutdown_logs_out_connected_browsers_promptly(self):
        sockets, readers = [], []
        async def read_close(socket):
            while True:
                message = await socket.receive()
                if message.type != WSMsgType.TEXT:
                    return message
        try:
            for _ in range(2):
                socket = await self.client.ws_connect(self.server.make_url('/terminal'))
                sockets.append(socket)
                await self.receive_until(socket, '*')
                readers.append(asyncio.create_task(read_close(socket)))
            await asyncio.wait_for(self.server.close(), 3)
            messages = await asyncio.gather(*readers)
            self.assertTrue(all(message.type == WSMsgType.CLOSE for message in messages))
            self.assertEqual({await asyncio.wait_for(self.closed.get(), 1),
                              await asyncio.wait_for(self.closed.get(), 1)}, {1, 2})
            commands = ''.join(self.inputs.get_nowait() for _ in range(self.inputs.qsize()))
            self.assertEqual(commands.count('quit\r'), 2)
            self.assertEqual(commands.count('kjob\r'), 2)
        finally:
            for socket in sockets:
                await socket.close()
            for task in readers:
                task.cancel()
            await asyncio.gather(*readers, return_exceptions=True)

    async def test_server_shutdown_preserves_logout_already_in_progress(self):
        socket = await self.client.ws_connect(self.server.make_url('/terminal'))
        await self.receive_until(socket, '*')
        self.allow_logout.clear()
        await socket.send_bytes(b'restart')
        reader = asyncio.create_task(socket.receive())
        shutdown = None
        try:
            while 'kjob\r' not in await asyncio.wait_for(self.inputs.get(), 2):
                pass
            shutdown = asyncio.create_task(self.server.close())
            await asyncio.sleep(0.1)
            self.assertFalse(shutdown.done())
            self.assertFalse(reader.done(), 'Shutdown interrupted the existing logout')
            self.allow_logout.set()
            await asyncio.wait_for(shutdown, 3)
            self.assertEqual((await reader).type, WSMsgType.CLOSE)
            self.assertEqual(await asyncio.wait_for(self.closed.get(), 1), 1)
        finally:
            self.allow_logout.set()
            reader.cancel()
            if shutdown is not None:
                shutdown.cancel()
            await asyncio.gather(reader, *([shutdown] if shutdown is not None else []), return_exceptions=True)
            await socket.close()

    async def test_bbc40_preserves_words_for_browser_wrapping(self):
        socket = await self.client.ws_connect(self.server.make_url('/terminal?style=bbc40'))
        await self.receive_until(socket, '*')
        self.assertIn('set tty width 255\r', self.terminal_setups)
        await socket.close()

    async def test_invalid_style_is_rejected(self):
        response = await self.client.get(self.server.make_url('/terminal?style=unknown'))
        self.assertEqual(response.status, 400)
        self.assertIn('Unknown terminal style', await response.text())

    async def test_legal_notices_are_served_without_opening_game_sessions(self):
        for path, expected in (('/legal', 'GPL-3.0-only'),
                               ('/legal/gpl', 'GNU GENERAL PUBLIC LICENSE'),
                               ('/legal/mud', 'exclusively for not for profit use'),
                               ('/legal/notice', 'HISTORICAL RUNTIME REVIEW IS INCOMPLETE')):
            response = await self.client.get(self.server.make_url(path))
            self.assertEqual(response.status, 200)
            self.assertIn(expected, await response.text())
        response = await self.client.get(self.server.make_url('/legal/private'))
        self.assertEqual(response.status, 404)
        self.assertEqual(self.count, 0)

    async def test_vt52_mda_and_cga_use_80_column_upstream(self):
        for style in ('vt52', 'mda', 'cga'):
            socket = await self.client.ws_connect(self.server.make_url('/terminal?style=' + style))
            await self.receive_until(socket, '*')
            self.assertEqual(self.terminal_setups[-1], 'set tty width 80\r')
            await socket.close()

    async def test_simh_linemode_offer_and_extra_prompt_newline(self):
        received = asyncio.Queue()

        async def simh(reader, writer):
            try:
                writer.write(b'\xff\xfb\x22\r\n\n.')  # SIMH's WILL LINEMODE
                setup = await reader.readuntil(b"set tty type vt100\r")
                writer.write(b"\r\n.")
                await reader.readuntil(b"set tty width 80\r")
                writer.write(b"\r\n.")
                data = await reader.readuntil(b"login mudguest\r")
                await received.put(setup + data)
                writer.write(b"By what name shall I call you?\r\nSIMH READY")
                await reader.read(100)
                writer.write(b"\r\n.")
                await reader.readuntil(b"kjob\r")
                writer.write(b"Logged-off")
            finally:
                writer.close()
                await writer.wait_closed()

        backend = await asyncio.start_server(simh, "127.0.0.1", 0)
        server = TestServer(create_app(upstream_port=backend.sockets[0].getsockname()[1]))
        await server.start_server()
        try:
            socket = await self.client.ws_connect(server.make_url("/terminal"))
            self.assertIn("SIMH READY", await self.receive_until(socket, "READY"))
            self.assertIn(b'\xff\xfe\x22', await asyncio.wait_for(received.get(), 5))
            await socket.close()
        finally:
            await server.close()
            backend.close()
            await backend.wait_closed()

    async def test_stale_upstream_session_is_not_exposed_to_a_new_browser(self):
        async def stale(reader, writer):
            writer.write(b"\r\n.")
            await reader.readuntil(b"set tty type vt100\r")
            writer.write(b"\r\n.")
            await reader.readuntil(b"set tty width 80\r")
            writer.write(b"\r\n.")
            await reader.readuntil(b"login mudguest\r")
            writer.write(b"Former player's private conversation.\r\n*")
            await writer.drain()
            writer.close()

        backend = await asyncio.start_server(stale, "127.0.0.1", 0)
        server = TestServer(create_app(upstream_port=backend.sockets[0].getsockname()[1]))
        await server.start_server()
        try:
            socket = await self.client.ws_connect(server.make_url("/terminal"))
            message = await asyncio.wait_for(socket.receive(), 5)
            self.assertEqual(message.type, WSMsgType.TEXT)
            self.assertNotIn("private conversation", message.data)
            self.assertIn("unavailable", message.data)
            await socket.close()
        finally:
            await server.close()
            backend.close()
            await backend.wait_closed()


if __name__ == "__main__":
    unittest.main()
