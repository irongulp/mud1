"""Exercise two browser-protocol sessions against the actual original game."""
import asyncio
import secrets
import string
from pathlib import Path

from aiohttp import ClientSession, WSMsgType
from aiohttp.test_utils import TestServer

from server.gateway import create_app

ROOT = Path(__file__).resolve().parents[1]


class Browser:
    def __init__(self, socket, name, log):
        self.socket, self.name, self.log = socket, name, log
        self.buffer = ""

    async def expect(self, marker):
        while marker not in self.buffer:
            message = await asyncio.wait_for(self.socket.receive(), 20)
            if message.type != WSMsgType.TEXT:
                raise AssertionError(f"{self.name}: connection ended before {marker!r}: {message}")
            self.log.write(f"[{self.name}] {message.data}")
            self.log.flush()
            self.buffer += message.data
        end = self.buffer.index(marker) + len(marker)
        result, self.buffer = self.buffer[:end], self.buffer[end:]
        return result

    async def send(self, text):
        await self.socket.send_str(text + "\r")

    async def enter(self):
        await self.expect("By what name shall I call you?")
        await self.send(self.name)
        await self.expect("What sex do you wish to be?")
        await self.send("m")
        await self.expect("letters, please.")
        await self.send("testpass")
        await self.expect("Hello, " + self.name)
        await self.expect("\n*")


async def main():
    server = TestServer(create_app())
    await server.start_server()
    players = []
    try:
        async with ClientSession() as client:
            for path in ("/", "/static/terminal.js", "/static/style.css", "/static/vendor/xterm.js", "/static/vendor/xterm.css"):
                async with client.get(server.make_url(path)) as response:
                    assert response.status == 200, path
                    await response.read()
            with (ROOT / "runtime/browser-multiplayer.log").open("w") as log:
                try:
                    for _ in range(2):
                        name = "Web" + "".join(secrets.choice(string.ascii_lowercase) for _ in range(5))
                        socket = await client.ws_connect(server.make_url("/terminal"))
                        player = Browser(socket, name, log)
                        players.append(player)
                        await player.enter()
                    for player in players:
                        await player.send("who")
                        await player.expect("who")
                        response = await player.expect("\n*")
                        assert all(p.name in response for p in players), response
                    marker = "Browserproof" + secrets.token_hex(3)
                    await players[0].send("shout " + marker)
                    await players[1].expect(marker)
                    print("PASS: HTTP assets + two WebSocket players share the original MUD world", flush=True)
                    for player in players:
                        await player.send("quit")
                        await player.expect("\r\n.")
                        await player.socket.close()
                    dropped = Browser(await client.ws_connect(server.make_url("/terminal")),
                                      "Drop" + secrets.choice(string.ascii_lowercase) + secrets.choice(string.ascii_lowercase), log)
                    players.append(dropped)
                    await dropped.enter()
                    await asyncio.wait_for(dropped.socket.close(), 10)
                    replacement = Browser(await client.ws_connect(server.make_url("/terminal")),
                                          "Next" + secrets.choice(string.ascii_lowercase) + secrets.choice(string.ascii_lowercase), log)
                    players.append(replacement)
                    await replacement.enter()
                    await replacement.send("quit")
                    await replacement.expect("\r\n.")
                    print("PASS: a dropped browser does not leak its persona to the next connection", flush=True)
                finally:
                    for player in players:
                        await player.socket.close()
    finally:
        await server.close()


if __name__ == "__main__":
    asyncio.run(main())
