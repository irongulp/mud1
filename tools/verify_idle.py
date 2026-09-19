"""Verify IDLE cold boot, clean shutdown/reboot, and real Chromium sessions.

Uses a disposable disk and private ports, never the live game.
"""
import argparse
import asyncio
import json
from pathlib import Path

from aiohttp.test_utils import TestServer

from server.gateway import create_app
from tests.browser_smoke import main as browser_smoke
from tools.benchmark_idle import DEFAULT_WARMUP, Emulator


async def main(output, speed_factor, check_pause=False):
    output.mkdir(parents=True)
    result = {"complete": False, "terminal_speed_factor": speed_factor,
              "pause_resume_requested": check_pause, "boots": []}
    try:
        for number in range(2):
            emulator = Emulator(output / "machine", "idle", reuse=number != 0, speed_factor=speed_factor)
            server = TestServer(create_app(upstream_port=emulator.port))
            try:
                print(f"IDLE boot {number + 1}", flush=True)
                emulator.boot()
                await asyncio.sleep(DEFAULT_WARMUP)
                status = "set cpu idle in the isolated boot configuration"
                if check_pause:
                    emulator.child.sendcontrol("e")
                    emulator.child.expect_exact("sim>")
                    emulator.child.send("show -d cpu\r")
                    emulator.child.expect_exact("sim>")
                    status = emulator.child.before
                    if "idle enabled" not in status:
                        raise AssertionError(status)
                    emulator.child.send("go\r")
                    emulator.command("daytime")
                await server.start_server()

                async def reconfigure_connected_lines():
                    emulator.child.sendcontrol("e")
                    emulator.child.expect_exact("sim>")
                    for factor in (1, speed_factor):
                        for line in range(32):
                            emulator.child.send(f"attach -am dz Line={line},SPEED=*{factor}\r")
                            emulator.child.expect_exact("sim>")
                            if "ERROR" in emulator.child.before:
                                raise AssertionError(emulator.child.before)
                    emulator.child.send("go\r")
                    emulator.command("daytime")

                await browser_smoke(str(server.make_url("/")), output / f"browser-{number + 1}.png",
                                    after_join=reconfigure_connected_lines if check_pause else None)
                await server.close()
                # Clean TOPS-10 shutdown, preserving this private disk for reboot.
                emulator.child.send("r opr\r")
                emulator.child.expect_exact("OPR>")
                emulator.child.send("set ksys now\r")
                emulator.child.expect_exact("KSYS processing completed")
                emulator.child.expect_exact("OPR>")
                emulator.command("exit")
                emulator.command("kjob")
                result["boots"].append({"number": number + 1, "cpu_status": status,
                                         "browser_multiplayer": "passed", "shutdown": "clean",
                                         "connected_line_speed_change": "passed" if check_pause else "not tested"})
            finally:
                await server.close()
                emulator.stop()
        result["complete"] = True
    except BaseException as error:
        result["error"] = repr(error)
        raise
    finally:
        (output / "report.json").write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--terminal-speed-factor", type=int, default=1)
    parser.add_argument("--check-pause", action="store_true",
                        help="Also reproduce/check the observed IDLE pause/resume stall")
    args = parser.parse_args()
    asyncio.run(main(args.output.resolve(), args.terminal_speed_factor, args.check_pause))
