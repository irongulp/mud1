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

### Cutover boot recovery follow-up

The documentation-triggered rerun
[38507721701](https://github.com/irongulp/mud1/actions/runs/38507721701) passed the
429 host tests, native installation/backup, HTTP/HTTPS and reboot, but stalled
waiting for the cutover guest's first `OPR>` prompt. It failed before capture or
guest compilation. The cleanup exception obscured that original timeout.
The earlier green run is historical evidence, not proof this stall was eliminated.

`Runtime.start()` now shares the existing three-attempt cold-boot recovery policy
between the foreground service and private cutover. No timeout or attempt count
was increased. Failed guests/resources must be released before another boot.
Stopping/cancellation or cleanup failure prevents further attempts. Each new
startup invalidates the previous clean marker before launching a guest.

`Runtime.session()` holds the runtime lock across private startup, controller
work and shutdown. Its body runs only after startup returns, and is never replayed
on a capture/build/shutdown error. Import remains after confirmed clean shutdown.
Startup, controller and service failures retain their original exception even if
cleanup fails. Failed-start cleanup is owned by `start()`, not repeated by the
private context manager.

Boot failures retain phase/type/readiness metadata and at most 8192 prompt
characters in `boot-diagnostics/attempt-*.json` (`0600`, private directory).
Excerpts are restricted to initial boot prompts; readiness/game payloads and
exception messages are excluded. CI diagnostics publish only validated metadata
through `tests.deployment_boot_status`, never the private excerpts.

`tests.integration_startup_recovery` deliberately withholds an actual native OPR
acknowledgement on copied private disks. Positive native control passed with one
suppressed reply, one body execution and genuine clean shutdown; exhaustion passed
with three suppressed replies, no body execution, reaped guests and `clean:false`.
Both preserved original source hashes. Evidence: disposable `mud86-timer-arm`
under `/tmp/startup-recovery-{green,exhausted}`. This models a transport failure;
it does **not** establish the cause or a fix for the underlying native OPR stall.
Cutover regressions additionally assert capture/build are not retried and import
is blocked on unconfirmed shutdown. Private failed CI evidence is retained at
`ci-9c0931e-cutover-boot-failure`.

Full acceptance passed for code commit `93478975b4dfb2fdc13fabe8b537caeb81560355`:

- Local native ARM AlmaLinux: `runtime/deployment-parity-8/report.json` records
  every stage completed, clean working tree, matching pinned runtime checksum,
  and both final guest shutdowns clean.
- Native-x86 GitHub: [run 38501086454](https://github.com/irongulp/mud1/actions/runs/38501086454)
  passed in 1h7m57s. GitHub checked out PR merge commit
  `01c649c7e76c7c1b6ed998e3f45760c0434d68f0`; its lifecycle report also records
  every stage and both final clean shutdowns. Both populated cutover and fresh
  external reports confirm installer rerun, backup/restart and editor checks.
  Private downloaded evidence: `ci-9347897-lifecycle-green`.
- 429 host tests passed locally after installing the same pinned upstream
  preparation assets as CI. Thirty installed external maintenance admissions,
  hourly-announcement controls, missing-BATCON rejection and native shutdown
  controls passed separately. Test fixtures and containers are stopped.

The successful local/CI service journals still contain isolated startup retries,
conservative failed intermediate batch preflights and gateway logout timeouts.
Those are retained follow-up evidence, not claimed fixed by a successful final
run. Backup/migration guards and both final shutdown proofs passed; this does not
establish exhaustive startup or arbitrary-disconnect reliability.

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
