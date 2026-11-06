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
