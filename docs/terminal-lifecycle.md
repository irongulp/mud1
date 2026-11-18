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

Failure-only external run43116428884 at806d3f2 completed in26m19s and passed
installation/persistence/rerun/backup/restart, six scope/batch proofs,14 editor
cases and final clean shutdown. Artifact13899823286 contains five service-stop
reports, all census_enabled:false/shutdown_clean:true, with five native KSYS
completions and no census/device-failure files. This demonstrates successful
shutdown without the extra census in this run, not that earlier failures are
fixed or that census has no timing effect. The local gh-watch command timed out;
the independent completed GitHub result and artifacts establish the outcome.

Importantly, the service journal retained a warning at23:26:50 UTC: connection
af9163f6e8b84d35bb90d87eb82a6899, stage=logout, TimeoutError,6 response bytes,
KJOB echo=true, Logged-off/accounting/final prompt=false, EOF=false. The same
boot completed KSYS (journal23:26:57; guest23:26:46). This repeats
KJOB-echo-only failure with clean subsequent shutdown. The green workflow
therefore means scenario/editor/final-shutdown checks passed, not warning-free
terminal lifecycle. The fixture container was removed after evidence capture.

Next target is that reproduced terminal boundary, not another unchanged KSYS
control. A disposable gateway-only observer could keep the failed connection
open for a separately bounded, command-free observation after the production
deadline, recording only completion/EOF/timing flags. That would distinguish
a late complete logout from continued silence without increasing the production
timeout, replaying KJOB, or declaring cleanup successful. This observer is not
yet implemented; original warning and shutdown evidence must remain separate.

The passive observer is now available with `logout_observation=true` in the
installed shutdown diagnostic. A gateway-only service drop-in loads installed
server code, preserves the original logout warning/result, then waits at most
10s for a prompt after failure. It sends no input and logs structural facts,
elapsed time, EOF/cancellation and complete-report recognition only. Successful
cleanup adds no wait. Partial consumed reports cannot be reconstructed from this
wrapper; the target KJOB-echo-only timeout leaves its bytes in the reader buffer.
Four observer tests plus11 lifecycle/capture tests pass; actionlint passes.
Native execution remains pending. This extends fixture line ownership after a
failure, not production timeouts or a claim of successful cleanup.

## Passive observer native result

Run44342075420 atf1c7ed9 passed the external scenario, six boot/batch proofs,
14 editor/recovery checks and five clean service shutdowns, all with census
disabled. Artifact14446641567 retains three ORIGINAL logout warnings followed
by three passive observations, not warning-free acceptance:

| Journal UTC | Connection | Additional observation |
| --- | --- | --- |
| 16:21:43 | d2d44d11ff2041908061e82995a41afc | 10.0035s, timeout |
| 16:24:19 | ffdd5cf233f14d29a66bddeea50b6d92 | 10.0023s, timeout |
| 16:25:44 | 0845ff287d7347b786ff2a69ba00c457 | 10.0036s, timeout |

All three remained open before/after observation, EOF=false, buffer6 bytes,
KJOB echo=true and Logged-off/accounting/final prompt=false. No extra bytes
arrived during observation and late_complete remained false. Original failed
cleanup results were retained; no additional command or KJOB replay occurred.
Each corresponding boot subsequently completed KSYS. The fixture was removed.

This establishes continued silence for the bounded interval, not permanent
deadlock, a guest root cause, or that the job was already gone. It supplies no
support for increasing the production three-second timeout. Next capture should
correlate the affected terminal with a bounded read-only guest job census while
the line is still held, via the runtime-owned CTY (never a second unsynchronised
console writer). That fixture coordination is not implemented. Preserve the
passive-only result separately because CTY inspection itself changes workload.
Release remains blocked pending lifecycle resolution and final main acceptance.

Coordinated census is now selectable with logout_observation=true and
logout_census=true. The runtime fixture installs a main-thread read hook after
boot; only that owner executes one8s SYSTAT for a fresh per-boot request while
at a known monitor. Re-entrant command reads bypass request processing. Requests
expire, pending cancellation prevents dispatch, and uncertain execution fences
guest cleanup. Gateway retains line ownership for a bounded12s rendezvous, then
the existing10s observation; it sends no guest command. Reports preserve line,
connection, boot token, outcome and separate SYSTAT output. A cancelled census
already executing cannot be undone; no retry is allowed. No production files
changed.20 capture/observer/lifecycle tests and actionlint pass; native pending.

Coordinated run44348369009 at817e5de completed the external scenario, six
boot/batch proofs,14 editor checks and five clean service stops. All four
recorded gateway logouts completed; no logout warning or observer event occurred.
Artifact14448428693 retains five census-disabled shutdown reports and the last
logout-census owner token, but no request/response/SYSTAT file. The runtime
rendezvous was initialized; dispatch and stalled-job inspection were NOT
exercised natively. The fixture container was removed.

This is a successful no-trigger control, not evidence that adding coordination
fixed the three stalls in44342075420. Do not repeat full external compilation
unchanged just to obtain another pass. Before relying on the new diagnostic,
qualify one explicitly labelled healthy-session census request through the same
owner rendezvous in a short disposable fixture; keep that control distinct from
a naturally failed logout. Then target a bounded terminal-reuse/restart workload
to capture an actual recurrence. Neither follow-up is implemented here, and full
release acceptance/root-cause resolution remain open.

`healthy_census=true` now selects an explicit native control after the native
installed lifecycle, with logout_census/logout_observation enabled. It opens a
direct private terminal, verifies the original MUD name prompt (no persona
created), holds that line while requesting the same runtime-owned rendezvous,
and requires exactly one MUDGUEST/MUD job on the assigned line in SYSTAT.
Existing bounded interrupt/KJOB cleanup must complete. Its healthy-report.json
is distinct from failed-logout evidence. No consumed request is retried.
Two control tests plus20 observer/capture tests and actionlint pass; native
control pending. This is a name-prompt/OS-job control, not gameplay acceptance.

Healthy control44391196288 atd9e3db3 passed. Artifact14468392490 contains the
claimed request, matching response and SYSTAT for token
69929433876047529d78f43bbe94eafe: line0/job2/PPN2653,2653/MUD11+117/SL.
The terminal remained open at the original name prompt, completed normal logout,
and healthy-report.json is complete:true. The native installation/rerun/backup/
restart driver also passed three scope/batch proofs and three clean KSYS stops,
all pre-shutdown census disabled; no gateway warnings were observed. The fixture
container was removed.

This natively qualifies owner rendezvous, held-line correlation and cleanup in a
healthy session. It is not a census of a failed KJOB or a fix for44342075420.
Next use a finite terminal-reuse/restart workload with first-failure capture and
no replay; avoid another full external compile solely to repeat healthy proof.
That workload remains to be implemented. Original code and production deadlines
remain unchanged; release/root-cause gates remain open.
