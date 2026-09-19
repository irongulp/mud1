"""Compare SIMH idle modes on an isolated copy of the first-playable disk.

Run with the development requirements installed. Neither the live emulator nor
its disk is touched. Reports measure CPU seconds per host elapsed second, not
the smoothed percentage printed by ps. Tests use actual browser-protocol players.
"""
import argparse
import asyncio
import json
import math
import os
import re
import secrets
import shutil
import socket
import statistics
import subprocess
import sys
import time
from pathlib import Path

from tools.boot import BOOT_CALIBRATION_SECONDS

ROOT = Path(__file__).resolve().parents[1]
DAY_SECONDS = 24 * 60 * 60
DEFAULT_SECONDS = 90
DEFAULT_WARMUP = 30
COMMAND_INTERVAL = 5
TIMEOUT = 30
CLOCK_TOLERANCE_SECONDS = 1.5  # DAYTIME is displayed only to the nearest second.
SLEEP_TOLERANCE_SECONDS = 1
DAEMON_TOLERANCE_SECONDS = 1.5
LATENCY_TOLERANCE_SECONDS = 0.3
MAX_TERMINAL_SPEED_FACTOR = 32  # SIMH tmxr_set_line_speed's supported maximum.


def cpu_seconds(value):
    match = re.fullmatch(r"(?:(\d+)-)?(?:(\d+):)?(\d+):(\d+(?:\.\d+)?)", value.strip())
    if not match:
        raise ValueError("Invalid ps CPU time: " + value)
    days, hours, minutes, seconds = match.groups()
    return int(days or 0) * DAY_SECONDS + int(hours or 0) * 3600 + int(minutes) * 60 + float(seconds)


def guest_seconds(output):
    matches = re.findall(r"\b\w+\s+\d+-[A-Za-z]+-\d+\s+(\d{1,2}):(\d{2}):(\d{2})", output)
    if not matches:
        raise ValueError("No TOPS-10 DAYTIME response: " + repr(output))
    hours, minutes, seconds = map(int, matches[-1])
    if hours >= 24 or minutes >= 60 or seconds >= 60:
        raise ValueError("Invalid guest clock")
    return hours * 3600 + minutes * 60 + seconds


def metrics(start, end, latencies, rss_samples):
    elapsed = end["wall"] - start["wall"]
    consumed = end["cpu"] - start["cpu"]
    if elapsed <= 0 or consumed < 0:
        raise ValueError("Invalid CPU counter window")
    guest_elapsed = (end["guest"] - start["guest"]) % DAY_SECONDS
    ordered = sorted(latencies)
    return {
        "host_elapsed_seconds": round(elapsed, 3),
        "cpu_seconds": round(consumed, 3),
        "cpu_percent_one_core": round(100 * consumed / elapsed, 3),
        "guest_elapsed_seconds": guest_elapsed,
        "clock_error_seconds": round(guest_elapsed - elapsed, 3),
        "peak_rss_kib": max([start["rss_kib"], end["rss_kib"]] + rss_samples),
        "commands": len(ordered),
        "latency_median_seconds": round(statistics.median(ordered), 4) if ordered else None,
        "latency_p95_seconds": round(ordered[math.ceil(len(ordered) * .95) - 1], 4) if ordered else None,
        "latency_max_seconds": round(max(ordered), 4) if ordered else None,
    }


def process_sample(pid):
    before = time.monotonic()
    output = subprocess.check_output(["ps", "-p", str(pid), "-o", "time=", "-o", "rss="], text=True)
    cpu, rss = output.split()
    return {"wall": (before + time.monotonic()) / 2, "cpu": cpu_seconds(cpu), "rss_kib": int(rss)}


def validate_comparison(report):
    """Reject timing regressions; CPU sizing remains an explicit host-specific judgment."""
    if not report.get("complete") or not {"idle", "noidle"} <= report["modes"].keys():
        raise AssertionError("A complete two-mode comparison is required")
    baseline, idle = report["modes"]["noidle"], report["modes"]["idle"]
    for label in ("empty", "two_quiet", "two_active", "eight_active"):
        for mode in (baseline, idle):
            if abs(mode["scenarios"][label]["clock_error_seconds"]) > CLOCK_TOLERANCE_SECONDS:
                raise AssertionError(f"Guest clock drift in {label}")
        previous = baseline["scenarios"][label]["latency_p95_seconds"]
        current = idle["scenarios"][label]["latency_p95_seconds"]
        if previous is not None and (current is None or current > previous + LATENCY_TOLERANCE_SECONDS):
            raise AssertionError(f"Command latency regression in {label}")
    sleep_delta = statistics.median(idle["timing"]["sleep_wake_seconds"]) - statistics.median(baseline["timing"]["sleep_wake_seconds"])
    if abs(sleep_delta) > SLEEP_TOLERANCE_SECONDS:
        raise AssertionError("Original sleep/wake timing changed")
    if abs(idle["timing"]["fall_daemon_seconds"] - baseline["timing"]["fall_daemon_seconds"]) > DAEMON_TOLERANCE_SECONDS:
        raise AssertionError("Original falling daemon timing changed")


class Emulator:
    def __init__(self, directory, mode, reuse=False, speed_factor=1):
        if not 1 <= speed_factor <= MAX_TERMINAL_SPEED_FACTOR:
            raise ValueError("Terminal speed factor must be between 1 and 32")
        import pexpect

        self.directory = directory
        directory.mkdir(exist_ok=reuse)
        if not reuse:
            with (ROOT / "runtime/checkpoints/first-playable/tops10-704.dsk").open("rb") as source:
                with (directory / "guest.dsk").open("xb") as target:
                    shutil.copyfileobj(source, target)
        elif not (directory / "guest.dsk").is_file():
            raise FileNotFoundError(directory / "guest.dsk")
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        config = directory / "pdp10.ini"
        config.write_text(
            "set tim y2k\nset dz 8b\nattach -e rp0 guest.dsk\n"
            f"attach -am dz 127.0.0.1:{self.port},SPEED=*{speed_factor}\nset tu0 locked\n"
            f'attach -e tu0 "{ROOT / "runtime/media/t10boot.tap"}"\n'
            f"set cpu {mode}\nboot tu0\n")
        self.log = (directory / "console.log").open("a" if reuse else "w")
        self.child = pexpect.spawn(str(ROOT / "upstream/simh/BIN/pdp10"), [str(config)],
                                   cwd=str(directory), encoding="ascii", codec_errors="replace",
                                   timeout=TIMEOUT, dimensions=(40, 120))
        self.child.logfile_read = self.log
        self.child.delaybeforesend = 0.05

    def boot(self):
        for prompt, answer in (("BOOT>", "/tm02"), ("Why reload:", "sched"),
                               ("Date:", "09-18-2026"), ("Time:", "030000"),
                               ("Startup option:", "g"), ("OPR>", "exit")):
            self.child.expect_exact(prompt)
            if prompt == "Startup option:":
                # Let the emulator's timer calibrate before launching system
                # jobs. Fast cold boots have also stalled with NOIDLE.
                time.sleep(BOOT_CALIBRATION_SECONDS)
            self.child.send(answer + "\r")
        self.child.expect(r"\n\.")

    def command(self, text, prompt=r"\n\."):
        self.child.send(text + "\r")
        self.child.expect(prompt)
        self.log.flush()
        return self.child.before + self.child.after

    def point(self):
        clock = guest_seconds(self.command("daytime"))
        return dict(process_sample(self.child.pid), guest=clock)

    def place_umbrella(self):
        """Set up the falling-daemon fixture using original archwizard commands."""
        self.command("kjob")
        self.command("login richard")
        self.child.send("run mud\r")
        self.child.expect_exact("By what name shall I call you?")
        self.child.send("Richard\r")
        self.child.expect_exact("letters, please.")
        self.child.send("testpass\r")
        self.child.expect(r"\n----\*")
        for command in ("go wrdbe", "get umbrella", "go start", "drop umbrella"):
            self.command(command, r"\n----\*")
        self.command("quit")

    def stop(self):
        # This is exclusively the disposable test machine. Flush its disk on
        # exit; it is retained as evidence, never copied over the live disk.
        try:
            if self.child.isalive():
                self.child.sendcontrol("e")
                self.child.expect_exact("sim>")
                self.child.send("quit\r")
                self.child.expect_exact("Goodbye")
        finally:
            self.child.close(force=True)
            self.log.close()


class Session:
    def __init__(self, connection, name, log):
        self.connection, self.name, self.log = connection, name, log
        self.buffer = ""

    async def expect(self, marker, timeout=TIMEOUT):
        from aiohttp import WSMsgType

        deadline = time.monotonic() + timeout
        while marker not in self.buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"{self.name}: waiting for {marker!r}: {self.buffer!r}")
            message = await asyncio.wait_for(self.connection.receive(), remaining)
            if message.type != WSMsgType.TEXT:
                raise RuntimeError(f"{self.name}: connection ended: {message}; buffer={self.buffer!r}")
            self.buffer += message.data
        end = self.buffer.index(marker) + len(marker)
        result, self.buffer = self.buffer[:end], self.buffer[end:]
        return result

    async def send(self, command):
        await self.connection.send_str(command + "\r")

    async def enter(self):
        await self.expect("By what name shall I call you?")
        await self.send(self.name)
        await self.expect("What sex do you wish to be?")
        await self.connection.send_str("m")  # The original sex prompt consumes one character.
        await self.expect("letters, please.")
        await self.send("testpass")
        await self.expect("Hello, " + self.name)
        await self.expect("\n*")

    async def command(self, text, expected=None):
        start = time.monotonic()
        await self.send(text)
        response = await self.expect(text)
        if expected:
            response += await self.expect(expected)
        response += await self.expect("\n*")
        duration = time.monotonic() - start
        self.log.write(json.dumps({"name": self.name, "command": text,
                                   "seconds": duration, "output": response}) + "\n")
        return duration

    async def close(self):
        # Let the actual gateway perform QUIT/KJOB, as for a browser closing.
        await self.connection.close()


async def players(client, server, number, log):
    sessions = []
    try:
        for _ in range(number):
            name = "Bench" + "".join(secrets.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(4))
            session = Session(await client.ws_connect(server.make_url("/terminal")), name, log)
            sessions.append(session)
            await session.enter()
        return sessions
    except BaseException:
        await asyncio.gather(*(session.close() for session in sessions), return_exceptions=True)
        raise


async def scenario(emulator, client, server, number, active, seconds, log):
    sessions = await players(client, server, number, log)
    try:
        # Flush arrival notifications via a real command before timing.
        for session in sessions:
            await session.command("who", session.name + " is playing")
        start = emulator.point()
        deadline = start["wall"] + seconds
        latencies, rss_samples = [], []
        round_number = 0
        while time.monotonic() < deadline:
            next_round = time.monotonic() + COMMAND_INTERVAL
            if active:
                command = "look" if round_number % 2 == 0 else "who"
                latencies.extend(await asyncio.gather(*(
                    session.command(command, "Narrow road between lands." if command == "look"
                                    else session.name + " is playing") for session in sessions)))
            rss_samples.append(process_sample(emulator.child.pid)["rss_kib"])
            round_number += 1
            await asyncio.sleep(max(0, min(next_round, deadline) - time.monotonic()))
        result = metrics(start, emulator.point(), latencies, rss_samples)
        result.update(players=number, active=active, command_interval_seconds=COMMAND_INTERVAL)
        return result
    finally:
        await asyncio.gather(*(session.close() for session in sessions), return_exceptions=True)
        await asyncio.sleep(4)  # Let normal guest logout finish before the next scenario.


async def timing_checks(emulator, client, server, log):
    session = (await players(client, server, 1, log))[0]
    try:
        sleeps = []
        for _ in range(3):
            await session.send("sleep")
            await session.expect("ZZZzzz...")
            started = time.monotonic()
            await session.expect("You wake up.")
            sleeps.append(time.monotonic() - started)
            await session.expect("\n*")
        emulator.place_umbrella()
        await session.command("get umbrella")
        await session.command("open umbrella", "OK, it's unfurled.")
        for direction in ("w", "w", "w", "sw"):
            await session.command(direction)
        await session.send("jump")
        await session.expect("Over you go! For some reason, you don't plummet like a stone...")
        falling = time.monotonic()
        await session.expect("You land safely!")
        fall_seconds = time.monotonic() - falling
        return {"sleep_wake_seconds": sleeps, "fall_daemon_seconds": fall_seconds,
                "fall_daemon_source_interval": 8}
    finally:
        await session.close()
        await asyncio.sleep(4)


async def run(args):
    from aiohttp import ClientSession
    from aiohttp.test_utils import TestServer
    from server.gateway import create_app

    report = {"complete": False, "seconds_per_scenario": args.seconds,
              "warmup_seconds": args.warmup, "host": os.uname().machine,
              "terminal_speed_factor": args.terminal_speed_factor,
              "live_runtime_untouched": True, "modes": {}}

    def save():
        (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")

    try:
        for mode in args.modes:
            print(f"Booting isolated {mode} emulator", flush=True)
            emulator = Emulator(args.output / mode, mode, speed_factor=args.terminal_speed_factor)
            server = TestServer(create_app(upstream_port=emulator.port))
            try:
                emulator.boot()
                await server.start_server()
                print(f"{mode}: waiting {args.warmup}s for calibration", flush=True)
                await asyncio.sleep(args.warmup)
                result = report["modes"][mode] = {"pid": emulator.child.pid, "scenarios": {}}
                save()
                async with ClientSession() as client:
                    with (args.output / mode / "commands.jsonl").open("w") as log:
                        for label, count, active in (("empty", 0, False), ("two_quiet", 2, False),
                                                       ("two_active", 2, True), ("eight_active", 8, True)):
                            print(f"{mode}: {label} ({args.seconds}s)", flush=True)
                            measurement = await scenario(emulator, client, server, count, active, args.seconds, log)
                            result["scenarios"][label] = measurement
                            save()
                            print(json.dumps(measurement), flush=True)
                        print(f"{mode}: original sleep/wake timing checks", flush=True)
                        result["timing"] = await timing_checks(emulator, client, server, log)
                        save()
                        print(json.dumps(result["timing"]), flush=True)
            finally:
                await server.close()
                emulator.stop()
        report["complete"] = True
        if {"idle", "noidle"} <= report["modes"].keys():
            validate_comparison(report)
            report["timing_validation"] = "passed"
    except BaseException as error:
        report["complete"] = False
        report["error"] = repr(error)
        raise
    finally:
        save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--validate-report", type=Path)
    parser.add_argument("--terminal-speed-factor", type=int, default=1)
    parser.add_argument("--seconds", type=int, default=DEFAULT_SECONDS)
    parser.add_argument("--warmup", type=int, default=DEFAULT_WARMUP)
    parser.add_argument("--modes", nargs="+", choices=("noidle", "idle"), default=["noidle", "idle"])
    parser.add_argument("--background", action="store_true")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.validate_report:
        validate_comparison(json.loads(args.validate_report.read_text()))
        print("PASS: guest clocks, original timed behaviors and command latency")
        return
    if args.output is None:
        parser.error("--output is required for a benchmark")
    if args.seconds <= 0 or args.warmup < 0 or not 1 <= args.terminal_speed_factor <= MAX_TERMINAL_SPEED_FACTOR or len(set(args.modes)) != len(args.modes):
        parser.error("Use positive durations, speed factors 1–32, and unique modes")
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=args.worker)
    if args.background:
        with (args.output / "driver.log").open("xb") as log:
            process = subprocess.Popen([sys.executable, "-u", "-m", "tools.benchmark_idle", "--worker",
                                        "--output", str(args.output), "--seconds", str(args.seconds),
                                        "--warmup", str(args.warmup),
                                        "--terminal-speed-factor", str(args.terminal_speed_factor),
                                        "--modes", *args.modes], cwd=ROOT,
                                       stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
        print(f"Benchmark PID {process.pid}; progress in {args.output / 'driver.log'}")
    else:
        asyncio.run(run(args))


if __name__ == "__main__":
    main()
