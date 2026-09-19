"""Opt-in test against the original running MUD, using Python 3.9–3.12.

Creates two disposable personas, verifies shared player lists and speech,
then quits both. Run only against the local restoration instance.
"""
import argparse
import secrets
import string
import telnetlib
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TIMEOUT = 20


class Player:
    def __init__(self, login, name, log, autostart=True):
        self.name = name
        self.log = log
        self.connection = telnetlib.Telnet("127.0.0.1", 2020, TIMEOUT)
        self.in_game = False
        try:
            self.send("")
            self.expect(b".")
            self.send("login " + login)
            if not autostart:
                self.expect(b"\r\n.")
                self.send("run mud[2011,2776]")
            self.expect(b"By what name shall I call you?")
            self.send(name)
            self.expect(b"What sex do you wish to be?")
            self.send("m")
            self.expect(b"letters, please.")
            self.send("testpass")
            self.expect(("Hello, " + name).encode())
            self.expect(b"\n*")
            self.in_game = True
        except Exception:
            self.connection.close()
            raise

    def send(self, command):
        self.connection.write(command.encode("ascii") + b"\r\n")

    def expect(self, marker):
        data = self.connection.read_until(marker, TIMEOUT)
        self.log.write(b"[" + self.name.encode() + b"] " + data + b"\n")
        self.log.flush()
        if marker not in data:
            raise AssertionError(f"{self.name}: expected {marker!r}, got {data!r}")
        return data

    def close(self):
        try:
            if self.in_game:
                self.send("quit")
                self.expect(b"\r\n.")
            self.send("kjob")
            time.sleep(0.5)
        finally:
            self.connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--login", default="mudguest", help="Password-free local TOPS-10 test account")
    parser.add_argument("--manual-run", action="store_true", help="For accounts without auto-start")
    args = parser.parse_args()
    names = ["Test" + "".join(secrets.choice(string.ascii_lowercase) for _ in range(5)) for _ in range(2)]
    players = []
    with (ROOT / "runtime/multiplayer.log").open("wb") as log:
        try:
            for name in names:
                players.append(Player(args.login, name, log, not args.manual_run))
            for player in players:
                player.send("who")
                # Arrival messages can introduce a prompt before this command's
                # response. Synchronize on the command echo, not any old prompt.
                player.expect(b"who")
                output = player.expect(b"\n*")
                for name in names:
                    if name.encode() not in output:
                        raise AssertionError(f"{player.name}: shared WHO missing {name}: {output!r}")
            marker = "Sharedworld" + "".join(secrets.choice(string.ascii_lowercase) for _ in range(6))
            players[0].send("shout " + marker)
            players[1].expect(marker.encode())
            print("PASS: two original MUD sessions share WHO and receive cross-player speech")
        finally:
            for player in players:
                player.close()


if __name__ == "__main__":
    main()
