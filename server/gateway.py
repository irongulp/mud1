"""Browser terminal transport for the original MUD86 executable."""
import argparse
import asyncio
import logging
import re
from pathlib import Path
from urllib.parse import urlsplit

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


def create_app(upstream_host="127.0.0.1", upstream_port=2020):
    app = web.Application()

    async def terminal(request):
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
        tasks = []
        entered = False
        monitor = False
        authenticated = False
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
            writer.write("\r")
            await asyncio.wait_for(reader.readuntil(b"."), CONNECT_TIMEOUT)
            # Telnet's terminal name does not configure TOPS-10's local DZ TTY.
            # Select display editing rather than printing-terminal rubout echo.
            writer.write("set tty type vt100\r")
            await asyncio.wait_for(reader.readuntil(b"."), CONNECT_TIMEOUT)
            # NAWS alone does not configure the emulated local DZ terminal.
            # Always restore width: a reused line may have served word-wrap mode.
            writer.write(f"set tty width {columns}\r")
            await asyncio.wait_for(reader.readuntil(b"."), CONNECT_TIMEOUT)
            writer.write("login mudguest\r")
            introduction = await asyncio.wait_for(
                reader.readuntil(b"By what name shall I call you?"), CONNECT_TIMEOUT)
            authenticated = True
            await socket.send_str(introduction.decode("ascii"))

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
                    await socket.send_str(data)
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
        except (OSError, EOFError, asyncio.TimeoutError, asyncio.IncompleteReadError,
                asyncio.LimitOverrunError) as error:
            LOG.warning("Terminal connection ended: %s", error)
            if not socket.closed:
                await socket.send_str("\r\n[The original MUD server is unavailable. Please reconnect.]\r\n")
                await socket.close(code=1013)
        finally:
            password_input.clear()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if writer is not None:
                # Keep the physical line occupied until QUIT and the TOPS-10
                # logout finish. Closing TCP alone leaves local TTY jobs alive.
                try:
                    if authenticated and not monitor:
                        writer.write("\x15quit\r" if entered else "\x03" * 4)
                        await asyncio.wait_for(reader.readuntil(b"\n."), LOGOUT_TIMEOUT)
                    if authenticated:
                        writer.write("kjob\r")
                        await asyncio.wait_for(reader.readuntil(b"Logged-off"), LOGOUT_TIMEOUT)
                except (OSError, EOFError, asyncio.TimeoutError, asyncio.IncompleteReadError):
                    LOG.warning("Terminal logout did not complete; check the guest job")
                writer.close()
                await writer.wait_closed()
            await socket.close()
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
