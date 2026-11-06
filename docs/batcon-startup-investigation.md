# Focused BATCON startup investigation

The release remains blocked by native KSYS waiting for demand BATCON startup.
See [release CI evidence](ci.md#failed-shutdown-evidence) for the original native
x86 failures and corrected installer/backup continuation gates.

## Hypothesis and reference

Earlier independent local research observed a runnable five-page BATCON startup
job while the monitor executed its core-allocation wait loop. The SIMH timer
correction alone did not fix that case. Reference `PDP-10/stacken` commit
`6e18f5ebefd9acb0d718ef31a08f33a60fc9fca2`,
`files/stacken-tape-backup/dskb:10_7/mon/segcon.mac` lines 1317–1416, describes
FRDCR/FRDCRW: try free/paging/dormant segments, then wait for paging I/O and
retry. Dormant/idle segments without a disk copy are skipped. This is a matching
reference sequence, not a verified full build/map for the installed KS10.

The focused probe tests whether the current native x86 shutdown failure reaches
that same loop. It does not assume a missing file, substitute BATCON, install the
local monitor scope correction or use the unverified OPSER fallback.

## Probe

`tests.integration_batcon_startup` copies only the checksum-pinned runtime-v1
archive into a new private output directory. It uses `server.runtime.Runtime`
with its deployed UTC/tape/NOIDLE/5M/SPEED8 settings and an explicitly selected
timer-corrected simulator. Terminal initialization is disabled through the
existing staged/verified configuration tool; its configuration reboot requires
a confirmed clean shutdown. Two native MUDGUEST jobs reach the name prompt,
remain there for a bounded interval, then undergo explicit Ctrl-C/monitor/KJOB
cleanup. No persona or password is created. Native SYSTAT precedes one normal
KSYS request.

There are at most three independently extracted trials. Any failed setup or
shutdown stops the probe; a failed disk is never retried or promoted. This is a
lighter native memory workload, not external-storage or full installation
acceptance. A pass cannot prove the original external failure repaired.

The shared implementation is `tools.batcon_diagnostics`. The opt-in
`tools.batcon_service` entry point injects its diagnostic subclass into the normal
runtime argument parser; transport, backend, UTC clock and native commands stay
the same. The focused `fresh-external` CI scenario selects this entry point using
a fixture-created systemd ExecStart drop-in before setup. The default full
release workflow and production runtime entry point do not select it. Failure
captures go into unique private `/var/lib/mud86/batcon-failures/<id>/` directories;
the artifact collector reads only each generated `summary.json`.

On submitted KSYS failure, before simulator termination, the fixture:

1. Retains the native response privately.
2. Halts SIMH, reads selected registers, enables bounded instruction history,
   resumes for 0.2 host seconds, then halts and captures 512 history entries.
3. Reads the small pinned allocation-loop code range and reports page counters
   only if its MOVE/ADD instructions have the expected direct-reference shape.
4. Resumes and attempts one bounded operator SYSTAT after preserving the first
   sample. Diagnostic errors never replace the original failure or replay KSYS.

Raw terminal responses, registers, memory words and history live in `0700`
directories with `0600` private files. CI uploads only explicitly constructed
`summary-*.json`: lifecycle booleans, exception types, BATCON job/page/state
counts, PC frequencies, code hash and validated page counters. Raw private
evidence and guest disks are excluded from CI artifacts and release assets.
Interrupting for observation is diagnostic, not continuously running timing or
performance evidence.

Dispatch the focused native-x86 AlmaLinux container without installer/browser
compilation or the full release matrix:

```sh
gh workflow run deployment.yml --ref fix/release-shutdown-evidence -f scenario=batcon
```

The job builds the existing AlmaLinux image, creates its own Python environment
and separately checked timer-corrected SIMH cache, uses one CPU/2 GiB, and exposes
no host ports. Its private container is removed afterward. Summary evidence is
retained even on a failed run. The default `full` scenario remains the release
gate.

## Initial local control

Mac control `batcon-local-01` failed native admission before the BATCON probe:
cleanup rejected an unconfirmed `r opr` echo and SIMH stopped at PC0. Goodbye
and process exit were observed; shutdown was not clean. It remains failed
evidence, not a BATCON reproduction. A report-path construction error initially
masked its final summary; a run-level regression reproduces that host bug and
now verifies summary publication and no second boot after failure. Native x86
comparison is required rather than more identical Mac retries.

Native-x86 run 42254256397 at `bb1588e` completed the lightweight probe process,
but artifact upload failed because Docker's root-owned `0700` output was not
readable by the runner. It is not complete retained-summary acceptance. The
focused container now uses the invoking runner UID/GID, retaining private modes
while allowing that same owner to upload only the summary glob. The next
external scenario uses the shared observer to capture the original workload,
rather than treating a lighter successful workload as a native shutdown fix.

## First external-workload capture

Native-x86 external run 42256488786 at `805062d` reproduced the installer-rerun
KSYS failure and retained a usable sanitized summary. KSYS was queued and the
native BATCON startup failure was explicit. After the deadline, all 512 history
samples were idle-loop PCs (`000001/2/3/5`); none were in the previously observed
allocation wait range. The subsequent complete ten-job census showed BATCON job
1 at 39 pages, sleeping, rather than a five-page runnable startup stub.

This sample does not support declaring the earlier allocator loop the current
cause. It also does not show whether BATCON finished loading before or only after
QUASAR declared startup failure. The reference QSRT10 source's lines 4204–4285
distinguish an existing running PSB from firing/waiting/KSYS status, and send the
KSYS message through the BATCON HELLO/PS.KSY path. Its source version is reference
material, not proof of the installed controller's exact layout or timeout.

The observer now takes one earlier kernel sample if the original KSYS wait is
still pending after ten seconds. Sampling consumes the original timeout budget;
there is no new KSYS request or timeout extension. Native completion arriving
during the diagnostic halt is retained from the original guest frames and must
match the full timestamped completion line; it is not discarded or replayed.
Tests cover the shared deadline, in-sample completion and private-data boundary.
The early and post-failure summaries can distinguish a loading stall from an
already-initialized controller/QUASAR handshake problem. This remains observation,
not a runtime correction.

Run 42262115421 at `233332a` did not reproduce pending KSYS: installer rerun
failed at the maintenance DIRECTORY query used by `reset_permissions`, and its
cleanup KSYS completed normally. There were no early/pending samples. Keep this
separate failure rather than interpreting its empty capture list as a fix.

The explicit `batcon-external` workflow scenario now builds the external fixture
once, then performs up to three original browser login/QUIT and native stop/start
cycles. Every stop checks the clean marker before another boot; an unclean stop
ends the sequence without retry. The report is marked `diagnostic_only:true`.
This retains the external engine/database workload but removes installer-rerun
package/permission queries from the shutdown investigation. It is not installer
rerun, backup or full release acceptance.
