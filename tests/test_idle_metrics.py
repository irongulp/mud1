import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.benchmark_idle import Emulator, cpu_seconds, guest_seconds, metrics, validate_comparison


class IdleMetricsTests(unittest.TestCase):
    def test_unsupported_terminal_speed_fails_before_creating_a_machine(self):
        with tempfile.TemporaryDirectory() as directory:
            machine = Path(directory) / "machine"
            for factor in (0, 33):
                with self.subTest(factor=factor), patch("pexpect.spawn", side_effect=AssertionError("invalid speed reached emulator launch")), patch("tools.benchmark_idle.shutil.copyfileobj"):
                    with self.assertRaises(ValueError):
                        Emulator(machine, "idle", speed_factor=factor)
                self.assertFalse(machine.exists())

    def test_ps_cpu_times_on_macos_and_linux(self):
        for text, expected in (("53:19.68", 3199.68), ("01:02:03", 3723),
                               ("2-01:02:03", 176523)):
            with self.subTest(text=text):
                self.assertAlmostEqual(cpu_seconds(text), expected)
        with self.assertRaises(ValueError):
            cpu_seconds("not a CPU time")

    def test_clock_parser_uses_daytime_response_not_command_echo(self):
        self.assertEqual(guest_seconds("daytime\r\nFriday 18-Sep-126 3:04:05\r\n."), 11045)
        with self.assertRaises(ValueError):
            guest_seconds("daytime\r\n?Error\r\n.")

    def test_measures_one_core_cpu_and_handles_clock_midnight(self):
        result = metrics(
            {"wall": 100, "cpu": 20, "guest": 86390, "rss_kib": 10000},
            {"wall": 140, "cpu": 30, "guest": 30, "rss_kib": 11000},
            [0.1, 0.3, 0.2, 0.8], [12000])
        self.assertEqual(result["cpu_percent_one_core"], 25)
        self.assertEqual(result["guest_elapsed_seconds"], 40)
        self.assertEqual(result["clock_error_seconds"], 0)
        self.assertEqual(result["latency_p95_seconds"], 0.8)
        self.assertEqual(result["peak_rss_kib"], 12000)

    def test_invalid_counter_windows_are_rejected(self):
        point = {"wall": 100, "cpu": 20, "guest": 100, "rss_kib": 10000}
        with self.assertRaises(ValueError):
            metrics(point, point, [], [])
        with self.assertRaises(ValueError):
            metrics(point, dict(point, wall=110, cpu=19), [], [])

    def comparison(self):
        mode = {"scenarios": {name: {"clock_error_seconds": 0.8, "latency_p95_seconds": latency}
                               for name, latency in (("empty", None), ("two_quiet", None),
                                                     ("two_active", 0.6), ("eight_active", 0.8))},
                "timing": {"sleep_wake_seconds": [6, 6.1, 6], "fall_daemon_seconds": 9}}
        return {"complete": True, "modes": {"noidle": mode, "idle": copy.deepcopy(mode)}}

    def test_quantized_clock_and_small_latency_variation_are_accepted(self):
        report = self.comparison()
        report["modes"]["idle"]["scenarios"]["eight_active"]["latency_p95_seconds"] = 0.9
        validate_comparison(report)

    def test_timing_regressions_and_incomplete_runs_are_rejected(self):
        for kind in ("clock", "sleep", "daemon", "latency", "incomplete"):
            report = self.comparison()
            idle = report["modes"]["idle"]
            if kind == "clock":
                idle["scenarios"]["empty"]["clock_error_seconds"] = -15
            elif kind == "sleep":
                idle["timing"]["sleep_wake_seconds"] = [3, 3, 3]
            elif kind == "daemon":
                idle["timing"]["fall_daemon_seconds"] = 4
            elif kind == "latency":
                idle["scenarios"]["eight_active"]["latency_p95_seconds"] = 2
            else:
                report["complete"] = False
            with self.subTest(kind=kind), self.assertRaises(AssertionError):
                validate_comparison(report)


if __name__ == "__main__":
    unittest.main()
