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

Follow-up42877224223 at052d458 passed both browser rounds, eight complete logouts,
no gateway warnings, pre-shutdown census and clean KSYS. Artifact13791928242's
console.log retains SYSTAT: BATCON sleeping, two LOGIN jobs on lines0/1, no busy
devices; shutdown then completed. The separate census file was omitted by the
old artifact whitelist; upload now includes both new shutdown filenames. Failed
KSYS capture remains host-tested, not exercised by this passing run.

`shutdown_reproduction=true` runs only the actual native installation/rerun/
saved-login/timing/backup/restart fixture. A disposable systemd drop-in launches
tests/shutdown_capture.py using the installed venv/cwd/server code, unchanged
service identity/environment/deadlines, and the shared observer. Per-stop UUID
directories retain census/device/report evidence. The wrapper calls original
Runtime.stop once and records exception types without payloads. Five capture
tests,75 focused gateway/carrier/evidence tests and actionlint pass. This mode
is diagnostic, not full release acceptance; no production unit/runtime changes.

Installed-path run42878923580 at3e5926b passed native install, Nginx HTTP/WS,
saved persona, setup rerun/credential preservation, clean backup, restart/
re-entry and read-only inspection. Three guarded boot/batch proofs and three
native KSYS completions passed; sleep checks measured5.990/5.979/6.000s.
Artifact13793023769 retains all three standalone censuses/reports plus service
journals; final shutdown clean:true. No gateway warning or shutdown failure was
observed. The container was removed after evidence collection.

Censuses showed BATCON SL SW (4+40 pages), SL (46+40), then SL SW (4+40);
the latter two also had a LOGIN job on line0 (SL then EW). All had no busy
devices and subsequently completed KSYS. Resident/swapped BATCON or a remaining
LOGIN job alone therefore does not identify the failure. Pre-shutdown SYSTAT
also changes timing/workload; these passes are not a causal fix comparison.
Failure-device capture remains host-tested only. Do not repeat these passing
controls unchanged as a release fix. The next useful capture is the external
installed restart/final-stop path that previously emitted BATCON failed to
startup, with evidence attached to that exact boot. Full uninstrumented release
acceptance and a justified runtime correction remain open.

Select `shutdown_reproduction=true` with `shutdown_scenario=fresh-mariadb`
for the external installed path. It uses the original fresh-external acceptance
driver followed by the14 editor/recovery checks, then the same final stop and
clean-shutdown verification. Per-stop capture uses the same service-only
drop-in and observer; the separate build guest is not instrumented by this
drop-in. Native remains the diagnostic default. Both modes retain per-stop
censuses/reports, any failed-KSYS DZ report and service journals; external mode
also retains its scenario/editor reports. Actionlint and10 focused capture/
lifecycle tests passed before this external invocation.

External run42913344093 at16bc7e0 passed fresh installation, persistence, rerun,
backup/restart, all14 MariaDB10.5.29 editor/recovery cases and final clean
shutdown. Artifact13809302847 retains five service-stop censuses/reports, all
shutdown_clean:true, alongside five native KSYS completions and no gateway
warnings. The scenario verified six guarded boot/batch proofs; these include
the separate build guest, so do not label all six as service-stop captures.
The disposable container was removed after evidence collection.

The initial native service census contained STOMPR and BATCON SL SW; the four
external service censuses had BATCON SL or SL SW, sometimes with a line0 LOGIN
job. All reported no busy devices. The final external stop had BATCON4+40/SL SW,
no LOGIN job and confirmed KSYS completion. No failed-KSYS DZ capture triggered.
This repeats successful shutdown across the actual external lifecycle, not a
diagnosis of42913344093's predecessors or a production reliability fix.

Both installed diagnostic paths now pass with pre-shutdown census enabled.
Before another run, isolate that observation's timing/workload effect: a matched
failure-only capture mode should omit SYSTAT before shutdown but retain the
original queue check, original KSYS budget and post-failure device capture.
Such a comparison is not yet implemented or executed. Do not promote SYSTAT
into a production workaround or run unchanged positive fixtures until green.
Release acceptance on the final uninstrumented main commit remains required.

Failure-only comparison is now selectable with `shutdown_census=false` alongside
`shutdown_reproduction=true` and the chosen scenario. A fixture-only systemd
environment drop-in sets MUD86_CAPTURE_CENSUS=0; each report explicitly records
census_enabled:false. No SYSTAT is issued before shutdown. The observer passes
through original commands/timeouts and captures DZ only after failed KSYS,
without resume/replay. One red/green regression with success/failure subcases
plus existing capture/lifecycle tests totals11 passing tests; actionlint passes.
The earlier statement that this comparison was unimplemented describes the
42913344093 boundary; native failure-only evidence is still pending.
