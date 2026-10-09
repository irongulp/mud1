# External existing-persona death deletion

## Verified milestone

`tools.prepare --external-death-existing` extends the eligible-exit variant with
deletion selected by the original BCPL `writeprofile()` policy. Original FOD,
combat bookkeeping, `checkout()` and `quit()` still run in the historical engine.
Only generated persistence code changes; `source/` remains byte-for-byte intact.

Evidence:

- `runtime/external-death-acceptance/`: twelve external death cases, four native
  controls, sixteen authentication comparisons, FILCOM preservation and source hashes.
- `build/external-death-acceptance/`: generated code, provenance and `local.diff`.
- `runtime/persona-deletes-acceptance/`: real MariaDB deletion transactions and races.
- `runtime/persona-writes-delete-regression/`: prior SAVE transaction acceptance.
- 96 host preparation, bootstrap, protocol, worker and storage tests passed.

The first six-case native run passed at `runtime/external-death-first/`. Two
subsequent extended-control attempts failed in test setup, before building the
external image: the test initially addressed the wrong games field, then used
the archwizard-specific ATTACH helper for an ordinary target. Those runs are
retained under `external-death-verified` and `external-death-final`; the successful
extended evidence is the `external-death-acceptance` directory.

## Native decision and failure behavior

The original promotion prefix and eligibility predicate are retained:

```text
not ATTED
and name is neither glai nor gali
and (games > 1 or savedp != 0
     or (stamina > 0 and (chaining != 0 or score != 0)))
```

Only an eligible profile with `STAMINA <= 0` reaches deletion. Eligible living
profiles use the existing SAVE adapter. Death does not serialize a negative
stamina profile and does not apply the SAVE score guard. Native `deleterec()`
has no such score guard (`source/MUDLIB.BCL:1308–1335`).

Death narration alone is insufficient: some A.DEATH/F.DEAD paths call QUIT without
setting nonpositive stamina. Acceptance uses original wizard FOD against ordinary
players: `K.FOD` sets stamina to -1 and invokes `checkout()`
(`source/MUD8.BCL:604–614`, `source/MUD3.BCL:301–343`). This verifies that real death
path, not every monster, room, revival or disconnect path.

As in the exit milestone, pending SAVE resolution precedes eligibility. A confirmed
SAVE increments `savedp` using its frozen checkpoint bookkeeping; an aborted SAVE
does not. An unresolved SAVE prevents a new deletion. The return-only `WRDEAD.BCL`
helper never calls `error()` or `quit()`, never returns to the command loop and
does not retry with a new operation after a generation conflict.

Lost mutation replies are resolved with the same operation ID. Unresolvable
outcomes print UNKNOWN and the ID, then complete teardown. A known unconfirmed
deletion reports that the stored persona may remain. An outage can therefore
leave a saved persona available for later login. There is no deferred-death queue:
resolving an old pending SAVE does not subsequently create a delete operation.
This bounded failure policy does not reproduce native indefinite file-I/O retries.

## Protocol and atomicity

Deletion is opt-in at three boundaries: the generated build switch, the bridge's
`allow_delete=True`, and explicit SQL DELETE permission. Existing bridge callers
default to deletion disabled.

After the existing H1 handshake:

1. `W1 DSTART <epoch> <operation>` selects immutable DELETE intent.
2. `W1 KEY <epoch> <name-word-0> <name-word-1>` begins a snapshot operation.
3. The existing credited R1 snapshot is validated in BCPL, including name,
   ordering and checksum. No mutation occurs during snapshot transfer.
4. `W1 DELETE <epoch>` explicitly confirms deletion, without PUT/upload frames.
5. `W1 RESULT` reports the durable outcome. Existing RESOLVE fences ambiguous work.

All numbers retain the existing octal widths and single-CR framing. Wrong epochs,
early confirmation, upload/commit frames in delete state and old-owner frames are
rejected. Deadline expiry after a store call produces UNKNOWN even if that call
returned COMMITTED. Bounded subprocess workers carry no bridge socket.

The journal binds namespace, operation ID, name and an explicit `kind` (UPDATE or
DELETE). Reusing an ID for a different kind or name returns REUSED. A nameless
RESOLVE tombstone fences either kind. Snapshot generation is captured at DSTART's
KEY transaction, not at login; generation fencing is an operation-level guarantee,
not a new lifetime lease for the game session.

DELETE locks its journal identity and persona row. If the generation matches,
the row removal and COMMITTED outcome are one transaction. Concurrent saves to
that generation do not defeat death deletion; revision/score changes are not
delete conflicts. A different generation yields durable CONFLICT. Missing rows
yield durable NOT_FOUND, matching native no-op deletion. Invalid stored records
remain INVALID_RECORD rather than being treated as missing.

Terminal replay consults the journal and never mutates the persona again, even
after recreation or database restart. RESOLVE aborts/fences OPEN or absent
operations; it is a write, not a passive status query. A racing SAVE either
commits before deletion or sees CONFLICT after it; it cannot create a row.

The fixture schema now includes `persona_operations.kind DEFAULT 'UPDATE'`.
This is a fresh private-test schema, not an installer migration for an existing
database. Reusing a previous experimental database requires an explicit quiescent
schema migration; this milestone does not supply a deployment/migration command.
Recreation must assign a fresh nonzero generation. Gameplay creation remains gated.

## Native acceptance

| Case | Result |
|---|---|
| Ordinary Mortal FOD | Native and external saved persona removed; external re-entry reports not found |
| Gali FOD | Original exclusion retained; no delete operation or stored-record change |
| Lost DELETE reply plus database restart | Same operation resolved COMMITTED; one deletion attempt |
| Committed DELETE with database still unavailable | UNKNOWN reported; later resolution confirms COMMITTED |
| Database paused before death lookup | Unconfirmed deletion reported; stored record unchanged |
| Prior SAVE remains UNKNOWN | No delete issued; teardown reports pending operation |
| Record removed administratively after login | Missing deletion is a successful no-op with durable NOT_FOUND |
| Generation replaced between snapshot and DELETE | CONFLICT, replacement retained, no fresh-operation retry |
| Unsaved one-game ordinary ATTACH | Native and external death skip persistence |
| Prior Roy SAVE, then one-game ordinary ATTACH | Native and external death delete the target |
| Pending attached SAVE resolves ABORTED | No invented `savedp`; target remains; delayed SAVE is fenced |
| Pending attached SAVE resolves COMMITTED | `savedp` qualifies death; target deleted |

All deaths finished at the monitor within the 25-second test bound. Successful
ordinary deletion took about one host second; lost replies about 5.3 seconds.
The original `.PM` was renamed out of reach before external cases. FILCOM `/B`
confirmed unchanged retained native bytes afterward. Private fixture credentials
and exported password words are confined to a mode-0600 file in the private run
directory; they are not part of the public report.

The SQL acceptance additionally covers replay after recreation, generation
conflict, cross-kind rejection, same-generation SAVE followed by deletion,
concurrent duplicate DELETE, DELETE/RESOLVE races, DELETE/SAVE races, absent
operation fencing, wrong-name rejection, outage and restart. Host tests cover
protocol rejection, owner handover, deadlines and uncertain worker outcomes.

## Reproduction and remaining scope

```sh
.venv/bin/python -m tools.prepare --external-death-existing --output build/mud-death-example
.venv/bin/python -m tests.integration_persona_deletes
.venv/bin/python -m tests.integration_external_death
```

Use fresh output paths. The harness owns disposable disks, private ports and its
MariaDB process. It stops those services on exit. Native build code ended at
octal `505053`; DBADAT and original DBASE remain at `520000`, with 25,247 words of
regenerated world data. Keep executable/world files together.

All four external build switches are mutually exclusive. Native, read-only,
explicit-SAVE-only and alive-exit-only behavior remains selectable. Creation,
PASSWORD, PURGE, outbound chaining, browser bootstrap deployment, migration and
arbitrary disconnect/recovery remain follow-up work.

Follow-up: [logical persona creation](external-persona-creation.md) is now verified
in the separate `--external-creation` variant. This death-only variant retains its
creation gate; the native storage default remains available.
