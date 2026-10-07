# External persistence on eligible exits

## Verified scope

The generated `--external-exit-existing` variant extends existing-persona SAVE
with **eligible alive-persona updates from the original `writeprofile()` path**.
Normal QUIT now persists the original game's current profile to MariaDB without
requiring an explicit SAVE first.

The final disposable run is `runtime/external-exit-verified/`, with generated
code and provenance in `build/external-exit-verified/`. It passed thirteen named
exit scenarios, sixteen authentication comparisons, a database restart check
and source/native-persona byte preservation checks.

The native, read-only and explicit-SAVE-only modes remain available and retain
their previous behavior. Creation, deletion/death persistence, PASSWORD, PURGE,
outbound chaining and public/browser deployment remain outside this milestone.

The later opt-in [death/deletion milestone](external-death-existing.md) adds
eligible nonpositive-stamina deletion in a separate `--external-death-existing`
variant; this exit-only variant retains its deletion gate.

## Native policy retained

The generated `writeprofile()` retains the original promotion/eligibility code
from `source/MUDLIB.BCL:1209–1266`. Host tests compare the promotion block and
predicate with the original text. The persistence condition remains:

```text
not ATTED
and name is neither "glai" nor "gali"
and (games > 1 or savedp != 0
     or (stamina > 0 and (chaining != 0 or score != 0)))
```

This means that an existing zero-score persona can still qualify because its
game count increased at login. Conversely, a saved ATTACH target with one game,
zero score and no earlier SAVE in the current session can legitimately skip
persistence. An earlier successful SAVE changes that decision through `savedp`.

For an eligible, living profile, the adapter uses the existing W1 save path:
fresh save-time snapshot, original BCPL `SCRE >= savescr` check, unchanged
`dumpersona()`, atomic compare/update and durable outcome resolution. No scoring,
promotion or password rules move into SQL.

The original experience-threshold promotion runs before persistence. A dedicated
external fixture started at 102,399 points, performed original gameplay and
persisted the resulting ISWIZ eligibility bit on exit. This is runtime coverage
of the unchanged promotion block, not a separate native-file byte comparison
for that special fixture.

An eligible profile with nonpositive stamina does **not** overwrite its stored
record with a dead profile and does not delete it. It reports that external
deletion is unavailable. Native deletion equivalence remains a separate step;
combat/death acceptance has not been claimed here.

## Teardown-safe failure handling

`quit()` has already removed live player references, dropped possessions and
processed exit events before it calls `writeprofile()`. Therefore this path must
not use the interactive SAVE recovery helper, which jumps back to the command
loop through `error()`.

`tools/fixtures/WREXIT.BCL` supplies return-only helpers:

1. Resolve any pending explicit SAVE before considering another write.
2. If it committed, update `savedp` and `savescr` using the serialized checkpoint
   score, then evaluate normal exit eligibility.
3. If it was aborted/conflicted, clear pending state without inventing a
   successful SAVE, then evaluate eligibility.
4. If it remains unknown, print its operation ID and return without another write.
5. For a new eligible exit save, report a known failure or UNKNOWN honestly and
   return to the rest of the original teardown.

These helpers contain no `error()`, `quit()` or game-loop jump. The wrapper also
restores `output` to the controlling TTY before the storage phase, and new exit
diagnostics use explicit TTY output, rather than a stream that QUIT may have closed.

If a new exit commit succeeds but its acknowledgement is lost, W1 resolves the
same durable operation rather than submitting a second update. If the database
is unavailable during resolution, the session still closes and reports UNKNOWN;
it does not announce failure or success as a known fact. The printed operation
ID can later be reconciled through the existing fencing RESOLVE interface.

This is intentionally bounded failure behavior. It does not reproduce the
native file-open error branch's potentially indefinite retry when points were
lost. It also does not promise that a checkpoint was saved during an outage.
See [external-save-existing.md](external-save-existing.md) for the transaction,
immutable-intent and resolution contract, including why RESOLVE is not a passive
status query.

## Acceptance cases

The test first creates private native fixtures and collects original-file QUIT
controls. It then builds the external variant, regenerates data with original
DBASE, renames `MUD..PM` out of reach and runs the corresponding external cases.

| Case | Verified result |
|---|---|
| Ordinary gameplay then QUIT, no SAVE | Score 11 persisted and restored on re-entry; all logical words except clock-dependent LSTM matched native QUIT |
| Existing zero-score persona, no SAVE | Native game-count/profile update occurred and matched the native control |
| Excluded name Gali | Native “Not updating persona” behavior; no backend write operation and no record change |
| Roy ATTACH Richard, no earlier SAVE | One-game zero-score target remained unchanged, matching native behavior |
| Roy SAVE, then ATTACH Richard and QUIT | Exit became eligible; native-equivalent fields, including the historical password/PN behavior |
| Database paused before exit storage | Unconfirmed checkpoint reported; record/revision unchanged; teardown finished |
| Exit commit succeeds, reply lost, database restarted | Commit resolved; one revision increment |
| New exit commit remains unresolvable | UNKNOWN printed; one operation only; later resolution found the committed outcome |
| Prior explicit SAVE still unknown at QUIT | UNKNOWN printed; no new write attempted during teardown |
| Prior explicit SAVE resolves aborted | No false `savedp` increment; otherwise-ineligible attached exit skipped; delayed old commit was fenced |
| Prior explicit SAVE resolves committed after more gameplay | Old checkpoint bookkeeping used its saved score; fresh exit checkpoint persisted subsequent score 11 |
| Stored signed score below `savescr` | Original score-guard message; no update; teardown finished |
| Experience-threshold crossing | Original promotion text and persisted ISWIZ eligibility |

Every recorded exit returned to the monitor within the test's 25-second bound.
Typical eligible exits took about 1.3 seconds. Lost-acknowledgement cases took
about 5.3 seconds; a pending operation with an already stopped database was
reported unknown in about 0.2 seconds. These are observed host timings under
NOIDLE / 5M / SPEED=*8, not real-time guarantees for a stopped emulator or host.

The final report records thirteen cases and 21 write-operation BEGIN attempts,
including authentication and fault fixtures. Native control comparisons cover
ordinary, idle and attached successful exits; the other cases have targeted
state/operation-count assertions. LSTM is produced by the original guest clock
and is compared for forward progress rather than byte equality across runs.
The final host check passed 86 preparation, bootstrap, store and protocol tests.

SQL fixtures are deliberately reset with fresh generations after the external
authentication matrix, because successful authentication exits now legitimately
update game counts. Later administrative fixture changes are explicit and
separate from game writes. No assertion claims that all SQL rows stayed unchanged;
successful persistence is the point of this milestone.

FILCOM `/B` confirmed that retained native persona bytes did not change during
external operation. Original host `source/` SHA-256 values also matched. A fresh
getter after database restart restored the automatic checkpoint's score.

## Build and reproduction

```sh
.venv/bin/python -m tools.prepare --external-exit-existing --output build/mud-exit-example
.venv/bin/python -m tests.integration_external_exit
```

The three external build switches are mutually exclusive:

- `--external-readonly`: lookups only.
- `--external-save-existing`: explicit SAVE only.
- `--external-exit-existing`: explicit SAVE plus eligible exit updates.

Omitting them keeps native storage. The new flag changes generated files only.
`tools.prepare_writes.enable_existing_exits()` restores the original writer's
policy prefix/predicate and replaces its native storage scope; W1 and the
database implementation are unchanged by this milestone.

The private build uses the existing ROBOOT/ROSEED TMPCOR provisioning path,
MUD's channel allocator, and original DBASE with DBADAT at octal `520000`.
Game code ended at `504712` in the verified build. Keep the executable and its
matching generated world files together; an old executable alone is not a rollback.

`--output runtime/<fresh-short-directory>` selects the evidence directory and
a matching generated directory under `build/`. The harness owns its database,
disk copy and ports, and stops its test services on exit. It resets only its
disposable world for isolated scoring/promotion fixtures.

The 0600 `private-fixtures.json` contains disposable credentials and native
control words. Do not publish it as an operator report. `report.json` contains
outcomes and exit output, not passwords or persona bodies. The first complete
run is retained at `runtime/external-exit-first/`; the verified run adds both
new-exit UNKNOWN and aborted-pending eligibility cases.

## Remaining lifecycle work

The changed writer is also reachable from the original engine's exceptional
recovery paths, but this acceptance specifically exercises normal QUIT and the
listed storage faults. Arbitrary disconnects, allocator/lock failures, combat
death, forced exits and shutdown-driven cleanup need their own native coverage.

Deletion on death, persona creation and the recycled-slot/header-buffer edge
case are next persistence boundaries. PASSWORD/PURGE, operation-history
administration, migration and browser/production bootstrap also remain gated
or unimplemented. Do not equate successful QUIT persistence with complete
replacement of the native persona subsystem.
