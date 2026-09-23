"""Browser terminal transport for the original MUD86 executable."""
import argparse
import asyncio
import logging
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import telnetlib3
from telnetlib3.stream_writer import TelnetWriterUnicode
from telnetlib3.telopt import DONT, LINEMODE
from aiohttp import WSMsgType, web

from server.password_input import PasswordInput

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
LEGAL_DOCUMENTS = {
    'gpl': 'COPYING', 'scope': 'LICENSE', 'notice': 'NOTICE',
    'mud': 'licenses/MUD1-NOTICE.txt', 'third-party': 'THIRD_PARTY.md',
    'dec': 'licenses/DEC-HOBBYIST.txt', 'bcpl': 'licenses/BCPL-STATUS.md',
    'simh': 'licenses/SIMH.txt',
}
CONNECT_TIMEOUT = 15
TERMINAL_COLUMNS = 80
TERMINAL_ROWS = 30
# The 40-column browser reflows prose itself. Avoid monitor-inserted breaks
# inside words before it receives the original game's lines (usually <=80).
WORD_WRAP_UPSTREAM_COLUMNS = 255
TERMINAL_STYLES = {
    "original": (TERMINAL_COLUMNS, TERMINAL_ROWS),
    "chat": (TERMINAL_COLUMNS, TERMINAL_ROWS),
    "vt220": (80, 24),
    "vt52": (80, 24),
    "mda": (80, 25),
    "cga": (80, 25),
    "bbc40": (40, 25),
    "bbc0": (80, 32),
}
READ_SIZE = 4096
MAX_INPUT_SIZE = 8192
LOGOUT_TIMEOUT = 3
INTERRUPT_SEQUENCE = "\x03" * 4  # Controlled TOPS-10 monitor recovery, never browser input.
SAFE_CONTROLS = frozenset('\b\t\n\r\x12\x15\x17')
GAME_PROMPT = re.compile(r'(?:^|[\r\n])\(?(?:----)?[*>"]\)?$')
LOG = logging.getLogger(__name__)


class SimhWriter(TelnetWriterUnicode):
    def handle_will(self, option):
        # SIMH offers WILL LINEMODE, whereas RFC 1184 places that offer on
        # the client. Decline it and keep character-at-a-time terminal I/O.
        if option == LINEMODE:
            self.iac(DONT, option)
            self.remote_option[option] = False
            return
        return super().handle_will(option)


class SimhClient(telnetlib3.TelnetClient):
    _writer_factory_encoding = SimhWriter

    def begin_negotiation(self):
        if not self._closing:
            super().begin_negotiation()

    def data_received(self, data):
        if not self._closing:
            super().data_received(data)

    def _process_chunk(self, data):
        # 2.0.8's chunk scanner starts in text mode, even when the preceding
        # chunk ended inside an IAC command. Complete that command first.
        offset = 0
        while offset < len(data) and self.writer.is_oob:
            byte = data[offset:offset + 1]
            try:
                inband = self.writer.feed_byte(byte)
            except Exception:
                self._log_exception(self.log.warning, *sys.exc_info())
            else:
                if inband:
                    self.reader.feed_data(byte)
            offset += 1
        return super()._process_chunk(data[offset:]) or bool(offset)

    def connection_lost(self, exc):
        if self._closing:
            return
        # telnetlib3 2.0.8 signals EOF before its queued receive task has run.
        # Finish already-received bytes synchronously, while the Telnet parser
        # and writer callbacks still exist, so final output/Logged-off survives.
        # The event loop cannot run _process_rx concurrently with this callback.
        if self._rx_task is not None:
            self._rx_task.cancel()
            self._rx_task = None
        try:
            while self._rx_queue:
                chunk = self._rx_queue.popleft()
                self._rx_bytes -= len(chunk)
                self._process_chunk(chunk)
        except Exception as error:
            # A parser failure is a real read error, not a successful EOF.
            exc = exc or error
        finally:
            self._rx_queue.clear()
            self._rx_bytes = 0
            super().connection_lost(exc)


class BrowserDisconnected(Exception):
    """Browser-side send failure; the guest still needs its normal cleanup."""


async def send_browser(socket, data):
    try:
        await socket.send_str(data)
    except OSError as error:
        # WebSocket.closed can still be False while its transport is closing.
        # Keep this distinct from upstream OSErrors handled by the gateway.
        raise BrowserDisconnected() from error


async def logout_guest(reader, writer, *, entered, monitor, connection_id):
    """Bounded QUIT -> monitor recovery -> KJOB; callers own the TTY until done."""
    stage = 'quit' if entered else 'interrupt'
    recovered = False
    try:
        if not monitor and entered:
            writer.write("\x15quit\r")
            try:
                await asyncio.wait_for(reader.readuntil(b"\n."), LOGOUT_TIMEOUT)
                monitor = True
            except asyncio.TimeoutError:
                # QUIT can be an answer to a question rather than a command.
                # Do not send any OS command until interrupt reaches a monitor.
                recovered = True
                LOG.info("Terminal cleanup recovery: connection=%s stage=quit error=TimeoutError", connection_id)
        if not monitor:
            stage = 'interrupt'
            writer.write(INTERRUPT_SEQUENCE)
            await asyncio.wait_for(reader.readuntil(b"\n."), LOGOUT_TIMEOUT)
        stage = 'logout'
        writer.write("kjob\r")
        await asyncio.wait_for(reader.readuntil(b"Logged-off"), LOGOUT_TIMEOUT)
        LOG.info("Terminal logout complete: connection=%s recovered=%s", connection_id, recovered)
    except (OSError, EOFError, asyncio.TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError) as error:
        # No raw terminal output, persona names, or exception payloads here.
        LOG.warning("Terminal logout did not complete; check the guest job: connection=%s stage=%s error=%s",
                    connection_id, stage, type(error).__name__)


def create_app(upstream_host="127.0.0.1", upstream_port=2020):
    app = web.Application()
    terminal_handlers = set()
    terminal_cleanups = set()
    shutting_down = False

    async def terminal(request):
        if shutting_down:
            raise web.HTTPServiceUnavailable(text="Gateway is shutting down")
        handler = asyncio.current_task()
        terminal_handlers.add(handler)
        try:
            return await terminal_session(request)
        finally:
            terminal_handlers.discard(handler)
            terminal_cleanups.discard(handler)

    async def shutdown_terminals(app):
        nonlocal shutting_down
        shutting_down = True
        handlers = tuple(terminal_handlers)
        for handler in handlers:
            # Cancel active transport/setup, which enters its normal finally
            # block. Never interrupt a QUIT/KJOB already underway.
            if handler not in terminal_cleanups:
                handler.cancel()
        await asyncio.gather(*handlers, return_exceptions=True)

    async def terminal_session(request):
        style = request.query.get("style", "original")
        if style not in TERMINAL_STYLES:
            raise web.HTTPBadRequest(text="Unknown terminal style")
        columns, rows = TERMINAL_STYLES[style]
        if style == "bbc40":
            columns = WORD_WRAP_UPSTREAM_COLUMNS
        origin = request.headers.get("Origin")
        if origin and urlsplit(origin).netloc != request.host:
            raise web.HTTPForbidden(text="Terminal connections must originate from this site")
        socket = web.WebSocketResponse(heartbeat=30, max_msg_size=MAX_INPUT_SIZE)
        await socket.prepare(request)
        writer = None
        close_code = 1000
        tasks = []
        entered = False
        monitor = False
        login_started = False
        connection_id = uuid4().hex
        stage = 'connect'
        LOG.info("Terminal session started: connection=%s style=%s", connection_id, style)
        password_input = PasswordInput()
        input_ready = asyncio.Event()
        try:
            reader, writer = await asyncio.wait_for(telnetlib3.open_connection(
                host=upstream_host, port=upstream_port, term="vt100", encoding="ascii",
                client_factory=SimhClient,
                cols=columns, rows=rows,
                connect_minwait=0.1, connect_maxwait=1), CONNECT_TIMEOUT)
            # TOPS-10 treats CR and LF as separate input terminators. A trailing
            # LF after LOGIN reaches MUD as an empty name and repeats its prompt.
            stage = 'monitor'
            writer.write("\r")
            await asyncio.wait_for(reader.readuntil(b"."), CONNECT_TIMEOUT)
            # Telnet's terminal name does not configure TOPS-10's local DZ TTY.
            # Select display editing rather than printing-terminal rubout echo.
            stage = 'terminal-type'
            writer.write("set tty type vt100\r")
            await asyncio.wait_for(reader.readuntil(b"."), CONNECT_TIMEOUT)
            # NAWS alone does not configure the emulated local DZ terminal.
            # Always restore width: a reused line may have served word-wrap mode.
            stage = 'terminal-width'
            writer.write(f"set tty width {columns}\r")
            await asyncio.wait_for(reader.readuntil(b"."), CONNECT_TIMEOUT)
            stage = 'login'
            login_started = True
            writer.write("login mudguest\r")
            introduction = await asyncio.wait_for(
                reader.readuntil(b"By what name shall I call you?"), CONNECT_TIMEOUT)
            await send_browser(socket, introduction.decode("ascii"))
            stage = 'transport'

            async def to_browser():
                nonlocal entered, monitor
                recent = ""
                while True:
                    data = await reader.read(READ_SIZE)
                    if not data:
                        return
                    recent = (recent + data)[-256:]
                    if re.search(r"Hello(?: again)?,", recent):
                        entered = True
                        password_input.clear()
                    if not entered:
                        password_input.observe(data)
                    monitor = recent.endswith("\n.")
                    await send_browser(socket, data)
                    if monitor:
                        return
                    if GAME_PROMPT.search(recent) or recent.replace('\r', '').endswith(
                            "What's the password for this persona?\n"):
                        input_ready.set()

            async def to_game():
                async for message in socket:
                    if message.type == WSMsgType.TEXT:
                        if not message.data.isascii():
                            await socket.close(code=1007, message=b"MUD86 uses a 7-bit terminal")
                            return
                        if any(ord(char) < 32 and char not in SAFE_CONTROLS for char in message.data):
                            await socket.close(code=1008, message=b"Unsupported terminal control")
                            return
                        try:
                            data = password_input.feed(message.data)
                        except ValueError:
                            await socket.close(code=1009, message=b"Password input line too long")
                            return
                        # Never pipeline another line past a game exit or rejected
                        # login into the operating-system monitor. Disconnects
                        # cancel the blocked sender before QUIT/KJOB cleanup.
                        for part in re.findall(r'[^\r\n]*[\r\n]|[^\r\n]+$', data):
                            await input_ready.wait()
                            writer.write(part)
                            if part.endswith(('\r', '\n')):
                                input_ready.clear()
                            await writer.drain()
                    elif message.type == WSMsgType.BINARY:
                        # Reserved browser control frame; never forward to MUD.
                        # Returning runs QUIT/KJOB before finally closes the socket.
                        if message.data == b"restart":
                            return
                        await socket.close(code=1003, message=b"Text terminal input required")
                        return
                    elif message.type == WSMsgType.ERROR:
                        return

            tasks = [asyncio.create_task(to_browser()), asyncio.create_task(to_game())]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except BrowserDisconnected:
            LOG.info("Browser terminal disconnected during output: connection=%s stage=%s", connection_id, stage)
        except (OSError, EOFError, asyncio.TimeoutError, asyncio.IncompleteReadError,
                asyncio.LimitOverrunError) as error:
            LOG.warning("Terminal connection ended: connection=%s stage=%s upstream %s",
                        connection_id, stage, type(error).__name__)
            if not socket.closed:
                try:
                    await send_browser(socket, "\r\n[The original MUD server is unavailable. Please reconnect.]\r\n")
                except BrowserDisconnected:
                    pass  # Best-effort notification; guest cleanup must still run.
                else:
                    close_code = 1013
        finally:
            terminal_cleanups.add(asyncio.current_task())
            password_input.clear()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if writer is not None:
                # Keep the physical line occupied until QUIT and the TOPS-10
                # logout finish. Closing TCP alone leaves local TTY jobs alive.
                if login_started:
                    # LOGIN may have allocated a job even if its game prompt
                    # timed out, so successful introduction is not a prerequisite.
                    await logout_guest(reader, writer, entered=entered, monitor=monitor,
                                       connection_id=connection_id)
                writer.close()
                await writer.wait_closed()
            await socket.close(code=close_code)
        return socket

    async def index(request):
        return web.FileResponse(WEB / "index.html")

    async def legal_page(request):
        return web.FileResponse(WEB / 'legal.html')

    async def legal_document(request):
        name = request.match_info['document']
        if name not in LEGAL_DOCUMENTS:
            raise web.HTTPNotFound()
        return web.FileResponse(ROOT / LEGAL_DOCUMENTS[name],
                                headers={'Content-Type': 'text/plain; charset=utf-8'})

    app.on_shutdown.append(shutdown_terminals)
    app.router.add_get("/", index)
    app.router.add_get('/legal', legal_page)
    app.router.add_get('/legal/{document}', legal_document)
    app.router.add_get("/terminal", terminal)
    app.router.add_static("/static/", WEB)
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--upstream-host", default="127.0.0.1")
    parser.add_argument("--upstream-port", type=int, default=2020)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    web.run_app(create_app(args.upstream_host, args.upstream_port), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
