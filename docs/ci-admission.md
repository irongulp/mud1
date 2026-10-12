# CI initial-admission investigation

The later controller implementation and validation are described in
[verified guest control](verified-guest-control.md). The failures below remain
historical evidence; they are not retroactively declared successful.

## Observed failure

PR #6, commit `925155c`, failed in run `38172587681` during the HTTPS browser
smoke step on 2026-10-11. The dependency audit, host suite, native install/rerun,
saved login, backup/restart, and HTTP Chromium multiplayer steps passed.
Reboot and MariaDB deployment steps were skipped after the failure.

The service artifact establishes this sequence (UTC):

- 20:40:19: HTTP browser smoke completed, with gateway logout completion.
- 20:40:30: the guest reported `TTY STOMPER: Quieting open line on TTY0 ...
  failed, code 0`.
- 20:40:35–36: HTTPS page and static assets reached the local gateway.
- 20:40:36: the gateway connected to guest Telnet for the browser session.
- 20:40:51: `stage=monitor upstream TimeoutError`; the WebSocket request had
  status 101. This is before `LOGIN MUDGUEST` or any RESET command.
- 20:40:52: browser reconnect began; the smoke client's initial 20-second prompt
  wait expired at 20:40:56.

The timeout means that the gateway's initial CR did not yield a monitor dot
within its existing 15-second deadline. It does not establish why. In particular,
the STOMPR warning is a lead, not proof that STOMPR owned the failed connection's
line. Neither increasing the browser timeout nor removing STOMPR is a verified
fix for this failure.

## Added diagnostics

`tests.browser_smoke.wait_admission()` retains a screenshot and a sibling
`*.admission.json` on initial prompt timeout, before any persona input is sent.
It records bounded received output, socket state/open/error/close events,
pending pacing lengths, and browser errors. It also works when page scripts
have not initialized. The initial timeout is unchanged; failure is not retried
or treated as success by the test helper.

The deployment workflow uploads `runtime/browser.admission.json` and obtains
Nginx configuration plus a read-only `SYSTAT` through
`tests.deployment_guest_status` before stopping services. The independent
maintenance connection can itself fail; its error is retained. Its timeout
sends SIGINT first, allowing the inspector's bounded logout before forced exit.
This reports ownership at diagnostic time, not a snapshot at the earlier fault.

## Disposable controls

`tests.integration_gateway_admission` creates an isolated guest copy with private
ports and the NOIDLE / 5M / DZ SPEED=*8 profile. It never selects a live disk.
`--archive` verifies and installs the pinned deployment runtime rather than using
the historical first-playable checkpoint. `--assets` selects a checkout holding
SIMH and the original tape. Output directories must be new and are private (0700).

```sh
python -m tests.integration_gateway_admission \
  --assets /path/to/runtime-checkout \
  --archive /path/to/mud86-runtime.tar.gz \
  --output /private/new-admission-probe --attempts 24 --interval 3

python -m tests.integration_gateway_admission \
  --assets /path/to/runtime-checkout \
  --archive /path/to/mud86-runtime.tar.gz \
  --output /private/new-browser-probe --browser-rounds 3 --interval 18 --tls
```

The first mode sends no persona credentials and retains bounded private upstream
wire data, browser output, gateway logs and SYSTAT. Browser mode uses the existing
two-player smoke including creation, editing, WHO/speech, QUIT and reconnect.
`--tls` uses a disposable local test certificate and HTTPS/WSS directly to the
gateway; it is not an Nginx/systemd deployment check. Every completed control
requires source preservation and KSYS before emulator exit.

Evidence under the session's private OpenCode temporary directory:

| Directory | Result |
| --- | --- |
| `admission-baseline` | macOS, historical image: 24/24 admissions; clean shutdown. |
| `admission-deployed-baseline` | macOS, pinned deployment image: 8/8 admissions with 18-second gaps; clean shutdown. |
| `admission-browser-baseline` | Initial OPR boot timeout; no browser check or clean-shutdown claim. |
| `admission-browser-baseline-2` | macOS: three two-tab smoke rounds passed; clean shutdown. |
| `admission-linux-baseline` | Native ARM AlmaLinux: all four rounds admitted; first round failed later on a native redraw (`*howho` after a player-arrival notice), remaining three passed; clean shutdown. |
| `admission-linux-early` | Interrupted exploratory run; incomplete evidence, no clean-shutdown claim. |
| `admission-linux-early-2` | Four admissions with Telnet's minimum/maximum negotiation waits forced to zero passed; clean shutdown. This experimental override is not in the final harness. |
| `admission-linux-tls` | Native ARM AlmaLinux, one CPU/2 GiB: three HTTPS/WSS two-tab smoke rounds passed; clean shutdown. |

The Linux final checks used Python 3.12.15, aiohttp 3.14.5 and the pinned SIMH
revision. The 75 selected browser-smoke/gateway/deployment/reset-permission tests
passed on both macOS Python 3.12 and native ARM AlmaLinux. Two new browser
diagnostic tests were observed failing before implementation, then passing.

## Remaining work

The CI monitor timeout has **not** been reproduced in these local controls. No
production gateway, terminal initializer, game code, or deadline was changed as
a purported fix. Keep the native boot/redraw and interrupted-run failures.
The redraw failure is separate from the CI admission failure and remains open.

Run native-x86 deployment CI with the added diagnostics. If admission fails,
correlate the connection stage, socket close code, guest line ownership, and
runtime/Nginx evidence before selecting a change. Compare a proposed correction
against a failing control on a disposable guest; a successful rerun alone is not
proof of causation or a general admission fix.

## Native-x86 diagnostic run

Run `38178361290` at `9933234` passed the previously failing HTTPS smoke,
container reboot/browser recovery, and populated native-to-MariaDB cutover with
installer rerun, backup and restart. It then failed the **rerun** of a fresh
external installation: `tools.reset_permissions.configure()` timed out awaiting
`directory DSKB:MUD.EXE[2011,2776]`. Initial installation, saved persona admission
and the installed editor check had passed. The final database-editor acceptance
step was skipped. This is a different failure point from the initial browser
monitor wait; no common cause has been established.

That run exposed two evidence gaps. Diagnostics only targeted
`mud86-install-test`, not the failing `mud86-external-fresh`, and `rerun.log` was
written only on success. The collector now captures service journals (including
MariaDB), service status, Nginx configuration and independent guest SYSTAT for
**both containers**, under `runtime/deployment-ci/<container>/`. Missing
containers or timed-out diagnostics retain their errors and do not suppress the
other captures. Installer/rerun/backup logs retain redacted output before raising
on failure, including partial output from a subprocess timeout.

Five failing regressions preceded these corrections (including interrupted
credential-line redaction); all 32 diagnostic,
deployment and external-deployment host tests passed afterward. This fixes
evidence retention, not the native DIRECTORY timeout. No additional production
retry or increased guest deadline has been introduced.

## Repeated failure and private control experiments

Run `38182544754` at `e40e6b2` retained both containers' diagnostics as intended.
Attempt 1 failed before cutover: KSYS started its batch stream but did not finish
within the existing deadline. The installer correctly refused the unconfirmed
snapshot. Attempt 2 (unchanged commit) passed cutover, then reproduced the fresh
installer rerun's maintenance DIRECTORY timeout. Fresh-container diagnostics
showed STOMPR explicitly **not starting**, runtime/database still active, and an
independent RICHARD maintenance login failing. Removing STOMPR is therefore not
a demonstrated remedy for this failure.

The fresh guest's console echoed `set tty tty: echo` where the host requested
`set tty tty7: echo`. A separate private ARM AlmaLinux fresh-build attempt echoed
`copy sys:tty.nii=tty:` for `copy sys:tty.ini=tty:` and failed the exact-echo
check. These establish malformed echoes, not whether loss/reordering occurred
on input, output, or within the guest. No shared cause with the earlier browser
timeout is proved.

Private repeated COPY controls on the pinned native image:

- Unpaced control: round 99 echoed `copy chtest.iin=tty:` for `.ini`; clean KSYS.
- 20 ms character delay: round 174 echoed `copy chtest.ini=tt:`; clean KSYS.
  Simple pacing is not a verified correction.
- Per-character echo acknowledgement plus COPY consumption settling: 200 rounds
  passed with clean KSYS. Earlier acknowledgement and a separate settled-unpaced
  run stalled at COPY completion and were stopped without clean-shutdown claims.
  This is preliminary transport research, not a production-ready fix.
- Permission/DIRECTORY loops passed 30 times on macOS and 40 times on ARM Linux.
  The private probe used shorter diagnostic timeouts; production timeouts stayed
  unchanged. They do not reproduce the fresh external installer failure.

The Mac entered maintenance sleep during some experiments (confirmed by `pmset`),
so interrupted/local timing results cannot establish CI timeout causes or timing
margins. The Linux 40-round probe ultimately completed with clean KSYS despite
the host-side command watcher timing out. Preserve the interrupted runs.

Private evidence is in the OpenCode temporary directory: `ci-e40e6b2-attempt1`,
`ci-e40e6b2-attempt2`, `ci-9933234-failure`, `maintenance-native-awake`,
`maintenance-linux-report.json`, and `console-{unpaced,paced,ack-settled}-report.json`.
Local fresh-install reports are in the PR worktree's ignored
`runtime/external-deployment-mud86-maintenance-fresh` and temporary
`fresh-arm-retry/runtime/`; systemd diagnostics are in
`maintenance-fresh-local-diagnostics`. Disposable Docker containers
`mud86-maintenance-fresh` and `mud86-admission-probe` are stopped and retain the
other private traces/disks. No historical binary or private wire trace was pushed.

The next investigation must distinguish echo corruption from input corruption,
then prove a bounded controller correction on both the failed native control
and the full fresh external rerun. Do not bypass the clean-shutdown guard,
blindly retry an uncertain guest command, or claim that pacing fixed CI.
