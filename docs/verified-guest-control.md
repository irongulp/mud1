# Verified guest control input

Host maintenance and operator drivers now acknowledge printable command input
before sending its terminating CR. This addresses the unsafe assumption that a
whole-line write followed by a prompt wait proves that the intended command was
entered. It does not repair the historical engine or establish the physical
cause of every earlier malformed echo, boot stall, or shutdown timeout.

## Protocol boundaries

`tools.guest_control.submit_line()` sends one printable ASCII byte and requires
its exact echo before advancing. It sends one CR only after the complete line
has been acknowledged. One deadline bounds the line, and unexpected data fails
closed. Errors distinguish whether any input was sent and whether Enter might
have reached the guest. The sender never automatically replays a command.

The adapters consume their libraries' existing receive buffers, including
pexpect's buffer, rather than bypassing them with direct socket/PTY reads.
Consumed echoes are reconstructed in returned responses for existing parsers.

Three native framing cases are handled explicitly:

- An inspector companion can leave additional empty monitor prompts after its
  first return marker. A bounded sequence of dots/CR/LF is accepted only before
  the first actual echoed character. It cannot acknowledge a command byte or
  complete a newly submitted request. Dot-leading commands are rejected in this
  mode to avoid ambiguity.
- The witnessed CTY `%%TTY STOMPER: Quieting open line ... failed, code 0` notice
  can interrupt an echo. Only that complete bounded message is recognized;
  unknown/incomplete notices remain errors and the console log retains them.
- OPR emits queued startup/accounting messages, then redraws `OPR>` and its
  current input. Before any input, the driver may resynchronize to another OPR
  prompt within the existing deadline and a fixed notification-count bound.
  Once typing has started, only the witnessed startup message formats plus an
  **exact full redraw of the typed prefix** can acknowledge the pending byte.
  Searching for a single matching character or accepting a corrupted redraw is
  forbidden. Notifications and redraws remain in the operator transcript.

`NativeInspector` applies this protocol only from a confirmed monitor state.
Compiler, snapshot-companion, seed, and other program input retain their explicit
protocols. Raw sends invalidate monitor state. Caller-specific TYPE/DBASE frames
use `send_control()` and explicitly confirm the final monitor afterward.
Snapshot response limits and its longer capture deadline remain supported.

`Runtime` tracks monitor/operator state. A control command makes it unknown until
its expected completion. Shutdown does not type R OPR into an unfinished COPY:
it must first witness interrupt recovery to the monitor. KSYS completion remains
mandatory for a clean marker, backup, or cutover. Shutdown's control operations
share one deadline; no timeout was increased.

## Configuration and permission operations

`tools.terminal_config` writes `SYS:XTTY.TMP`, verifies its full text, backs up
the old configuration as before, and activates the staged file through verified
file-to-file COPY. It verifies the active file afterward. The active `TTY.INI`
is not opened as a TTY transfer destination. A pre-existing or unreadable stage
is preserved and reported instead of overwritten. Native `%WLDNSF` is accepted
only for the exact requested staging filename.

COPY is a separate program dialogue with its own settling interval and full
read-back checks. A header echo alone is not evidence that COPY has consumed it.
The small configuration transfer has one deadline across header, payload and
completion. Source transfers retain their independent pacing and source-content
checks; source text is not interpreted as monitor commands.

The permission CLI permits at most one fresh-session reconciliation after a
metadata operation fails **and logout was confirmed**. Admission failures are
not retried by this mechanism. The new session reads actual protection before
any write; an already-applied PROTECT is therefore not blindly replayed. Unknown
protections and failed read-back checks remain hard errors. Reconciliation emits
a warning containing the error type, not raw terminal data.

## Tests and evidence

Host regressions cover dropped/reordered/duplicate echoes, stale prompts,
notification and redraw validation, deadlines, Enter uncertainty, program-mode
isolation, permission read-back reconciliation, failed cleanup, and staged-file
preservation. The expanded controller/inspection/deployment/gateway/browser suite
passed **156 tests** on macOS and native ARM AlmaLinux Python 3.12. Red failures were observed before each
new behavior was implemented.

The disposable native check is:

```sh
python -m tests.integration_guest_control \
  --assets /path/to/runtime-checkout \
  --output /private/new-control-check --rounds 200
```

It verifies the pinned runtime archive, uses private ports and a copied disk,
checks permission configuration/rerun, repeated COPY/read-back, staged terminal
configuration, reboot/idempotence, source hashes, and two clean shutdowns.

Private evidence in the OpenCode temporary directory and stopped/private Docker
fixtures is retained:

- `control-driver-native-1`: strict sender caught an interleaved STOMPR notice at
  round 35; controlled interrupt and clean KSYS passed.
- `control-driver-native-2`: OPR boot stall before the new sender was reached.
- `control-driver-native-3`: all 200 transfers passed; staging refused the then
  unrecognized `%WLDNSF` response; failure shutdown was clean.
- `control-driver-native-4`: complete 20-round macOS check, staging, reboot and
  both clean shutdowns passed.
- Docker `mud86-admission-probe:/tmp/control-driver-linux-1`: complete 200-round
  native ARM AlmaLinux check with both clean shutdowns passed.
- Initial `mud86-control-green` install exposed the extra monitor dot after
  MVTXT and the resulting unlogged-out maintenance job. The private trace is
  retained inside that fixture; no raw maintenance transcript was committed.
- `control-install-resume-1` and `-2`: installation/rerun succeeded; backup caught
  queued OPR notifications before or during command entry. Those failures remain.
- `control-install-resume-3`: installed rerun, saved Freshsql login, clean backup,
  restart, re-entry and installed editor checks passed with OPR redraw handling.
  This is a continued ARM acceptance after retained failures, not a claim that
  the initial fresh-install attempt passed unchanged.

Native-x86 CI must still validate the complete final implementation. Original
`source/` and gameplay remain unchanged; native storage has no MariaDB dependency.

The first native-x86 run at `3ea5b6f` (`38277153941`) passed native installation,
rerun, saved-player checks, backup and restart. It then hit the separately
retained browser arrival/redraw race: stable-prompt editing began before the
second player's arrival had reached the first page, producing `*wxwx`. The smoke
client now waits for that explicit arrival and the refreshed prompt before
editing. Its new regression failed before implementation; all nine smoke-client
tests and three disposable original-engine two-browser rounds passed afterward
(`browser-arrival-barrier`). No production terminal filtering was introduced and
this does not claim correct editing during arbitrary asynchronous game output.

Run `38282325093` at `02c6e98` subsequently passed native install/rerun/backup,
HTTP and HTTPS browsers, reboot, populated native-to-external cutover, and the
fresh external install/permission rerun. Fresh external backup then failed:
KSYS was correctly echoed and queued, but TOPS-10 reported `BATCON failed to
startup` and `Use OPSER for KSYS logouts since BATCON didn't start`. No clean
marker was fabricated and the backup was refused. Final SQL acceptance was
skipped. Full CI is therefore **not green**.

A read-only check of the local staged fixture found active `SYS:TTY.INI` and
`SYS:BATCON.EXE` at `<055>`; no loss of read access from staged activation was
observed. That local fixture subsequently completed a clean shutdown. Keep
`ci-02c6e98-batcon-failure` and `control-attributes-shutdown.json` in the private
OpenCode evidence directory. Native BATCON/OPSER shutdown recovery needs separate
validation; the controller patch does not establish a safe fallback procedure.

The subsequent [native batch-readiness check](batch-readiness.md) exercises
BATCON before admission and before shutdown; it retains the KSYS/backup guard.
