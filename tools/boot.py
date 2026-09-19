"""Boot the prepared TOPS-10 disk at an explicit test clock."""
import argparse
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Experimental wait used by isolated benchmarks; it does not resolve every
# observed startup stall. Keep the established live boot behavior as default.
BOOT_CALIBRATION_SECONDS = 22


def exchange(text="", wait=0.2):
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(wait + 10)
        connection.connect(str(ROOT / "runtime/operator.sock"))
        connection.sendall((json.dumps({"input": text, "wait": wait}) + "\n").encode())
        data = bytearray()
        while True:
            chunk = connection.recv(65536)
            if not chunk:
                return data.decode("ascii", errors="replace")
            data.extend(chunk)


def expect(marker, initial="", timeout=30):
    output = initial
    deadline = time.monotonic() + timeout
    while marker not in output:
        if time.monotonic() > deadline:
            raise TimeoutError(f"Waiting for {marker!r}: {output}")
        output += exchange()
    print(marker, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default="09-18-2026")
    parser.add_argument("--time", default="030000")
    parser.add_argument("--monitor", default="/tm02")
    parser.add_argument("--startup", default="g", choices=("g", "noinit", "quick"))
    parser.add_argument("--settle", type=float, default=0,
                        help="Seconds for timer calibration before starting system jobs")
    args = parser.parse_args()
    if args.settle < 0:
        parser.error("--settle cannot be negative")
    initial = subprocess.check_output([sys.executable, str(ROOT / "tools/console.py"),
                                       "--start", "--wait", "1"], text=True)
    expect("BOOT>", initial)
    expect("Why reload:", exchange("\x15" + args.monitor + "\r"))
    expect("Date:", exchange("sched\r"))
    expect("Time:", exchange(args.date + "\r"))
    expect("Startup option:", exchange(args.time + "\r"))
    time.sleep(args.settle)
    expect("To automatically log in" if args.startup == "noinit" else "OPR>",
           exchange(args.startup + "\r"))
    print("TOPS-10 ready; terminal port is 127.0.0.1:2020")


if __name__ == "__main__":
    main()
