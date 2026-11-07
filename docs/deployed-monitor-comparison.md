# Deployed monitor-scope comparison

Base: merged main `50092ed`. This branch isolates the existing local monitor
correction from all batch-warmup, gateway and source-transfer experiments.

`server.runtime --monitor-scope` creates a fresh `MonitorBootstrap` on every boot,
arms it from the witnessed BOOT> boundary, sends the original /tm02 once, and
requires verified installation before OPR exit and native/external admission.
The existing fingerprint/allocator/state-restoration implementation is reused
without modification. Default runtime behavior remains unpatched. UTC boot time,
private bridge ports and admission calls remain in the original boot method.
Failed/unverified bootstrap stops in-process retries; a witnessed bootstrap SCP
prompt remains owned during cleanup. No replacement monitor is written to disk.

Tests cover external bridge construction with actual reserved port arguments,
UTC boot fields, repeated fresh bootstrap construction, default-off behavior,
installation/arming failure without admission/retry, and simulator-prompt
ownership during failed bootstrap cleanup. Local native correction evidence and
limits remain in `local-monitor-fix.md`.

## Single comparison

Manual deployment workflow input `monitor_comparison=true` runs two native-x86
AlmaLinux arms from the same source/media/simulator pins. Each is one CPU/2GiB
during runtime, using NOIDLE/5M/DZ SPEED8 and host UTC. The simulator is built
before applying the CPU quota. There is no installer, database, gameplay persona
creation, batch warmup or gateway alteration in this comparison.

Each arm allows at most three independently extracted starter copies. Each boot
uses the production native admission probe and four further name-question /
Ctrl-C / KJOB cycles with ten-second running gaps, followed by normal shutdown.
Stop at first boot, admission or shutdown failure; no failed disk or uncertain
input is retried. This is focused lifecycle evidence, not full deployment or
external persistence acceptance. Timing/host scheduling need not match exactly
between independent runners; do not claim a controlled performance benchmark.

A bounded4096-entry instruction-history ring is enabled in the generated initial
configuration before boot, never by editing a running ini. Boot/admission failure
captures the last256 records before cleanup. Raw history/registers and small halt
word reads stay private on the ephemeral runner. Only PC frequencies, the last64
PCs, lifecycle results and a narrowly validated saved-PC half at5004 for HALT5005
are uploaded. No user memory, stack or register values enter public artifacts.
An already halted guest receives simulator exit, never OS cleanup or a resumed
halt. Running failure captures resume before the ordinary shutdown attempt.

The earlier HALT5005 report alone did not establish the stale-table defect. A
positive candidate result is not automatically a causal repair claim. Interpret
the paired evidence, record missing proof, and stop rather than expanding the
experiment or launching a full matrix without a decision.

## Single native-x86 result

Run [42312843572](https://github.com/irongulp/mud1/actions/runs/42312843572)
at `7abd6d3` completed both arms; no rerun was launched.

| Arm | Result |
| --- | --- |
| Baseline | Boot1/four repeated admissions/clean shutdown passed. Boot2 failed within boot/admission with TimeoutError; captured PC000000, no HALT5005 in the last256 history entries, cleanup unclean. Stopped before boot3. |
| Scope candidate | All three independent fresh boots installed/verified the correction, completed four repeated admissions per boot, and completed native clean shutdown. |

Both arms used the same pinned source/timer patch, original archive, UTC clock
policy, runtime quota and history configuration, without batch warmup. They built
SIMH independently; recorded binary hashes differ (baseline427d5bf7..., candidate
b6692757...). This is a source/profile-matched comparison, not a byte-identical
binary or synchronized-clock experiment. Raw private histories/registers were
excluded from uploaded artifacts; sanitized reports are retained separately as
monitor-comparison-baseline and monitor-comparison-candidate.

The baseline PC0 admission failure is consistent with the earlier demonstrated
stale-table failure class. The short captured history contains interrupt/monitor
paths and does not by itself re-establish the complete free/reallocate/restore
causal chain. It did not reproduce HALT5005. Combined with the prior local causal
work, the successful deployed-controller candidate supports taking this existing
correction forward for broader validation. It is not proof of universal boot or
BATCON shutdown reliability, and no full installation, MariaDB, HTTPS, backup or
upgrade validation was performed by this fixture.

Host regression suite:50 focused tests passed. Workflow lint passed excluding
pre-existing SC2034 loop-variable warnings. Main remains unchanged; the opt-in
branch is not merged or enabled by production setup. Recommended next gate is
review of the opt-in integration, then full deployment validation with explicit
selection on every relevant boot, including private cutover runtime boots. Do
not silently enable only the systemd process and claim cutover coverage.

## Explicit installer integration under validation

`setup.sh --monitor-scope` selects the correction independently of persona storage.
Fresh installation still defaults to native storage and no monitor correction.
`deployment.json` retains the boolean selection; omission on a rerun preserves it.
Setup writes `MUD86_MONITOR_SCOPE=1` in the existing systemd runtime environment
and explicitly passes `--monitor-scope` to private external cutover. Native and
MariaDB service boots use the same guarded bootstrap. Existing disks and the
historical SYSTEM.EXE remain intact; the correction is reinstalled into RAM on
each boot. There is no automatic unpatched fallback.

Bootstrap failure exits with status78 and the runtime unit's
`RestartPreventExitStatus=78` prevents automatic systemd restart. Cleanup failure
cannot turn an incompatible/uncertain bootstrap into a retryable error. Ordinary
runtime failures retain the existing policy. Inspect private boot records before
an explicit retry; do not remove the guard or rewrite a failure as success.

Manual workflow input `scoped_acceptance=true` runs the full deployment matrix.
Native and external first setup explicitly select the correction; their reruns
omit the flag. Acceptance verifies persisted metadata/runtime environment and
one successful installed proof per recorded boot, including private cutover
boots. It rejects retained failed bootstrap records. Only sanitized proof counts
enter reports; stack/register and snapshot credentials are not uploaded.

62 focused deployment/selection/bootstrap/control tests pass. Full native-x86
installation acceptance remains pending for this installer integration.

First full run42355849773/71b0b51 completed native setup/rerun/backup/re-entry,
then failed the host evidence checker: its `*-verified.json` glob counted both
the profile-verified intermediate stage and final installed proof. A failing
regression now executes the actual remote-check script against both files;
matching the exact two-digit final-stage filename fixes the assertion and still
rejects a profile-only boot. The original run remains failed, not full acceptance.

Corrected full run [42356594697](https://github.com/irongulp/mud1/actions/runs/42356594697)
at `5f6df97` passed host/Chromium tests, native initial setup, saved login,
inspection and installer rerun. The backup's native shutdown then failed:
KSYS queued request9, BATCON stream32 started and opened
`DSKB:B10335.LOG[3,3]`, but no End/KSYS completion arrived within90seconds. A
TTY0 STOMPR quieting failure appeared during the wait. Final `shutdown.json`
retained `clean:false`, failure phase `ksys`, type `TIMEOUT`; backup did not
create an accepted archive or restart the disk. Simulator Goodbye occurred.

This is a KSYS stream execution/completion failure, not an observed BATCON
startup failure. It happened with scope selection enabled; the correction is
not a complete shutdown repair. No HTTP/HTTPS multiplayer, container reboot,
MariaDB cutover or fresh external acceptance ran after this failure. Private
cutover option plumbing is host-tested, not natively qualified by this run.
The full acceptance remains failed; no release or adoption follows automatically.

Next evidence should be the exact KSYS stream log and contemporaneous job state
before simulator termination, to identify the job/operation blocking logout.
The retained artifact has the stream filename but not its contents. STOMPR
correlation alone does not justify disabling it or claiming a cause. Do not
repeat the same installation prefix, extend the deadline or replay KSYS as a
substitute for that evidence.

Scoped CI now explicitly selects `MUD86_KSYS_CAPTURE=1` through a fixture-only
service drop-in. After a failed KSYS wait, the bounded20s evidence collector
requires a confirmed queued stream and exactly one native `DSKB:Booooo.LOG[3,3]`
filename. It interrupts only its CTY operator, witnesses the monitor, reads
SYSTAT and that exact file once, and retains the original unclean result.
No KSYS replay, timeout extension, clean-marker promotion or guessed filename.
Raw output is private0600 under `ksys-failures/<id>/`; incomplete reads leave
transcript logging disabled. CI exports only filtered command verbs/error codes
and job/program/page/state summaries. This is failure diagnosis, not a new
shutdown mechanism or proof that the original log was captured retrospectively.

Capture-enabled run42358668600/b6487f2 passed native installation/rerun,
inspection, saved login, backup/restart and3 per-boot monitor proofs. Sleep
measurements6.001/5.978/5.973s passed. HTTP multiplayer passed. HTTPS progressed
past admission but failed the Backspace initial-echo assertion: native arrivals
and redraws produced `*  wx` instead of the fixture's exact `*wx`. This is not
the earlier initial-monitor timeout. Final cleanup KSYS was clean and the
KSYS-summary list was empty; no stream failure was captured. Keep this failed
full run as partial evidence, not release acceptance or a resolved shutdown
cause. No external stages ran, and no speculative UI relaxation was applied.

Next stream investigation should use a native install/backup lifecycle-only
fixture so a separate browser presentation assertion cannot block observation.
Retain the full browser matrix as a release gate; separating diagnosis does not
waive its failed assertion. No further unchanged full run was launched here.

The captured browser sequence is now a real Chromium regression. Native
`CR + CSI C + CSI C + CSI C + CSI K` after a standalone `*` leaves exactly two
padding cells before the input. The smoke assertion now permits that exact
offset only with the witnessed redraw in the current edit's raw output, while
still requiring exact text/cursor and no trailing visible content. Backspace,
completion and Enter emit the expected edit bytes. Arbitrary padding, wrong
commands and trailing junk remain rejected. Production browser rendering is
unchanged; the real-game WHO outcome check is still required by the smoke test.

Explicit `lifecycle_only=true` runs scoped native installation/rerun and at most
three distinct backup/saved-re-entry cycles, stopping on first failure with no
restart override or backup replay. It skips downstream native browser/HTTPS,
cutover and database checks only for diagnosis; default full acceptance retains
them. Native failed-backup output is saved before raising. Host tests exercise
the cycle bound, immediate stop and saved re-entry after each successful backup.

Lifecycle-only42364597755/8b70f1e passed all3 distinct backups/re-entries and5
verified monitor boots, final clean KSYS, no captured failures. The five sleep
observations6.034/5.983/5.987/5.987/5.978s passed. This is bounded positive
lifecycle evidence, not resolution of the earlier intermittent KSYS timeout.

Full scoped42365483957 at the same commit passed native setup/rerun/backup,
HTTP and HTTPS Chromium multiplayer/editing, and container reboot/browser
re-entry. Native-to-MariaDB cutover compiled the external modules, imported the
native snapshot, completed its private guest KSYS and verified retained
external archwizard records. Setup then timed out in reset_permissions' read-only
DIRECTORY query for MUD.EXE. The external acceptance report remains incomplete;
external login/rerun/backup and fresh external installation were not accepted.
Final service cleanup KSYS was clean; no KSYS capture was produced. No command
replay or unchanged full rerun followed. The remaining observed boundary is the
maintenance query after cutover, not HTTPS or a reproduced shutdown failure.

The exact reset-permission query now reports structural failure evidence through
`ProtectionInspector`: confirmed echo, accumulated response-byte count, presence
of the MUD EXE listing, newline-dot/CR-dot endings, XON/XOFF/BEL and EOF flags.
The observer is enabled only for `directory DSKB:MUD.EXE[2011,2776]`, cleared
before cleanup, and never prints arbitrary response data. Other inspector
commands, snapshot/password handling and query deadlines remain unchanged.
Tests reproduce a partial response with CR-dot but no required LF-dot and check
that only structural facts escape. This is diagnosis, not a parser relaxation.

Explicit `fresh_external_only=true` selects the scoped fresh external acceptance
without repeating the native/browser prefix. It still performs real cutover,
login, rerun, backup and persistence checks; a focused pass is not full release
acceptance.43 relevant host tests and workflow lint passed before dispatch.
