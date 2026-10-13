# Native batch readiness

`Runtime` now verifies real batch execution before publishing readiness and again
before KSYS. This exercises BATCON while normal logins are still available,
instead of relying solely on its cold start after timesharing has ended.
KSYS completion is still mandatory. No OPSER fallback or synthetic clean marker
is implemented.

## Proof and lifecycle

`tools.batch_readiness` opens a private RICHARD OS maintenance session after the
existing private game/bootstrap check. This is not a persona login. It reserves
an unused six-character `MBxxxx` basename, writes and reads back a text file with
a fresh 128-bit nonce and a control file containing only `.type <name>.txt`, and
submits the native batch request. The helper requires:

1. An acknowledgement for the exact generated name and a request ID.
2. The named request to leave the batch queue before reading its log.
3. Exactly one matching log header for that name, request and RICHARD PPN.
4. The fresh nonce on a native USER output line, followed by batch KJOB, logout
   and final disk-accounting lines, in order.
5. Successful maintenance logout.

Queued acknowledgement, a stale log, a MONITR command echo, or BATCON merely
appearing in SYSTAT is not sufficient. Tabs are expanded for structural parsing:
a line reused after browser VT100 setup returns tabs that a text terminal would
expand to spaces. This normalization does not relax nonce or identity checks.

The probe uses `/OUTPUT:NOLOG` (keep the log, never print it),
`/BATLOG:SUPERSEDE`, `/NORESTART`, `/ASSISTANCE:NO`, and the supplied system's
normal five-minute batch CPU allowance. The host deadline is 45 seconds; guest
accounting ticks do not define that deadline. Individual maintenance operations
are bounded at 10 seconds, with bounded logout still permitted on failure.
The existing 90-second KSYS phase and 180-second systemd stop bound remain.

Only the three exact files belonging to a completed, nonce-bound probe are
deleted. Collisions are checked before writing; failed files are retained for
diagnosis. Failure reports include phase, basename, request ID and exception
type, not raw maintenance transcripts. No probe is run as the protected OPR
system account. Native storage remains independent of MariaDB.

On startup, failure blocks public readiness. On normal shutdown, failure blocks
a clean-backup marker even if the supervisor subsequently completes a best-effort
KSYS. Bridge/database services remain available through guest cleanup.

## Validation

169 focused batch/controller/inspection/deployment/gateway/browser tests passed
on macOS and native ARM AlmaLinux Python 3.12. Regressions were observed failing
before implementation for proof matching, deadlines, startup ordering, failure
gates, log-print suppression, active-log synchronization, tabbed logs and probe
notification framing.

Disposable native checks:

```sh
python -m tests.integration_guest_control \
  --assets /path/to/runtime-checkout --output /private/new-batch-check --rounds 5
python -m tests.integration_batch_failure \
  --assets /path/to/runtime-checkout --output /private/new-batch-failure
```

The failure test temporarily withholds BATCON only on a fresh copied image,
confirms that a submitted probe cannot complete, restores the binary, and asserts
that readiness and clean-backup publication remain blocked. Do not direct it at
an existing game. Source hashes are checked.

Private evidence retained under the OpenCode temporary directory / disposable
containers:

- `batch-research-1` through `-5`: native command research, including retained
  boot/notification failures; the RICHARD batch executed and logged off.
- `batch-readiness-native-1` through `-6`: retained parser, boot and admission
  failures; final two-cycle normal/staged/reboot check passed.
- `batch-unavailable-native-1`: real missing-BATCON failure gate passed, binary
  restored, no clean marker published.
- `mud86-admission-probe:/tmp/batch-readiness-linux-final` and
  `/tmp/batch-unavailable-linux-final`: final ARM native success/failure controls
  passed, including two normal clean shutdowns and source preservation.
- `batch-installed-acceptance` through `-3`: retained installed failures. Private
  tracing identified valid logs rejected because VT100 preserved tabs. A separate
  attempt hit the experimental ten-second guest CPU limit; that restriction was
  removed in favor of the normal native allowance, without extending host waits.
- `batch-installed-acceptance-4`: installed ARM rerun, saved login, backup,
  restart, re-entry and editor checks passed. This continues the retained fixture;
  it does not erase the earlier failures or substitute for native-x86 CI.

Native-x86 complete fresh-install/cutover acceptance remains the final gate.
This change does not establish that all historical boot/shutdown failures have
the same cause.

## Source references

The 7.04-era GALAXY source's
[QSRT10 KSYS path](https://pdp-10.trailing-edge.com/cuspbinsrc_1of2_bb-x128c-sb/01/10,7/galaxy/quasar/qsrt10.mac.html)
starts BATCON if necessary and waits for registration before forwarding KSYS.
[QUEUE help](https://pdp-10.trailing-edge.com/cuspbinsrc_1of2_bb-x128c-sb/01/10,7/galaxy/queue/queue.hlp.html)
documents the submission, logging and list switches used here. The sources explain
the design; native tests above establish behavior on the supplied image.
