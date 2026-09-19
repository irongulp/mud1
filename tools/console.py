"""Local restoration console: persistent PTY, command batches, and a transcript.

This is an operator/development tool, not a player-facing server.
"""
import argparse
import json
import os
import pty
import select
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime"
SOCKET = RUNTIME / "operator.sock"
CONFIG = Path(os.environ.get("SIMH_CONFIG", str(ROOT / "config/pdp10.ini"))).resolve()


def daemon():
    pid, terminal = pty.fork()
    if pid == 0:
        os.chdir(RUNTIME)
        executable = os.environ.get("SIMH_BIN", str(ROOT / "upstream/simh/BIN/pdp10"))
        os.execl(executable, "pdp10", str(CONFIG))
    pending = bytearray()
    server = socket.socket(socket.AF_UNIX)
    server.bind(str(SOCKET))
    os.chmod(SOCKET, 0o600)
    server.listen(1)
    try:
        with (RUNTIME / "console.log").open("ab", buffering=0) as log:
            while True:
                ready, _, _ = select.select([terminal, server], [], [])
                if terminal in ready:
                    try:
                        data = os.read(terminal, 65536)
                    except OSError:
                        break
                    if not data:
                        break
                    pending.extend(data)
                    log.write(data)
                if server in ready:
                    connection, _ = server.accept()
                    with connection:
                        with connection.makefile("rb") as stream:
                            request = json.loads(stream.readline())
                        os.write(terminal, request["input"].encode("ascii"))
                        deadline = time.monotonic() + request["wait"]
                        while time.monotonic() < deadline:
                            readable, _, _ = select.select([terminal], [], [], max(0, deadline - time.monotonic()))
                            if readable:
                                try:
                                    data = os.read(terminal, 65536)
                                except OSError:
                                    break
                                if not data:
                                    break
                                pending.extend(data)
                                log.write(data)
                        try:
                            connection.sendall(pending)
                            connection.shutdown(socket.SHUT_WR)
                        except BrokenPipeError:
                            continue
                        pending.clear()
    finally:
        server.close()
        SOCKET.unlink(missing_ok=True)
        os.close(terminal)
        os.waitpid(pid, 0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", action="store_true")
    parser.add_argument("--daemon", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--send", default="", help=r"Input with \r, \x03, \x05 escapes")
    parser.add_argument("--wait", type=float, default=2)
    args = parser.parse_args()
    if args.daemon:
        daemon()
        return
    if args.start:
        if SOCKET.exists():
            parser.error("Operator socket already exists; use the existing session")
        RUNTIME.mkdir(exist_ok=True)
        with (RUNTIME / "operator.log").open("ab") as log:
            subprocess.Popen([sys.executable, __file__, "--daemon"], stdin=subprocess.DEVNULL,
                             stdout=log, stderr=log, start_new_session=True)
        for _ in range(100):
            if SOCKET.exists():
                break
            time.sleep(0.1)
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(args.wait + 10)
        client.connect(str(SOCKET))
        text = args.send.encode("ascii").decode("unicode_escape")
        client.sendall((json.dumps({"input": text, "wait": args.wait}) + "\n").encode())
        while True:
            data = client.recv(65536)
            if not data:
                break
            sys.stdout.write(data.decode("ascii", errors="replace"))


if __name__ == "__main__":
    main()
