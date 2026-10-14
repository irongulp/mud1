# Reproducing deployment acceptance

GitHub and local Docker hosts use `tests.deployment_lifecycle`. It owns the fresh
container sequence: install/rerun/login/backup, HTTP and HTTPS Chromium checks,
container reboot, populated external cutover, fresh external installation, SQL
editor acceptance, diagnostics and final shutdown. Containers/disks are retained.

Prepare the host test environment and pinned runtime archive as in
`.github/workflows/deployment.yml`, then run from the checkout:

```sh
PLAYWRIGHT_BROWSERS_PATH=/path/to/browsers python -m tests.deployment_lifecycle \
  --assets /path/to/runtime/release-v1 --prefix mud86-local \
  --output runtime/deployment-local
```

The prefix must be unused. Loopback ports 38080/38443/48080 must be available.
`--native-only` stops after the native installation checks but still requires
final shutdown. `--no-guest-diagnostics` omits only the independent maintenance
SYSTAT query, allowing controlled comparison of its effect on shutdown.
On macOS, use `caffeinate -is` and allow a sufficiently long host execution window:
original guest source transfers and compilation make the full sequence lengthy.

The runner records commit, working-tree changes, host/platform, Python version,
Docker server, image identity/architecture and runtime archive checksum. Individual
stages have logs; browser stages have separate screenshots/admission reports.
Incremental `report.json` remains incomplete until every stage and final shutdown
passes. Diagnostics are captured before and after shutdown. A failure still
attempts bounded cleanup, retaining the original stage failure and cleanup result.

The gateway stops before the runtime. The external bridge/database stay alive
through native cleanup. Final `systemctl stop` alone is not success: each guest's
`shutdown.json` must contain boolean `clean: true`, which the supervisor writes
only after its readiness proof and actual native KSYS completion. No container
restart or disk backup follows an unconfirmed shutdown in this runner.

The same scripts, resources, image definition and starter archive run locally,
but native ARM Docker on an Apple Mac is not native x86-64 GitHub hardware.
Translated x86 containers are supplemental checks, not native-x86 acceptance.

## Independently reproduced defects

### Interval timer interpolation

The pinned SIMH timer changes `tick_in_usecs` immediately on WRINT, although the
scheduled interval has not expired. TOPS-10 7.04 alternates roughly 17/16-ms
intervals; subtracting the old remaining interval from the newly shortened
duration produces backwards RDTIM readings. Private unpatched tracing witnessed
this. A compiled deterministic regression reproduces both shorter/longer WRINT
changes during an active tick.

`tools.simh_timer` retains the active scheduled duration separately from the next
requested interval. It checks exact upstream and corrected source SHA-256 values.
Deployment builds the unchanged pinned revision in a separate
`<revision>-active-tick-v1` cache, retaining the correction and MIT upstream notice.
Existing unpatched caches and historical guest source/binaries are not overwritten.
For an independent local SIMH checkout:

```sh
python -m tools.simh_timer /path/to/independent/pinned-simh
make -C /path/to/independent/pinned-simh pdp10 USEFUL_PACKAGES= OPTIONAL_PACKAGES=
```

Do not apply this to the checkout supplying an active emulator. The original
batch CPU allowance and host deadlines remain unchanged. ARM tracing of the
corrected emulator observed 139,021 RDTIM reads without backwards steps; that
traced run still hit the independent KSYS problem below.

### Ordinary batch workers during KSYS

Completed batch jobs can leave reusable, logged-in PTY jobs owned by the normal
BATCON worker. A failed native shutdown showed such a RICHARD job controlled by
the old worker while a separate KSYS stream waited. Native
`SHUTDOWN BATCH-STREAM 0:1` drains the supplied SYSTEM.CMD's ordinary streams.
Its acknowledgements precede final PTY release, so the supervisor also requires
a complete native SYSTAT table showing those PTY jobs gone before requesting
KSYS. Both acknowledgements, release and the restored OPR prompt share a bounded
drain phase inside the existing shutdown deadline. No job kill or KSYS replay.

### Hourly CTY announcements

The native hourly `Monitor KS10 / System uptime / Current date/time` announcement
can arrive while CTY is at the monitor. Strict echo verification previously
rejected it before R OPR. The console parser now recognizes its narrow witnessed
grammar while retaining exact command echo, bounds and rejection of unknown or
partial output. `tests.integration_hourly_control` uses fresh private disk copies
and a selected boot clock to observe the announcement and real clean shutdown.
It can use an explicitly supplied disposable stopped disk with its adjacent
clean-shutdown marker to isolate initializer/startup failures.
OPR's witnessed ten-minute idle BATCON logout and ordinary-stream Shutdown
notifications also require the complete exact typed-prefix redraw before they
can acknowledge an interrupted command byte.

### Terminal initializer ownership

The optional STOMPR initializer can claim browser TTY0, leaving browser admission
at the monitor stage with no prompt. This was reproduced in the full local HTTPS
stage: SYSTAT showed STOMPR owning TTY0 while maintenance on TTY1 worked.
Deployed native and external browser supervisors explicitly use
`--browser-terminals`: staged/read-back-verified SYS:TTY.INI preparation removes
only STOMP, preserves other settings and XTTY.INI, and requires a clean reboot
before admission. The gateway already sets terminal type and width per connection.
Standalone/default native Runtime configurations retain their existing behavior.

### Terminal reuse before logout output finished

The external backup failure was reproduced with private admission tracing. After
a maintenance connection closed at the words `Logged-off`, a new SIMH connection
received the preceding job's remaining `Runtime / Disk Reads` output. Its final
dot was mistaken for readiness; the next command's first byte was lost while
the line finished changing ownership. Native inspectors, runtime readiness
cleanup and the gateway now require the complete accounting report and final
monitor prompt before releasing their connection. No failed command is replayed.
Thirty consecutive maintenance admissions on the installed external fixture then
passed, followed by actual clean KSYS. Protocol regressions reject a logout prefix
alone and hold gateway cleanup open until its tail arrives.

The real-Chromium heartbeat regression now uses a one-second heartbeat and watches
three cycles. Its former 100-ms heartbeat imposed a 50-ms PONG allowance during
browser startup; shared native-x86 CI failed that test before deployment began.
Production heartbeat/deadline settings are unchanged, and prompt-starvation
protocol coverage remains in place.

## Retained evidence and limitations

Private evidence includes `runtime/deployment-parity-1` (local backup failure),
`-2/-3` (patch packaging failures), `-4` (TTY0 HTTPS failure), and `-5` (native,
HTTP/HTTPS/reboot passed; host execution window interrupted the cutover driver).
The latter's guest build subsequently completed, but its whole acceptance run is
not complete. Native timer/drain/hourly evidence is retained in disposable
`mud86-timer-arm` and the OpenCode temporary directory. Earlier boot, admission,
shutdown and experimental parser failures remain. Successful individual controls
do not establish that every historical failure has the same cause.
`deployment-parity-6` passed native install/backup, HTTP/HTTPS and reboot, then
finished external guest compilation but rejected the idle BATCON notice during
shutdown input. That exact notification now has a failing-before/passing-after
regression. It is retained as a failed run, not complete cutover acceptance.
`deployment-parity-7` reached installed external login/rerun but failed backup on
the incomplete-logout admission race. Its evidence and private
`external-admission-trace-{1,2}` failures are retained. The corrected fixture's
`admission-logout-green` verified the thirty-admission control above.
