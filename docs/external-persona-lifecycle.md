# External persona lifetimes and compatible-world chaining

## Verified milestone

The opt-in `--external-lifecycle` variant extends in-game administration with
shared creation provenance, stale-lifetime checks and cross-job first-SAVE
recovery. Repeated `--chain-target` options additionally enable handover between
explicitly approved compatible external images using the same persona namespace.

Final evidence is `runtime/external-lifecycle-green/`, with prepared sources,
provenance and `local.diff` in `build/external-lifecycle-green/`:

- Fifteen lifecycle scenarios and sixteen authentication comparisons passed.
- 102 bridge HELLO challenges were observed without reuse, including image
  changes and guest replacement.
- 142 relevant host preparation, storage, protocol and gateway tests passed.
- Original source hashes matched and FILCOM confirmed unchanged retained native
  persona bytes during the main external run.
- The main build/test phase completed clean KSYS shutdowns. The later guest-loss
  phase intentionally killed one disposable emulator with SIGKILL.

This is targeted acceptance, not certification of every native exceptional path.
Rare lock/memory-exhaustion recovery, arbitrary instruction-boundary interruption,
different-store world transfers and production deployment remain outside the
verified matrix below. The browser bootstrap for external images is still an
operator/controller integration concern; this milestone does not switch a live
server or replace its disks.

## Cross-job findings and implementation

`runtime/native-crossjob-first/` records unmodified-engine controls. A permitted
archwizard ATTACH to another job's live ordinary persona uses the same in-core
profile. It does not create a separate copy or increment GAMES. The visitor can
perform the first SAVE of an unsaved persona, using the visitor's session password.
The original owner can subsequently persist its own session password again.
The original password warning was observed. These effects are retained, not
replaced with a new exclusive-owner rule.

The previous creation adapter tracked names in a job-local list. That was too
narrow for this live-profile path. `WRLIFE.BCL` and `XLSTATE.MAC` now supply:

- A shared lifetime counter and a seven-word entry for each of the 36 player slots.
- A lifetime ID, profile address, new/saved/pending-creation state, creator
  operation ID, creator job number and operation-start clock.
- Private selected-lifetime and checkpoint references for each job.

The table is linked into the shared high segment **outside original DBADAT**.
It is runtime coordination state, not a new persistent persona-record field or a
simulation of native file slots. The existing eleven-word storage contract and
MariaDB transaction schema are unchanged by this milestone.

New profile allocation initializes a fresh lifetime. Live ATTACH selects the
existing lifetime; allocation for saved/missing-target ATTACH initializes its own.
Normal profile retirement, rejected admission and EXORCISE invalidate the slot
before it becomes reusable. The old job's cached lifetime cannot then authorize
serialization of a replacement profile. The normal `check.gone()` path and return
from DET/CONT also check lifetime validity.

Creation state is shared, but `ps.word`, `savedp`, `savescr` and ordinary pending
SAVE bookkeeping remain job-local. Recovering another job's first CREATE is not
credited as this job's own SAVE. After reconciliation, the caller makes its own
checkpoint through the normal serializer and score guard.

A normal in-flight first SAVE is given twelve guest-clock seconds to complete.
After that, or immediately when reconciling this job's own interrupted attempt,
the helper resolves the exact recorded operation. COMMITTED marks the shared
identity saved; ABORTED/CONFLICT permits a fresh first-create attempt. An unavailable
outcome remains unresolved. One preparation attempt has a fifteen-second guest
clock bound. These are additional cross-job coordination bounds, distinct from
the existing per-transport and per-worker deadlines.

Metadata uses short native `persona.door` critical sections. No bridge/database
round trip is performed while holding that door. Native lock failure itself is
not newly proven safe at every interruption point; see remaining limits.

The actual game command for detaching is **`DET`**, not `DETACH`
(`source/TXTBTM.GET:102`). The stopped-creator tests use original DET followed by
controller-owned monitor KJOB. The live profile's original owning job remains
present and can reconcile a committed or uncommitted first CREATE.

## Chaining contract

Example source preparation:

```sh
.venv/bin/python -m tools.prepare \
  --external-lifecycle \
  --chain-target mud \
  --chain-target valley \
  --output build/mud-lifecycle-example
```

Targets must be explicit lowercase TOPS-10 image names of at most six characters.
They are trusted operator configuration, not player-supplied executable paths.
Both images must implement this handover format and use the same configured
persona backend/namespace. An allowlisted filename is not a cryptographic image
attestation; deployment must install/verify the compatible images and protections.
Without target options, the variant keeps outbound chaining gated.

Original movement, source-world teardown and eligible checkpoint policy remain
BCPL. A pending SAVE/PURGE must resolve before admission to the leave path. Once
teardown has begun, a failed/unconfirmed required checkpoint prevents launching
the destination and closes at the monitor; it cannot undo dropped objects or
restore the departed live profile. An intentional native persistence skip is
distinct from an unsuccessful checkpoint. A missing chained persona at the
destination is an error, not permission to create a replacement silently.

Compatible external images use a thirteen-word, job-local, in-core TMPCOR `XCH`
packet. It is read/deleted atomically on entry and contains:

1. Format marker and destination image identity.
2. Packed persona name, session password word and starting score.
3. Session start time, destination room and logging flag.
4. Existing private bridge seed and its consumed challenge counter.
5. Handover timestamp.

The receiver checks length, marker, target, name length, counter range and the
native ten-second freshness window. The challenge counter continues across image
changes rather than restarting under the same seed. The destination then uses the
normal persona lookup/authentication/profile conversion path. Chained entry keeps
the original non-incrementing GAMES behavior. Normal admission still uses ROSEED's
two-word RSE bootstrap.

This fixed-word external format is **not the legacy ASCII temporary-file format**.
No seed or password word is put in an operator report. It supports the implemented
same-job, compatible-image handover; it is not a network transfer to another
emulator or a different database namespace.

### Native compatibility investigation

The supplied native chaining path did not pass the attempted two-world control.
Short-name entry reported “Something suspicious here”; a nine-character attempt
also failed. Independent `CHAINCK.BCL` diagnostics validated the outgoing header,
name count, flag and a fresh timestamp without printing password data. A separate
VEC-assignment probe did **not** confirm the suspected vector/scalar aliasing
explanation. Do not claim an unmodified-native chaining round-trip pass or a
conclusive diagnosis of that rejection.

The external test also exposed a concrete RUN-entry compatibility issue:
MBOOTS's older shim recognized lookup-block address octal 75, whereas this RUN
path supplied 77. Examination showed device `DSKB` at 77 and maintainer PPN
`[2011,2776]` at 101. Without normalization, the destination tried `[0,77]`.
The generated chaining variant adds those 77/101 cases while retaining the old
75/77 cases. This change is scoped to the opted-in chaining build.

New destination data files initially had `<057>` protections and were unreadable
to MUDGUEST. The test installer sets `<055>` on the six generated world-data
extensions and the executable, without changing native persona-file protection.

## Two-world test fixture

`tests/chaining_fixture.py` uses original DBASE to compile two copies of the
supplied MUD world. The second is named Valley **for this compatibility fixture**;
it is not a recovered historical Valley world. Both declare persona store `mud`.
The original chain portal is adjusted to the other image's existing `start` room.

The small source edits use TECO's page-aware search and copy-rest exit, with a
whole before/after TYPE comparison. Some original rows exceed the monitor's
255-column maximum, so the check validates all baseline non-whitespace source
and then the complete rendered before/after text with only the intended short
lines substituted. Full-file replacement through TECO is not assumed safe.
DBASE selects the second input using `RUN DBASE -valley`. Source hashes for both
fixture variants are computed by the fixture helper; `source/` is untouched.

Tape transfer attempts are retained as failed research: MTA1 was unavailable in
this monitor configuration, and the running tape-swap/continue attempt stalled.
The final procedure does not edit a running SIMH configuration or swap its boot
tape. Normal boots continue through the original tape and `/tm02`.

## Acceptance matrix

| Case | Verified result |
|---|---|
| Visitor first SAVE of another job's unsaved live persona | Native password and game-count effects retained; original owner subsequently SAVEs and re-enters |
| Visitor SAVE of an already saved live persona | Native visitor/owner password effects retained |
| Creator commits but loses reply, then DET/KJOB | Remaining job resolves the recorded CREATE and makes its own checkpoint |
| Creator never commits, then DET/KJOB | Remaining job fences the old request; a delayed old create remains ABORTED |
| EXORCISE, slot reuse, stale CONT and stale original job | EXORCISE invents no persistence; old jobs cannot mutate the old or replacement persona |
| Ordinary external round trip | Source first-game checkpoint created, destination reached, return completed, GAMES not incremented by chaining |
| Nine-character name round trip | Complete name and persona state retained |
| Lost source-checkpoint reply and DB restart | Outcome resolved before successful round trip |
| Database unavailable during required source checkpoint | Destination not launched; no phantom persona created |
| Gateway cleanup in ordinary gameplay | QUIT/KJOB completed on an external session |
| Gateway cleanup with lost checkpoint reply | Cleanup reached monitor and removed the job |
| Gateway cleanup during PASSWORD | Original interrupted-input path completed cleanup |
| Gateway cleanup during a PURGE menu | Target record unchanged; job removed |
| Gateway cleanup during creation's sex question | Job removed without creating a persona |
| Guest process killed after SAVE and later unsaved scoring | Fresh guest restored the confirmed score 0 checkpoint, not the later unsaved score 11 |

The native cleanup tests call the actual `server.gateway.logout_guest()` against
real guest connections through a small async stream adapter. The host gateway
suite covers browser disconnect/restart/shutdown orchestration. This combination
does not claim that a production external browser bootstrap or VPS update has
been deployed.

The guest-loss test copies only a stopped, clean compiled disk. It SIGKILLs the
test emulator without QUIT, then boots a fresh copy against the existing MariaDB
store. It does not promise restoration of unsaved gameplay, room location,
inventory or an entire crashed world. Newly configured private listener ports
avoid the old sockets' TIME_WAIT after SIGKILL; fixed-port production restart
behavior remains part of deployment work.

## Build, evidence and limits

```sh
.venv/bin/python -m tests.integration_native_crossjob
.venv/bin/python -m tests.integration_external_lifecycle
```

The lifecycle build must compile MUD3 as well as MUDLIB/MUD7/MUD5, assemble
`XLSTATE.MAC`, and link `XLSTATE.REL` with the game before DBADAT. Chaining also
requires the generated MBOOTS. Game code plus shared state ended at octal
`510047`; DBADAT remains at `520000`, and original DBASE reports 25,247 words.
Keep images, world data and bridge configuration consistent.

The native cross-job control is `runtime/native-crossjob-first/`. Final external
acceptance is `runtime/external-lifecycle-green/`; earlier incomplete builds,
parser investigations, diagnostic runs, port-reuse failures and native monitor
stalls remain under the corresponding `native-chain-*`, `external-lifecycle-*`
and private `lifecycle-*-debug-*` directories. Do not relabel those as passes.

Still not exhaustively validated: lock/JAR/getmblock failure callbacks, every
combat/interruption boundary, every ATTACH permission/state combination, different
persona namespaces, arbitrary target image replacement, and production full-stack
restart/migration. POWER and external-aware SSH inspectors remain separate work.
The completely native build, including `--always-open` alone, retains the original
implementation and does not depend on this adapter or MariaDB.
