# Guarded startup for the local external-persona launcher

`python -m tools.serve_external` uses three startup guards before exposing its
browser gateway: a verified independent simulator cache, a per-boot monitor RAM
correction, and a completed native batch dependency probe. Its command-line
interface and persistent state directory remain the same.

## Independent simulator cache

The first launch requires Git, make and a C compiler. `tools.local_simulator`
archives SIMH revision `47b7ddabbe5b548cfc32f2fd45f7bed238ff7921` into a separate
private build tree and uses the already supported
[active-tick correction](simh-timer.md) from `tools.simh_timer`. It passes
`USEFUL_PACKAGES=` and `OPTIONAL_PACKAGES=` to prevent make installing packages.
The original `upstream/simh` source and executable are not patched.

`build/local-simh/manifest.json` records the revision, patch ID, corrected timer
source hash and executable hash. Subsequent starts verify both source and binary
hashes. An incomplete/changed cache aborts startup; it is retained for inspection.
Failed staging directories retain build logs. Build cancellation/deadline kills
and reaps the compiler process group. No simulator build is attempted as part of
a native guest boot retry.

The cache can be prepared independently of a guest/database boot:

```sh
.venv/bin/python -m tools.local_simulator
```

## Scoped monitor RAM correction

The captured KS10 7.04 monitor layout contains an unbalanced saved-context path:
SWAPO enters SVEUB at octal `506705`, but its success and failure scan-loop exits
can escape without restoring the saved UBR/SPT. Earlier private instruction
histories demonstrated saved tables being freed/reallocated and then restored,
ending in a page fault through a zeroed handler.

`server.monitor_scope` builds a bounded wrapper from the **installed live words**.
It gives low/high output and failure exits a balanced scope, restoring the incoming
mapping before the previous PI7 enable state. The host independently generates
the wrapper; no replacement historical monitor binary or memory snapshot is
bundled.

`server.monitor_bootstrap` arms a breakpoint from a witnessed BOOT>/SCP boundary,
then verifies instruction-range SHA-256 fingerprints, paging context and relevant
monitor geometry before allocation. The original native GETWDS reserves 64 words;
the installer verifies ownership against its allocation bitmap, installs a
63-word payload, and changes only the original three entry words at
`506703`–`506705`. Payload and entry are read back. All 128 accumulator-bank words,
interrupted control registers and null-stack scratch are restored and checked.

This correction is RAM-only and lost on shutdown. It runs again on every boot,
including the launcher's terminal-configuration reboot. Unsupported monitors and
failed/uncertain installations abort admission without an unpatched fallback or
automatic boot retry. This is pinned-layout support, not a generic patch for
every TOPS-10 7.04 build.

## Native batch readiness and console ownership

Before bridge/HTTP admission, one generated control file runs native DAYTIME.
The filename must be confirmed absent before COPY; the log binds a full current
boot ID and the acknowledged queue request. `/OUTPUT:NOLOG` avoids printer work.
A queued acknowledgement, echoed command or login date is insufficient: the
controller must be initialized and the log must show the actual monitor DAYTIME
result followed by batch logout. Both witnessed `MONITR .DAYTIME` and
`BATCH DAYTIME` input labels are supported. Probe work shares one bounded deadline;
an uncertain submission is never replayed or retried.

`server.local_guest` reuses the verified console driver in `tools.guest_control`.
Commands require witnessed prompts and exact byte echoes before Enter. COPY
verifies its header and each line before continuing; a bad header receives
neither Enter nor payload/EOF. Only a confirmed monitor can receive OS commands.

Shutdown requires a semantic SHOW QUEUES response (empty **or nonempty** listing)
and the OPR prompt before one KSYS submission. A prompt alone cannot authorize it.
Clean shutdown requires native KSYS completion, simulator Goodbye and actual
process exit. Exit alone is not a clean native shutdown marker.

## Private evidence and persistent state

Each boot has a 0700 directory at
`<state>/machine/monitor-boots/<boot-id>/` containing 0600 stage summaries,
`batch-probe.json` and `shutdown.json`. Readiness metadata adds `monitor_scope`,
`monitor_boot` and `batch_readiness`; a stopped/dead guest cannot reuse an old
verified state. Summaries include the selected simulator path/hash.

Kernel stack/accumulator queries and restore operations disable transcript logging.
The 0600 scratch restoration script is removed after use. Failed memory queries
leave logging disabled through teardown so queued private output cannot leak.
Do not publish private memory captures or database configuration as operator reports.

Existing game disks and MariaDB records are retained. The original game source,
SYS:SYSTEM.EXE and SYS:BATCON are not replaced. Existing running launchers keep
their loaded code until a controlled restart. Native/default/systemd launchers
are outside this local integration.

## Validation and limits

Earlier development recorded 94 focused tests and the `lm18`/`lm19` disposable
acceptances: internal reboot, SAVE/PASSWORD/75-second idle lookup, full restart/
re-entry, stable two-player WHO, PURGE and verified clean boots. The original
controller control `lm16` also passed an 11-minute idle gap. Those observations
precede this PR's current-main/dependency validation and are historical evidence.

A separate native FRDCRW core-allocation loop was captured during failed BATCON
startup. The timer correction alone did not repair it universally. Dependency
preflight is not a promise that a demand controller stays resident indefinitely
or that every later memory-pressure/error path is repaired. Experimental
replacement-controller and OPSER fallback changes are not part of this profile.

Clean-branch verification on current-main base `af7cd82` used Python 3.12.15,
the current development dependencies and matching Chromium 153.0.8010.12:

- 144 focused local/gateway/bootstrap/console/cache/timer/controller tests passed.
- Fresh disposable `lpr03` passed three verified clean application boots and a
  clean source-fixture shutdown, including the internal reboot, SAVE/PASSWORD,
  75-second idle lookup, full launcher/database/guest restart, password re-entry,
  two ordinary players with shared WHO/stable socket epochs, and PURGE.
- Per-boot batch and monitor proofs matched HTTP readiness; native logs had no
  warnings/errors/startup retries. All owned test processes exited.
- `git diff --check`, source-tree preservation and dependency consistency checks
  passed. The original running local game was not restarted or modified.

`lpr01`/`lpr02` are retained failed pre-fix browser controls: startup/native
shutdown succeeded, but PASSWORD confirmation was queued because its unstarred
native question was not credited by current main. A failing protocol regression
reproduced it. The gateway now recognizes only that exact full-line question,
grants one occurrence's credit, rejects quoted lookalikes and does not recredit
later CR fragments. The browser driver also waits for display pacing and captures
failure screenshots. No historical binaries or private evidence/configuration
are included in the PR.

Fresh acceptance can be run on a stopped supplied image with new short output
paths (macOS private database socket paths must be shorter than 100 bytes):

```sh
.venv/bin/python -m tests.integration_local_monitor \
  --output /tmp/mud86-guard-test --terminal-fixture /tmp/mud86-guard-source \
  --assets-root "$PWD" \
  --prepared-runtime runtime/external-always-open-green/compiled \
  --idle-seconds 75
```

The fixture enables STOMP only on a disposable source copy. The normal launcher
must remove it, shut down cleanly, reverify its internal reboot, then pass the
browser/store/restart/multiplayer checks. All boot records must be verified and
clean; retained private restore scripts or memory transcript markers fail the run.
The test accepts an explicit `PLAYWRIGHT_BROWSERS_PATH` for a matching private
browser cache. Source media, live state and user-managed listeners are not selected
as test output. Use private high loopback ports; 8080–8082 are reserved.
