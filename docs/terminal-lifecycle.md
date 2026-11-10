# Native terminal lifecycle boundary

Manual release acceptance42533310887 at1a858df passed the fresh-MariaDB scenario
and both final clean-shutdown checks, but native-upgrade stopped before HTTPS
persona admission with stage=monitor/TimeoutError. STOMPR quieting failure
preceded it. Both jobs also retained terminal logout timeouts before their
emulators stopped; these warnings are not proof of an emulator-stop ordering bug.

## Host correction and evidence

Admission now records distinct banner, line-assignment, carrier-settling and
monitor-response phases, assigned line, wakeup-submitted and monitor-seen flags.
The one wakeup CR and whole15s admission deadline are unchanged. Error logs add
only byte counts/EOF and fixed structural flags, never terminal payloads.

The controlled logout regression showed that receiving only the `Logged-off`
prefix caused the old gateway to finish cleanup before the native accounting
tail and monitor prompt. Logout now requires the complete report under the same
3s deadline, with one KJOB and no retry. Missing/incomplete reports remain
warnings, with echo/report/accounting/prompt flags. Completion of this protocol
does not assert instantaneous native job disappearance. This fixes a demonstrated
host boundary but is not yet the cause of every retained native timeout.

The diagnostic buffer summary uses the pinned telnetlib3 reader's `_buffer` only
for bounded structural facts. Review that private hook on dependency upgrades.
Tests cover fragmented banner, no input on incomplete assignment, delayed
logout tail, timeout flags/privacy and no replay.78 gateway/carrier/transport
tests pass, including real Chromium heartbeat coverage.

## Focused native fixture

Explicit manual workflow `terminal_lifecycle=true` uses a new pinned runtime
copy, guarded monitor/batch startup and the unchanged native initializer. It
runs the existing two-player browser smoke sequence twice, separated by30s of
running time. No HTTPS configuration or external compilation is needed to test
the upstream terminal lifecycle. Failure stops the sequence; no failed input
or boot is replayed.

Fixture-only wrappers capture the first admission timeout or failed logout
before the gateway closes its upstream writer. They retain phase/line/structural
facts and whether the line was still open, then use the controller-owned CTY for
one bounded SYSTAT and SIMH `show dz` device report. No memory, password or raw
player transcript is captured. SIMH pauses only after the failure for device
inspection; this is diagnostic evidence, not a continuous timing benchmark.
An uncertain simulator resume forbids subsequent guest cleanup commands.

The fixture's diagnostic teardown allowance is separate from the completed
production timeout. Production gateway deadlines remain unchanged. The normal
release workflow is still available with this option false. The focused run is
not full installation, migration or release acceptance.

## Native evidence and shutdown follow-up

Focused run42850687405 at9d9bcd3 passed both browser rounds, eight complete
logouts/line0-1 reuse and clean KSYS with the original STOMP initializer enabled.
Artifact13781515719 retains the evidence; no failure capture triggered.

Full matrix42851873419 at the same commit failed both final shutdown gates.
Native-upgrade stopped during installer rerun: complete browser logout, empty
SHOW QUEUES and one queued KSYS, then completion timeout (artifact13780648179).
Fresh-MariaDB passed installation/persistence/rerun/backup/restart, six guarded
boot/batch proofs and14 editor cases, but final KSYS reported BATCON failed to
startup and timed out (artifact13782678284). Scenario complete:true does not
override shutdown clean:false.

External journal ordering matters:16:38:13 UTC KJOB-echo-only logout timeout
(6 bytes/no Logged-off/accounting/prompt/EOF=false) preceded a CLEAN KSYS at
16:38:15. After a new boot,16:39:22 logout completed but final KSYS failed.
Do not conflate these events or infer empty queues/startup batch execution
guarantees later shutdown. The earlier admission timeout remains unresolved.

The fixture now records SYSTAT before shutdown at a known monitor, retaining the
original queue check and single KSYS deadline. After a failed KSYS it captures
SIMH DZ state before exit, without resuming or sending another guest command.
An uncertain census fences guest cleanup. Capture errors preserve the original
shutdown exception. No automatic OPSER fallback or unconfirmed-disk promotion.
Three red/green tests and73 gateway/carrier/evidence tests pass; this new shutdown
capture still needs native execution. Temporary-worktree loss required recovery
from9d9bcd3; recovered tests live in tests/test_terminal_shutdown_capture.py.
