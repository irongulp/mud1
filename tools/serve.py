"""Start the local browser gateway in the background, with a log and PID file."""
import socket
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    for name in ("xterm.js", "xterm.css", "LICENSE"):
        if not (ROOT / "web/vendor" / name).is_file():
            raise FileNotFoundError("Run python3 tools/fetch_terminal.py first")
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", 8080)) == 0:
            raise RuntimeError("Port 8080 is already in use")
    with (ROOT / "runtime/web.log").open("ab") as log:
        process = subprocess.Popen([str(ROOT / ".venv/bin/python"), "-m", "server.gateway"],
                                   cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log,
                                   stderr=log, start_new_session=True)
    (ROOT / "runtime/web.pid").write_text(str(process.pid) + "\n")
    for _ in range(50):
        if process.poll() is not None:
            raise RuntimeError("Gateway exited; see runtime/web.log")
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", 8080)) == 0:
                print(f"http://127.0.0.1:8080 (gateway PID {process.pid})")
                return
        time.sleep(0.1)
    raise TimeoutError("Gateway did not start; see runtime/web.log")


if __name__ == "__main__":
    main()
