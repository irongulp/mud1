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

## Bounded recurrence experiment

`logout_workload=true` with shutdown_reproduction/fresh-mariadb, no shutdown
census, and logout observer+census enabled selects one fresh external install
and at most3 cycles. Cycle1 creates/SAVEs one ordinary persona; each cycle
logs in, SCOREs, QUITs and closes the browser. Clean cycle1 permits one backup,
clean cycle2 permits one restart, then cycle3 ends the budget. No installer
rerun/editor matrix or repeated compilation is performed within this experiment.
Journal cursors isolate each cycle; the first warning fences later cycles.
A bounded30s observer allows the existing failed-logout census/observation to
finish, then classifies reproduced-captured, reproduced-capture-failed,
cleanup-unconfirmed or not-reproduced. Reproduction intentionally returns a
nonzero diagnostic status; cleanup and evidence upload still run.

This serialized workload waits for cleanup evidence before management commands,
unlike the original driver's immediate continuation after socket closure. A
negative result cannot exclude a management/cleanup overlap race. Existing
KSYS/admission failures remain separate, not inferred from logout results.
Four classifier/control tests plus22 existing focused tests pass; actionlint
passes. No original source/server changes. Native result pending.

Bounded run44396531095 atcc163f9 exhausted its3-cycle budget with explicit
outcome:not-reproduced. Artifact14470764931 retains all three completed-logout
journals, four census-disabled clean service shutdown reports and final
clean:true. No gateway warning, census request or stalled-job snapshot occurred.
The container was removed. This is a negative experiment, not a fix or full
release acceptance. It excludes neither intermittency nor teardown overlap.

Total runtime24m36s remained dominated by initial external preparation; reducing
post-install cycles did not make the overall run short. Do not extend the budget
or repeat the same run unchanged. If continuing logout diagnosis, first review
the existing failing journals for the ordering of socket close, KJOB warning,
gateway stop and runtime stop. A matched bounded comparison of immediate
management continuation versus explicit cleanup acknowledgement could then
test the overlap hypothesis, but neither a causal overlap claim nor such a
comparison has been established. Keep original admission and KSYS/BATCON
failures separate; resolving this negative experiment does not close them.

## Existing-journal ordering review (no new CI run)

Artifact14446641567 (44342075420) establishes the following sequence using
HOST JOURNAL UTC timestamps throughout, not the embedded guest clock:

| Connection prefix | Logout timeout | Gateway stopping | Observation ends | Runtime stopping | KSYS completed |
| --- | --- | --- | --- | --- | --- |
| d2d44d11 | 16:21:43 | 16:21:50 | 16:21:53 | 16:21:53 | 16:21:55 |
| ffdd5cf2 | 16:24:19 | 16:24:26 | 16:24:29 | 16:24:29 | 16:24:31 |
| 0845ff28 | 16:25:44 | 16:25:55 | 16:25:54 | 16:25:55 | 16:25:57 |

All were line0. In the first two cases gateway shutdown began during the
additional passive observation, seven seconds AFTER the original timeout;
cleanup was awaited, not cancelled. In the third, the full ten-second
observation ended before gateway shutdown began. All retained only the KJOB
echo, then closed the upstream connection and later completed KSYS.

The non-passive run43116428884/artifact13899823286 independently corroborates
the ordering: connectionaf9163f6 warned/closed23:26:50, gateway/runtime stopping
23:26:54, operator launch23:26:55, KSYS completion23:26:57 (2026-11-11 UTC).
Thus the logged service stops cannot explain the ONSET of these four stalls.
This is narrower than excluding all earlier management activity or every
historical failure, but it removes the evidence basis for the proposed
immediate-versus-delayed service-stop experiment. Do not run that comparison
based solely on the preceding negative serialized workload.

Exact QUIT, browser-close receipt and KJOB-dispatch timestamps were not logged.
The six-byte echo plus timeout establish that KJOB was submitted before the
warning; subtracting3s is only an estimate, not a recorded dispatch timestamp.
The timestamp inside aiohttp's access message is request start, NOT closure.
Use journal timestamps for service ordering and retain that precision limit.

Next analysis should focus on the guest KJOB/LOGIN/terminal execution path and
the missing stalled-job state. Healthy rendezvous qualification does not fill
that gap. Any further native experiment needs a distinct hypothesis and bounded
budget; no new run or production correction was made for this review. Admission
and KSYS/BATCON failures remain separate unresolved tracks.

## Source trace: what an echo-only KJOB does and does not prove

This is source analysis, not a captured failing guest PC or a binary-equivalence
claim. References use the Stacken archive at commit
`6e18f5ebefd9acb0d718ef31a08f33a60fc9fca2`:

- [COMCON.MAC][kjob-comcon], V1736, blob
  `de5809c4ab5ca2270c25718c1d76bef6b1b5f5ea`.
- [SCNSER.MAC][kjob-scnser], blob
  `873207618feab8bc059d3a74adbcafc8b928fc51`.
- [LOGIN.MAC][kjob-login], V65(3010), blob
  `8591b0ee13be2caa57fe9bf91054f2448a347932`.
- [SYSTAT.MAC][kjob-systat], V704(416), blob
  `a8e584a9c2f542144495551b0ff74e5c5eedee5e`, and
  [SYSTAT.HLP][kjob-help], blob `d3fb83a168264983677e5e29cd2a0dba8c0c6c88`.

The existing local `build/monitor/dskb:10_7.mon..comcon.mac` and
`dskb:10_7.mon..scnser.mac` have Git blob hashes matching the archived files;
these local reference files were read without modification. The running
runtime-v1 monitor/LOGIN/SYSTAT binaries have not been matched instruction by
instruction to these sources; do not derive live addresses from this review.

### Execution boundaries

1. **Terminal echo precedes command execution.** SCNSER's `ECHBRK`
   (2281–2283) calls `COMSET` (8895–8906), which marks a command request and
   wakes COMCON. `TTYCOM` (8981–9032) subsequently selects the line.
   Receiving `kjob\r\n` proves that an echo reached the host, not that logout
   code ran or that the job was destroyed.
2. **Logged-in KJOB runs SYS:LOGIN.** COMCON `KJOB3` (728–753) attaches the
   terminal, sets the bypass-forced-program bit, ensures the memory limit
   permits LOGIN, and jumps through `RUNAME`. It is not immediate job deletion.
   A job that is not logged in follows a different `KJOB4`/`JOBKL` path.
3. **The program-name column is not a PC.** `ARCOM1` (4446–4447) stores the
   requested name in `JBTPRG` before loading. `RUNCM` (4458–4490) may involve
   the file-daemon path or wait for core; `GJOBX` (9679 onward) loads segments.
   SYSTAT prints `.PRG` at 2218–2219. Thus `LOGIN` in a census does not prove
   LOGIN's first user-mode instruction has executed.
4. **There is work before the report.** LOGIN `KJOB` (1847–1887) scans switches,
   processes SWITCH.INI, checks locks, handles other jobs, deletes temporary
   files, sets the path and checks quotas before calling `SUMARY`.
   `CHKQTA` (2839–2869) includes structure dismount/quota work. Disk or resource
   waits are candidates, not demonstrated causes. There is no basis here for
   assuming a MariaDB lookup or an accounting-daemon timeout caused the stall.
5. **The final dot also precedes final destruction.** `SUMARY` prints
   `Logged-off` at 2262, disk accounting at 2301 onward, then the dot and output
   flush at 2320–2323. It waits for output completion at 2337–2344 and returns
   before the caller executes `LOGOUT` at 1887. A complete report is stronger
   than the old prefix-only check, but it is not independent proof that the
   job slot has vanished. Preserve the report requirement; do not replace it
   with echo, silence or a delay. The echo-only cases have not reached even
   that report boundary from the host's perspective.

On the host, `server/gateway.py` cancels and awaits the transport tasks before
calling `logout_guest` (434–447). The normal output reader should therefore
not compete with the cleanup reader for the KJOB reply. This code ordering is
not proof that every byte reached Python, and does not exclude transport loss.

### Interpret the first failed-session census

Keep the full current-boot SYSTAT output and correlate the requested terminal,
connection and owner token. Do not apply the healthy control's requirement
that the row must say `MUDGUEST/MUD`: logout can change the program and login
status. Retain other jobs and detached rows too. All four known failures were
line0, so no decimal/octal line-number conversion is needed for those cases.

| Observed census | Supported interpretation | Next boundary if witnessed |
| --- | --- | --- |
| Original line still lists MUD with `^C`, `CW` or `^W` | Old program label and stopped/command-wait state remain visible | Terminal command request/dispatch and run transition; not proof that KJOB was never decoded |
| Line lists LOGIN with `CW`, `^W`, `^D`, `OW`, `DI`, `PI` or a memory/resource wait | Logout's launch or execution is waiting | Identify that wait's owner/resource and, only then, a version-matched PC/stack capture |
| LOGIN with `RN`, `WS`, `TS`, `DS` or `PS` | Runnable or wait-satisfied at the sampled instant | Scheduling/progress; one snapshot cannot establish a loop or starvation |
| LOGIN with `TI` | Terminal input wait | Command rescan/input state; never send an extra CR as a diagnostic retry |
| LOGIN with `TO` | Terminal output wait | Guest output queue/device/host delivery boundary |
| LOGIN with `SL` or `HB` | Sleep or hibernation | Determine the caller; `SL` alone does not identify the summary-output wait |
| No job attached to the held line | No attached job visible at census time | Check detached rows and identity limits, then terminal/report delivery; not automatic proof of successful cleanup |
| Census unavailable or uncertain | No usable guest-state evidence | Preserve failure and input fence; do not infer absence, replay SYSTAT or issue another KJOB |

SYSTAT's state decoder is at 2261–2293: command/operator/daemon/stopped states
take precedence; otherwise it reads the monitor queue code, distinguishes
sleep from hibernation and terminal input from output wait. `SYSTAT.HLP`
defines the remaining queue codes. A `DI` row does not identify a particular
file, and `EW` does not identify a particular lock. Collection is sequential,
not an atomic snapshot. A line-only correlation cannot prove the identity of a
detached job when the original job number was not recorded.

### Decision after this review

The existing one-shot, runtime-owned census already collects the columns needed
for this first split. No additional guest commands or production changes are
justified by the source trace. Healthy census and negative-workload results
still supply no stalled-job state. The next useful native evidence is one
natural echo-only failure captured with this mechanism, classified using the
table above; a successful control or more clean shutdowns cannot substitute.

Do not rerun the exhausted three-cycle workload unchanged. Before authorizing
another recurrence experiment, specify the workload difference and finite
budget, and preserve the original cleanup sequence rather than silently adding
acknowledgement waits. Select deeper tracing only from the observed branch.
There is no demonstrated root cause or fix, and no basis to combine admission,
logout and KSYS/BATCON failures into one defect.

[kjob-comcon]: https://github.com/PDP-10/stacken/blob/6e18f5ebefd9acb0d718ef31a08f33a60fc9fca2/files/stacken-tape-backup/dskb:10_7/mon/comcon.mac
[kjob-scnser]: https://github.com/PDP-10/stacken/blob/6e18f5ebefd9acb0d718ef31a08f33a60fc9fca2/files/stacken-tape-backup/dskb:10_7/mon/scnser.mac
[kjob-login]: https://github.com/PDP-10/stacken/blob/6e18f5ebefd9acb0d718ef31a08f33a60fc9fca2/files/stacken-tape-backup/dskb:10_7/login/login.mac
[kjob-systat]: https://github.com/PDP-10/stacken/blob/6e18f5ebefd9acb0d718ef31a08f33a60fc9fca2/files/stacken-tape-backup/dskb:10_7/systat/systat.mac
[kjob-help]: https://github.com/PDP-10/stacken/blob/6e18f5ebefd9acb0d718ef31a08f33a60fc9fca2/files/stacken-tape-backup/dskb:10_7/systat/systat.hlp

## Original-sequence recurrence budget

Further inspection of artifact14446641567 places the successful creation/logout
at16:20:12–20, followed by the installer rerun's stop/restart, then the three
saved-player failures listed above. The serialized three-cycle experiment
omitted the preceding installed editor/inspection checks and installer rerun.
Their relevance is unknown; the proposed recurrence preserves them rather than
assuming the reduced workload is equivalent.

`logout_sequence=true` selects `tests.integration_logout_sequence`: **one**
execution of the original fresh-external driver, capped at its four browser
admissions. It retains the original create/SAVE, inspection/editor, setup rerun,
saved login, backup, saved login, restart, saved login and editor-restart order.
No extra healthy cleanup acknowledgement wait is inserted between operations.
The separate fourteen-case database-editor matrix is omitted.

Host journal reads before/after driver operations fence the next operation
when a logout warning is observed. An operation already in flight finishes
under its existing deadline; it is not terminated or replayed. A warning uses
the existing bounded observation/census path and ends the budget, reporting
reproduced-captured or reproduced-capture-failed. A driver error is retained
separately even when cleanup also fails. At the end only, a bounded settle
requires complete-logout evidence for all four connection IDs; an earlier
success cannot cover a missing final cleanup. Installer readiness failures and
final native shutdown remain separate outcomes.

This changes the exhausted experiment by restoring the original workload,
not by assuming a shutdown-overlap cause. Journal reads and diagnostic hooks
still perturb timing. A negative result is not evidence that the precursor
steps are irrelevant, and does not authorize an unchanged rerun. One CI
execution is the budget; stop/retain/classify on its first observable warning.
Initial external preparation still costs roughly twenty minutes.

Seven new sequence tests cover first-warning fencing, in-flight operation
completion, unchanged healthy operation order, the four-login cap, final-session
cleanup and concurrent driver/capture errors. All33 focused tests and actionlint
pass. The first native outcome is below. Select shutdown_reproduction/fresh-mariadb,
logout_observation/logout_census/logout_sequence=true and shutdown_census=false;
the workflow rejects combination with the old workload or healthy control.

### First failed-session census: reproduced, captured, then late report

Run **44414949900**, commit `263637a`, artifact **14480551130**, finished with
the intended diagnostic failure after21m21s. `logout-sequence/report.json`
reports `reproduced-captured`, phase `login-2`, `logins_submitted=2`. The first
creation/logout, inspection/editor checks and installer rerun completed. The
second session reproduced the echo-only KJOB timeout; the driver stopped before
backup or either subsequent login. The external acceptance report correctly
remains `complete:false`. Evidence was also downloaded privately to
`runtime/logout-sequence-captured-44414949900/` in the diagnostic worktree.

The census request/response match connection
`5647fe11ff514a9698cc92c4a5e46011`, line0 and boot token
`dd0e515186be41e6b6143881efc156e2`. Its original SYSTAT row is:

```text
Job    Who     Line#    What   Size(P)  State   Run Time
 2  2653,2653    0      LOGIN   10+31   RN             6 $
```

The LOGIN high segment is also listed with one user. FILDAE is `HB SW`,
ACTDAE `SL`, BATCON `SL`; the report says no busy devices. These are
instantaneous observations, not evidence of the preceding wait's cause.
The six runtime units belong to the job's reported cumulative runtime; they
are not six seconds spent in KJOB. The existing source caveat about the program
label and non-atomic state sampling still applies.

Host journal UTC ordering:

| Event | Time |
| --- | --- |
| Session started | 23:08:56.130493 |
| Line0 assigned | 23:08:57.005004 |
| Original logout timeout, six echo bytes only | 23:09:06.551951 |
| Runtime-owned SYSTAT output recorded | 23:09:07 (service log resolution) |
| Complete late logout report observed | 23:09:07.660740 |
| Gateway stopping | 23:09:07 (service log resolution) |
| Runtime stopping | 23:09:08 |
| KSYS completion recorded | 23:09:10 |

The observer recorded `late_complete:true`,180 bytes including the original
echo, `Logged-off`, disk accounting and final dot, with the terminal open
throughout. Elapsed time was1.108328475 host seconds from the start of the
post-timeout observation, which includes the census rendezvous. The journal
warning-to-observation interval is1.108789s. Neither is an exact guest execution
or byte-arrival timestamp: the observer waits for the census response before
reading the terminal, so the report may already have been buffered.

**Interpretation:** the sampled branch is LOGIN-labelled/runnable, rather than
MUD/stopped, absent job or a sampled terminal/disk wait. This supports focusing
on scheduling/progress or a transient wait that had ended by the sample. It
does not establish a loop, starvation, a particular blocked resource, or a
transport fault. The same echo-only timeout signature now has a witnessed
late report, unlike44342075420's three ten-second passive-silence cases.

SYSTAT introduces a runnable CTY job and terminal activity. Its temporal
association with the late report is **not** proof that it unblocked LOGIN;
natural delayed completion and an observation-induced scheduling effect remain
distinguishable hypotheses. Do not prescribe SYSTAT as a workaround, increase
the production timeout, upgrade the original failed cleanup, or infer the
three earlier stalls would also have finished at this time.

All three captured service stops have `shutdown_clean:true` and
`census_enabled:false`; the failure-triggered census was separate. Final
shutdown verification and container removal passed. No second KJOB or failed
census replay occurred. Existing host late-report tests already assert that
the original failed result remains false. No code change or new run was needed
to record this result.

The one-run recurrence budget is exhausted, with the desired state split now
obtained. Before further native work, select a targeted way to distinguish
natural runnable progress from CTY-induced progress; any PC/queue sampling must
be matched to the actual runtime binary and must acknowledge its own timing
effects. More unchanged installation cycles or generic timeout extensions
cannot answer that question. Admission and KSYS/BATCON failures remain separate,
and this diagnostic failure is not release acceptance.

### Passive-before-census timing experiment

The next distinct experiment retains the original four-admission driver and
first-warning fence, but reverses the post-failure observation order:

1. After the unchanged production cleanup timeout, read the failed terminal
   silently for ten seconds. A complete late report ends observation without
   requesting SYSTAT, and is classified `reproduced-passive-completion`.
2. Only an incomplete, still-open terminal gets the existing one-shot census.
   Terminal reads continue concurrently with its twelve-second rendezvous.
   Total post-failure time is bounded at22 seconds, the previous maximum.
3. Record host monotonic observation times for the first bytes beyond the
   initial buffer and the report prompt. The runtime brackets its actual first
   CTY write and Enter write, and records command return. No terminal payload
   is added to the report; original raw census output remains private evidence.

The runtime and gateway share the container's monotonic clock. A prompt observed
before the first CTY write proves that this diagnostic SYSTAT did not trigger
the report. A prompt observed after Enter only establishes ordering: native
completion or transport delivery could precede the host read. Overlap with a
write bracket is ambiguous. Other driver/runtime activity must still be checked
in the journals; the silent phase suppresses this diagnostic request, not every
possible guest or host activity.

The terminal reader is cancelled and reaped on deadline/cancellation. EOF,
unexpected prompt or the16-KiB observation limit stops observation without an
extra guest command. A timed-out census retains its existing cancellation/input
fence. All late outcomes preserve the original failed cleanup result.

This is fixture-only (`logout_sequence` selects `logout-timing.conf`); the old
passive observer remains available to other diagnostics. Seven added tests
cover passive completion, concurrent reading, terminal termination, bounded
cancellation, actual-send timestamps and classification. All40 focused tests,
actionlint and diff checks pass. One original-sequence CI execution is the
budget, ending at the first warning; native outcome pending. A post-CTY result
alone will not justify a causal recovery claim or another unchanged run.

#### Initial timing run: fixture import failure before admission

Run **44419471205**, commit `2252521`, artifact **14482557212**, ended after
20m34s with `experiment-error`/`AssertionError`, phase `host-command:bash`,
zero browser admissions. The installed gateway launcher failed at23:37:38 UTC:
`logout_timing.py` imported `tests.logout_census`, but the installed release
does not contain the checkout's `tests` package. The subsequent gateway
readiness timeout at23:38:08 was a consequence of that import error, not a
native admission or logout stall.

Only the census owner file exists: no failure request, SYSTAT response or timing
observation was generated. Both captured runtime stops were clean; final
shutdown verification and fixture removal passed. Private evidence is retained
at `runtime/logout-timing-44419471205/`. This is neither a negative recurrence
result nor evidence for either timing hypothesis.

A subprocess regression reproduced the exact missing-package error with only
`server`/`tools` available in an isolated release layout. Direct fixture launch
now imports sibling helpers; package-based unit tests use relative imports.
The regression also launches the real observer with timing/census enabled and
`--help`, checking imports without booting or connecting to a guest. It runs in
the existing pre-install test step, before expensive external compilation.
All41 focused tests and actionlint pass. One corrected execution of the
unexercised experiment is planned; there is no changed production deadline or
guest-command policy and no automatic series of retries.

#### Corrected timing run: cutover console boundary blocked

Run **44422985974**, commit `a2be938`, artifact **14483726865**, ended after
18m35s with `experiment-error`/`AssertionError`, phase `host-command:bash`,
zero browser admissions. The installer failed inside `external_cutover`,
after the build branch and before external import/admission:

```text
external_install.cutover -> protect_bridge_terminals
 -> machine.command('type sys:tty.ini')
 -> submit_line -> pending(encoded[:position])
ControlError: Unexpected pending control output
```

The retained traceback identifies the per-character pending-output check at
`tools/guest_control.py:89`, before the Enter write at115. This command was not
submitted with Enter; the retained report does not identify how many preceding
characters, if any, had been sent. The rejected byte and pending frame are not
in the traceback. Do not label the preceding BATCON idle notice as the culprit
merely because it appears earlier in the transcript, or relax the guard to
discard unidentified output. The bridge-terminal routine failed on its first
TYPE, before its configuration writes.

The installer transcript records the cutover guest's subsequent SHOW QUEUES,
one KSYS with completion, and simulator Goodbye. Its embedded guest clock
crossed midnight (`0:00:33`/`0:00:34`); these are not host UTC timestamps.
The separate initial service stop has `shutdown_clean:true` in the retained
shutdown-capture report. Only one such service report exists: do not describe
the cutover's foreground shutdown as a second captured service stop. Final
shutdown verification and fixture removal passed.

Only a census owner file was retained, with no request/response; the sequence
journal is empty and external acceptance is `complete:false`. Private evidence:
`runtime/logout-timing-44422985974/`. The corrected gateway launcher was never
reached, so this run neither establishes its native startup nor exercises
passive-before-census timing. The installed-layout host regression remains its
verification. The prior runnable-LOGIN capture remains the latest logout evidence.

The corrected one-run budget is now exhausted. No further CI run is launched.
Before another expensive installation, the separate cutover console boundary
needs a focused evidence plan: retain the bounded pending frame and command
stage from a disposable build, without publishing persona capture/password
data, replaying partial input or weakening exact-echo guards. A source review
alone cannot reconstruct the missing byte. The natural-versus-CTY timing
question remains unanswered; this setup failure supplies no evidence for either
hypothesis. This update is documentation-only; the previous41 host tests remain
the code baseline.

#### Focused boundary review: witnessed midnight BIGBEN format

The follow-up review found useful evidence already in the retained install
transcript, lines665–668, immediately before cleanup's Ctrl-C sequence:

```text
Monitor KS10
System uptime :14:43
Current date/time Thursday 19-Nov-126 0.00
```

Although the traceback does not identify the rejected byte, this complete
visible notice has a definite incompatibility with the host parser. Its uptime
format was accepted, but the current-time field required nonempty hours and
`HH:MM:SS`; `0.00` was rejected. Replaying this notice with CRLF framing through
`submit_line` reproduced `Unexpected pending control output` at the same
per-character pending check, before any input. The artifact was collected as
normalized text, so this does not reconstruct the original byte boundary or
prove that no other pending content existed.

Pinned [COMCON.MAC][kjob-comcon] explains the representation:

- `BIGBEN`,5343–5358, prints uptime with `PRTIME`, then calls `DAYTIM`.
- `DAYTIM`/`DATIME`,5268–5282, call `PRNOW` for the time of day.
- `PRNOW`/`PRTIM`,7449–7479, use seconds.hundredths below one minute,
  suppress zero hours otherwise, and print full hours when nonzero.

The local COMCON reference still hashes to
`de5809c4ab5ca2270c25718c1d76bef6b1b5f5ea`. This remains a source-format
explanation corroborated by output, not an instruction-level runtime binary
comparison. In particular, `0.00` is seconds.hundredths at midnight, not an
hour.minute display.

The narrow host correction extends only the current-time field in the existing
complete BIGBEN recognizer to accept these formats. Two added regression tests
cover the witnessed midnight frame and source-supported variants, incomplete
frames, malformed times, unknown trailing output, absent command echoes and
an interleaved notice without the expected echo. All89 guest-control,
verified-controller, deployment/external-deployment and diagnostic tests pass.
The diagnostic pre-install test step now includes the control regressions.
Blue review retained the bounded complete-frame recognizer, exact command
echoes, existing deadlines and no-replay behavior.

This resolves a reproduced host parsing defect and supersedes the proposal to
add capture instrumentation for this particular mismatch: existing evidence
was sufficient for a focused test and correction. Native cutover with the fix
has not run. No new CI execution was launched during this review, and neither
the LOGIN timing question nor the release acceptance gates are closed.

### Post-correction native run: installation passed, backup KSYS failed

User-authorized run **44792601384**, commit `1859326`, artifact **14659745438**,
ended after23m12s. Initial external installation, persona creation/SAVE,
inspection/editor checks, installer rerun and the second saved-player login
completed. Both browser sessions logged complete logout reports with
`recovered=False`. The wrapper then reported `experiment-error`,
phase `host-command:sudo`, two admissions: the failing operation was
`sudo mud86ctl backup`, not a third login or the logout observer.

This is installed-path progress past the previous setup blockers, including
native launch of the corrected timing fixture. The install log contains no
BIGBEN midnight notice, so it does not independently exercise the new `0.00`
branch; that branch retains source/replay-test evidence.

Host service journal UTC:

| Event | Time on 2026-11-20 |
| --- | --- |
| Creation-session logout complete (`e42db8b9…`) | 18:45:15 |
| Installer-rerun shutdown KSYS queued | 18:45:19 |
| Installer-rerun KSYS completed | 18:45:52 |
| Saved-session logout complete (`8affd0a8…`) | 18:47:03 |
| Gateway stopped / runtime stopping for backup | 18:47:03 |
| SHOW QUEUES reports empty; KSYS queued, request9 | 18:47:06 |
| Waiting for BATCON to start for KSYS logouts | 18:47:06 |
| Shutdown deadline, diagnostic halt/DZ report/Goodbye | 18:48:34 |

The queued event and wait message establish that this KSYS was submitted and
processed beyond echo. No completion message followed before the deadline.
The preceding rerun shutdown spent about33 host seconds from queued event to
completion; this is an observation, not justification for increasing deadlines
or a demonstrated mechanism linking the two stops.

The existing failure-only device capture was exercised natively:
`shutdown-capture/16e1d7c11d524fcab8ed24061d8be892/report.json` has
`shutdown_clean:false`, `error_type:TIMEOUT`, `census_enabled:false`,
`device_report_completed:true`. After the failure, SIMH halted at
`PC:354741 (MOVE 2,720642)` and one `show dz` returned32 configured lines,
listener2020, raw listeners6/7 and **two current connections**. That aggregate
report does not identify the connected lines, their jobs, or BATCON's state.
The two connections are compatible with the external bridge remaining alive
during shutdown, but are not independently identified as its sockets. No
version-matched PC/stack analysis or active-browser inference is justified.
Capture ended with simulator Goodbye; no resume or second KSYS was issued.

Two other service-capture reports are clean (initial native service and the
installer-rerun stop). The foreground cutover also recorded KSYS completion
and Goodbye in `install.log`. The final verification correctly failed because
the backup stop was unclean. `backup.log` reports:
`Guest shutdown was not confirmed clean; recover and stop it before continuing`.
No backup success, restart, later admissions or complete external acceptance
is claimed. Container removal passed.

Only the census owner file exists; there was no logout warning, census request
or passive timing observation. Thus this is neither a complete four-session
negative result nor an answer to natural-versus-CTY progress. Private evidence
is retained at `runtime/logout-timing-44792601384/`.

The authorized one-run budget is complete. No further CI run was launched.
The immediate blocker is now the separately evidenced KSYS/BATCON path despite
successful browser logout reports. Next review should trace the specific
BATCON-start wait and identify the guest state needed to distinguish a pending
start from an already-started worker that cannot progress; the aggregate DZ
capture cannot do that. The logout timing hypothesis remains open. This
documentation-only result does not change the89-test code baseline or satisfy
either full uninstrumented release job.

### KSYS source trace: QUASAR registration versus BATCON logout work

Read-only source analysis uses the same pinned Stacken commit as the earlier
KJOB review:

| File | Git blob |
| --- | --- |
| [QSRT10.MAC][ksys-qsrt10] | `7c26a1b06a6a21167369fab5a10eb2ffb563323e` |
| [QSRADM.MAC][ksys-qsradm] | `9338f20aa291daec535b23494128560aa60cfd15` |
| [QUASAR.MAC][ksys-quasar] | `6cce7952c1c58e1d19a866eba3b8f3589b0decdb` |
| [BATCON.MAC][ksys-batcon] | `c7d37893b305bfad5c38f8ca980bee116b98eaec` |
| [BATMAC.MAC][ksys-batmac] | `813f20f893c8c0f060c9091a70449e09a14e85a0` |

BATMAC39–44 declares105(5027), matching the batch-log banner in44792601384.
That corroborates a version label, not full binary equivalence or usable live
addresses. No binary inspection, guest execution or CI run occurred here.

**The wait message belongs to QUASAR's processor-registration state.**
QSRT10's KSYS.2/KSYS2A at4193–4218 looks up BATCON's create-job block (CJB)
and processor status block (PSB). A PSB marked `PS.RUN` takes the direct
KSYS-message-send path. Otherwise, an absent PSB or `PS.FIR` can trigger
startup through `I$SXXX`/`I%CJOB`; an existing waiting PSB can reach the same
wait branch without another startup call.

At4248–4258 QUASAR sets `PS.KSY`, clears the startup retry count, sets
`PSBUDT` and prints the observed message. Thus its emission establishes neither
“no BATCON job exists” nor “a new BATCON process was just created.” It means
QUASAR selected the not-yet-registered-as-running branch at that point. This
`PS.RUN` is QUASAR bookkeeping, not SYSTAT's scheduler state `RN`.

QSRADM139–197 validates a processor HELLO, records its PID, sets `PS.RUN`,
and, when the previous state was `PS.KSY`, calls `I$SKSM`. QSRT104270–4285
then sends IPCF message `.QOKSY` to BATCON. There is no successful-send WTO
in that routine. The absence of later operator messages cannot show that
registration or message delivery never occurred.

**BATCON does the subsequent job scan and completion.** BATCON1548–1558
initializes KSYS state, scans eligible jobs with `KSYJOB`, and immediately
calls `KSYFIN` if none remain. Otherwise it creates dedicated KSYS streams.
`KSYFIN` at882–895 emits `KSYS processing completed`. Successful browser
logout does not remove the registration/message/completion dependencies.
The job scan also filters operator and certain batch/PTY jobs; TCP connection
counts are not its input and cannot substitute for that scan.

**The guest has its own registration expiry, but its silence is ambiguous.**
QSRT104253–4255 adds decimal30*3 to universal date/time: this is approximately
30 guest seconds (the source comment says30), not a90-host-second timeout.
QSRADM2675–2686 checks the deadline and can print `BATCON failed to startup`
and `Use OPSER for KSYS logouts since BATCON didn't start`. QUASAR309–338
updates `G$NOW`, handles KSYS/message traffic, checks waiting PSBs when no
message was received, and schedules sleep/wakeup. Neither failure notice appears
in44792601384. That does not prove a stuck timer: the PSB might have transitioned
to running, the loop might not have reached the check, output might not have
been delivered, or deployed code might differ. OPSER is historical source
advice here, not an adopted fallback.

#### What the existing capture can distinguish

The last boot census at18:46:43 host UTC showed job1 `[OPR]`, detached,
`BATCON 46+40 SL`. The wait message followed at18:47:06, about23 seconds later.
That demonstrates earlier process presence and batch readiness, not its later
registration, continued existence or progress. The failed stop provides only
the later aggregate DZ count and halted PC; it has no current PSB or BATCON
state. The earlier33-second successful stop is not proof of which stage consumed
that interval.

| State needed at failure | Interpretation if observed with matched identities/layouts |
| --- | --- |
| No BATCON job; QUASAR PSB still `PS.KSY` | Investigate launch/exit and registration expiry |
| BATCON job exists; PSB still `PS.KSY` | Startup/HELLO delivery or QUASAR processing boundary |
| PSB `PS.RUN`, PID matches BATCON; no accepted KSYS state | Dispatch, IPCF delivery or BATCON receive boundary |
| BATCON `G$KSYS` set, job bitmap/streams active | Registration completed; investigate job scan/PTY/logout progress |
| BATCON completion reached but host saw none | Operator-message/transport delivery boundary |
| Missing or unmatched state | Unresolved; do not infer absence, timer failure or deadlock |

A single state sample still cannot establish lack of progress. `G$NOW`,
`PSBUDT`, PSB flags/PID and BATCON's `G$KSYS`/`KSYCNT`/stream state are useful
only with the deployed layouts and job identity established. Do not derive
addresses from these source line numbers or interpret the monitor PC354741
as BATCON's user PC.

#### Next bounded evidence gate

The source review replaces the vague “BATCON did not start” hypothesis with
three explicit stages: registration, KSYS message acceptance, and logout work.
Before another run, establish a read-only capture for those stages against the
actual deployed binary layouts. Prefer capture after the original deadline and
existing diagnostic halt, with no resumed guest execution; any memory evidence
must remain private and avoid persona/password contents. Do not add an
unqualified SYSTAT/OPR exchange during the wait, since that perturbs the timing
being investigated. A label-only census or another aggregate `show dz` cannot
answer the PSB/HELLO question.

No new capture code, executable modification, longer timeout, OPSER substitution
or repeated KSYS was introduced. There is no root-cause/fix claim. This
documentation-only analysis leaves the89-test code baseline and all release
gates unchanged.

[ksys-qsrt10]: https://github.com/PDP-10/stacken/blob/6e18f5ebefd9acb0d718ef31a08f33a60fc9fca2/files/stacken-tape-backup/dskb:10_7/galaxy/quasar/qsrt10.mac
[ksys-qsradm]: https://github.com/PDP-10/stacken/blob/6e18f5ebefd9acb0d718ef31a08f33a60fc9fca2/files/stacken-tape-backup/dskb:10_7/galaxy/quasar/qsradm.mac
[ksys-quasar]: https://github.com/PDP-10/stacken/blob/6e18f5ebefd9acb0d718ef31a08f33a60fc9fca2/files/stacken-tape-backup/dskb:10_7/galaxy/quasar/quasar.mac
[ksys-batcon]: https://github.com/PDP-10/stacken/blob/6e18f5ebefd9acb0d718ef31a08f33a60fc9fca2/files/stacken-tape-backup/dskb:10_7/galaxy/batcon/batcon.mac
[ksys-batmac]: https://github.com/PDP-10/stacken/blob/6e18f5ebefd9acb0d718ef31a08f33a60fc9fca2/files/stacken-tape-backup/dskb:10_7/galaxy/batcon/batmac.mac

### Offline executable layout qualification

The follow-up [image-layout analysis](ksys-image-layout.md) found embedded
symbols in both distribution executables and two complete byte-identical copies
of each in the checksum-verified runtime-v1 disk. Seven red/green decoder tests
pass; an independent, nonexecuting SIMH LOAD/EXAMINE comparison matched all68,608
mapped words. Candidate PSB/BATCON field addresses and selected instruction
boundaries are now byte-backed. Monitor job/UPT mapping and resident-image
identity remain unqualified, so no failure capture or new CI run was enabled.
