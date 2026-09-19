# Small-VPS sizing and SIMH idle investigation

## Conclusion

**The resource measurements support trying a Linux VPS with 1 vCPU and 2 GB
RAM, such as the smallest IONOS plan discussed.** They do not yet establish
that the idle profile is operationally reliable: separate startup and
pause/resume checks stalled on this Mac. The live server retains its existing
configuration and its player sessions were not interrupted for these tests.

Use a short-term Linux VPS trial to verify both performance and lifecycle
behavior before making a longer hosting commitment. More RAM is not indicated
by the measured game/gateway working sets.

## Method

- Host: Apple M5, macOS arm64, 10 logical CPUs, 32 GiB RAM.
- Emulator: SIMH `47b7ddabbe5b548cfc32f2fd45f7bed238ff7921`.
- Each mode ran on its own copy of
  `runtime/checkpoints/first-playable/tops10-704.dsk`.
- Booted the original TOPS-10 7.04 tape with `/tm02`.
- Private Telnet and WebSocket ports; no benchmark personas in the live game.
- The tests used the original MUD executable, database and commands.
- Both modes received a 22-second startup settling interval before GO and a
  further 30-second warmup. This was an experimental mitigation for observed
  cold-start stalls, not a proven fix.
- CPU is the difference in cumulative process CPU time divided by host elapsed
  time. **100% means one fully occupied host core**, not all ten cores.
- Memory is sampled resident memory, not total system memory or a RAM limit.
- Active players issued alternating `look` and `who` commands once every five
  seconds each, in simultaneous bursts. Eight players therefore produced
  approximately 1.6 commands per second.
- Latency runs from sending a command to receiving the complete response and
  next prompt over WebSocket. It includes emulated terminal output but excludes
  Internet latency and any browser-side presentation/baud pacing.

The running live emulator also used one host core during the measurements.
Results are host-specific, single runs rather than a statistical capacity
certification. Combat-heavy play, 32-player saturation and long-duration clock
drift were not measured.

## First comparison: original terminal speed

90 seconds per scenario. Both modes used the original terminal-speed factor.

| Workload | NOIDLE CPU | IDLE CPU | NOIDLE p95 response | IDLE p95 response |
|---|---:|---:|---:|---:|
| No players | 99.44% | 19.11% | — | — |
| Two inactive players | 99.45% | 15.71% | — | — |
| Two active players | 99.51% | 22.17% | 0.532 s | 1.202 s |
| Eight active players | 99.49% | 22.79% | 0.783 s | 1.633 s |

CPU use improved substantially, but long responses finished more slowly. This
comparison **failed** the preselected latency-regression check (at most 0.3 s
increase in p95). It was not accepted as the final candidate configuration.

Raw results and command transcripts: `runtime/idle-comparison/`. That report
was collected before the automated acceptance checker was added; its
`complete: true` means collection completed, not that the later latency check
passed. Running the checker against it correctly fails.

## Second comparison: 8× terminal transport speed

SIMH supports `SPEED=*8` on the DZ attachment. This accelerates only terminal
transfer relative to the speed programmed by TOPS-10; it does not accelerate
the guest clock or change the game rules. Both NOIDLE and IDLE used this same
factor for the second comparison.

45 seconds per scenario, 18 measured commands with two active players and 72
with eight active players:

| Workload | NOIDLE CPU | IDLE CPU | NOIDLE p95 response | IDLE p95 response |
|---|---:|---:|---:|---:|
| No players | 99.37% | 18.07% | — | — |
| Two inactive players | 99.57% | 16.99% | — | — |
| Two active players | 99.04% | 16.50% | 0.128 s | 0.171 s |
| Eight active players | 99.44% | 18.20% | 0.169 s | 0.267 s |

This is approximately an **82% reduction in emulator CPU consumption**.
The emulator's maximum sampled resident memory was 12,480 KiB across this
comparison (about 12.2 MiB). The separate live gateway had previously measured
about 31 MB resident memory; host Linux, HTTPS, logs and backup processes must
be budgeted in addition. Chromium and the benchmark's extra disk copies are
development artifacts, not production requirements.

An M5 core is not equivalent to a shared IONOS vCPU. These results justify a
small-server trial; the benchmark should be repeated on the actual VPS.

### Timing checks

The original character started at full stamina, was put to sleep, and woke
without further input. Three repetitions were measured in each mode:

| Check | NOIDLE | IDLE |
|---|---:|---:|
| Median sleep-to-wake | 5.989 s | 6.039 s |
| Falling daemon, one trial | 8.954 s | 8.877 s |
| Largest absolute guest-clock/display discrepancy | 0.854 s | 0.858 s |

The clock checks compare TOPS-10 `DAYTIME` with monotonic host time. DAYTIME
displays whole seconds, so these discrepancies are consistent with its display
resolution and the command/measurement overhead.

For the falling test, the original archwizard commands retrieved an umbrella
from WRDBE and dropped it at START on the **private machine**. An ordinary test
persona collected and opened it, walked west/west/west/southwest, and jumped.
The interval between the original falling and safe-landing messages was timed.
The database interval is 8; the observed interval is near 9 seconds under the
original event-loop scheduling. The comparison preserves that behavior rather
than changing the engine to impose a new interpretation of the interval.

The second comparison passed these checks:

- Guest-clock error within 1.5 seconds for each sampled window.
- Median sleep/wake difference within one second.
- Falling-daemon difference within 1.5 seconds.
- p95 command-latency increase within 0.3 seconds at the same transport speed.

Raw results: `runtime/idle-comparison-fast-terminal/report.json`.

## Lifecycle failures: why this is still opt-in

Steady-state resource and timing tests passed, but further verification did not:

- Two early fast-start pilots stalled before measurements, one with NOIDLE and
  one with IDLE. This means the startup problem cannot be attributed solely to
  idle handling.
- Subsequent successful benchmarks used the settling interval described above.
- In maintenance tests, an IDLE emulator stopped at SIMH's prompt but stopped
  answering guest console/network input after `CONTINUE`. Testing `GO` also
  failed. The cause has not been established.
- Later clean-restart verification attempts stalled during initial TOPS-10
  startup, so the proposed two-boot Chromium/restart acceptance sequence did
  **not** complete. No successful browser/restart result is claimed for it.

Diagnostics are retained under `runtime/idle-restart-verification*`,
`runtime/idle-clean-restart-verification`, and `runtime/idle-clean-restart-retry`.
The private processes were stopped after failure. The live emulator was never
paused or reconfigured by the benchmark.

`config/pdp10.ini` remains the default. The experimental candidate is
`config/pdp10-idle.ini`. On a stopped test installation, select it with:

```sh
SIMH_CONFIG="$PWD/config/pdp10-idle.ini" python3 tools/boot.py --settle 22
```

Do not promote it to the production default until its startup, shutdown and
maintenance behavior has passed on the target Linux host. The normal boot
driver still defaults to its original zero additional settling delay.

## Reproduce the tests

Install `requirements-dev.txt`. Use fresh output directories; the tools refuse
to overwrite old runs. Each benchmark copies the baseline disk and binds
private loopback ports.

```sh
.venv/bin/python -m unittest discover -s tests -v

.venv/bin/python -m tools.benchmark_idle \
  --output runtime/idle-new-comparison --seconds 90 \
  --terminal-speed-factor 8 --background

.venv/bin/python -m tools.benchmark_idle \
  --validate-report runtime/idle-new-comparison/report.json

# Cold boot, real browsers, clean shutdown, and reboot (currently not passing here)
.venv/bin/python -m tools.verify_idle \
  --output runtime/idle-new-restart --terminal-speed-factor 8

# Include the observed pause/resume failure in the private-machine test
.venv/bin/python -m tools.verify_idle \
  --output runtime/idle-new-pause --terminal-speed-factor 8 --check-pause
```

The background benchmark writes `driver.log`, an incremental `report.json`,
console transcripts, command transcripts and disposable guest disks in the
specified output directory. A failed run records an error instead of being
treated as a successful comparison. The unit tests also check that clock,
sleep, daemon and response-latency regressions are rejected.
