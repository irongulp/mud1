# External persona creation

## Scope and compatibility decision

`--external-creation` adds first persistence for new personas to the existing
external SAVE/exit/death variant. The original BCPL code still chooses character
attributes, asks for sex/password, checks names, computes passwords and serializes
the profile. MariaDB performs explicit atomic **create-if-absent**.

Following the storage-boundary discussion, this targets **logical gameplay
compatibility, not reproduction of physical persona-file allocation artifacts**.
The independently buildable native path retains those original artifacts.
Three external-storage decisions are deliberate:

1. A new logical record starts with zeroed unused words, rather than inheriting
   three opaque words from a deleted physical slot. Existing records still retain
   their opaque words through updates.
2. A first creation has no existing saved score to guard. The adapter does not
   apply the accidental header-buffer score comparison from native allocation.
   Updates retain the original saved-score guard and serializer.
3. A saved identity disappearing during its active session is not silently
   recreated. Explicit creation is for a persona admitted as new in that job.
   Competing creation returns CONFLICT and cannot overwrite another password.

This is not a claim of byte-for-byte allocation equivalence or complete persona
administration/deployment. PASSWORD, PURGE/enumeration, migration and browser
bootstrap deployment remain pending.

Follow-up: [in-game PASSWORD and PURGE](external-persona-admin.md) now have native
acceptance in the separate `--external-admin` variant. This creation-only variant
retains its original administration gates.

## Native characterization before implementation

`tests.integration_native_creation` runs the unmodified game on a disposable disk.
Evidence is in `runtime/native-creation-guard/`; the earlier narrower probe is
`runtime/native-creation-first/`. Original source hashes matched.

The experiment verified:

- Selecting a new name, sex and password does not immediately allocate a persona
  record. First SAVE creates it. Zero-score first-game QUIT without SAVE does not.
- A fresh slot's three unused words were zero in the disposable baseline.
- Native PURGE/deletion retains the old score and three unused words in the slot.
  `PMEDGE.BCL`, a private test-only companion, marked these fields with a signed
  score of -2 and three recognizable full-width words before original PURGE.
  A different new persona reused the slot, SAVEd successfully and retained all
  three opaque words. Its first SAVE was not rejected by that retained -2 score.
- The suspected buffer-order effect is real. `addrec()` ends with block 1 loaded;
  `saverec()` checks SCRE through that header buffer before loading the new record
  (`source/MUDLIB.BCL:1295–1305,1336–1366`).
- A first-game persona saved at score 11, then purged while still playing, failed
  to recreate on QUIT when the corresponding header cell was zero. Original SAVE
  printed the score-change warning and left a linked, nameless slot.
- The same logical scenario succeeded after creating an unrelated persona whose
  hash populated that header cell. The observed guard was 304, a file offset,
  rather than a persona score. This used ordinary original PURGE/SAVE/QUIT and a
  valid hash-table entry, not a forged negative header.

That dependency is an implementation artifact in MUD's buffer/allocator code,
not a requirement of TOPS-10 or a useful relational-storage rule. The external
adapter therefore does not reconstruct hash buckets or a file free list.

`PMEDGE.BCL` writes only in its explicit marking mode and is used exclusively by
the disposable experiment. It is not an installer/production inspector. Its
report omits password words; full private record exports stay in memory.

## Guest behavior

The creation build permits a conclusive R1 NOT_FOUND response to reach original
`newpersona()` at login or missing-target ATTACH. UNAVAILABLE and INVALID_RECORD
remain failures; they never authorize creation. The original authentication and
existing-profile conversion code remains intact.

`WRCREATE.BCL` keeps a job-local, bounded set of names actually admitted through
`newpersona()`. Its capacity follows the original 36-player/profile slots. Each
`initialise()` clears it. First persistence uses CREATE only for a tracked name
with a first-game profile. Confirmed SAVE, including recovery of a previously
UNKNOWN SAVE, retires that creation authority; subsequent persistence is UPDATE.

The existing native SAVE command restrictions remain. In particular, a missing
ATTACH target is created in memory with ATTED set: explicit SAVE is rejected and
QUIT skips persistence. This differs from ATTACH to an existing saved profile,
whose saved STATES can clear ATTED, as described in the authentication audit.

The creation set is job-local, not shared live-player metadata. ATTACH to another
job's unsaved live profile does not automatically obtain CREATE authority. That
cross-job case and broader arbitrary ATTACH/disconnect sequences remain follow-up
coverage; do not describe this milestone as exhaustive lifecycle equivalence.

First persistence continues through the existing original policies:

- Explicit SAVE can create a zero-score new persona.
- Eligible alive QUIT can create a score-bearing new persona without prior SAVE.
- Unsaved zero-score first-game QUIT skips creation.
- A successfully saved first-game persona qualifies for native death deletion.
- New login after confirmed deletion may create a fresh generation.

The unchanged `dumpersona()` produces the eleven payload words. SQL does not
calculate attributes, passwords, score, game count, PN or native time. The existing
bounded UNKNOWN and teardown-safe exit behavior also applies to creation.

## Transaction and protocol

Creation requires both `allow_create=True` on the W1 bridge and an explicit SQL
INSERT grant. Both are absent from the previous fixture configurations by default.
The generated switch is separate and mutually exclusive with earlier variants.

After H1 handshake:

1. `W1 CSTART <epoch> <operation>` binds CREATE intent.
2. `W1 KEY` selects namespace/name. An existing row yields CONFLICT. Otherwise the
   journal gets an OPEN operation with a fresh nonzero 72-bit generation and a
   zero-initialized, name-bearing logical template. No persona row is inserted.
3. The template uses the existing credited R1 transfer. Guest validation remains
   complete before original BCPL serialization and upload.
4. Eleven ordered `W1 PUT` frames and the final COMMIT XOR checksum are required.
5. The proposal is durably bound before the persona transaction, just as for SAVE.
   The transaction rechecks absence, then inserts the persona at revision 1 and
   commits its terminal journal outcome atomically. There is no upsert fallback.

CREATE, UPDATE and DELETE operation kinds are immutable. Terminal replay returns
the recorded outcome without recreating/deleting/updating a later generation.
Different data under an already bound ID returns REUSED. A failed first insert
attempt also retains its bound proposal. RESOLVE fences OPEN or absent operations;
it is not a passive status query. Inconclusive worker/commit results are UNKNOWN.

Two concurrent operations for one missing name cannot both publish. Depending on
SQL locking, the loser can observe CONFLICT or need resolution after an ambiguous
transaction error; it never overwrites the winner. The final acceptance race
observed one COMMITTED and one CONFLICT.

The existing journal's `kind` column supports CREATE; there is no additional
physical-slot schema. This is still private fixture provisioning, not a deployed
database migration or a public account-creation API.

## Acceptance and evidence

The successful original-game run is `runtime/external-creation-reboot/`, with
generated code/provenance in `build/external-creation-reboot/`. It passed eleven
named cases, four native control scenarios and sixteen baseline authentication
comparisons. Ordinary new-persona wrong/correct password re-entry was also tested.

| Case | Verified result |
|---|---|
| First explicit SAVE | No row at admission; saved score 0 and correct password re-entry |
| First score-bearing QUIT | Original gameplay produced score 11, persisted without explicit SAVE, restored on re-entry |
| Unsaved zero-score QUIT | No persona row |
| Missing-target ATTACH | Original sex question, ATTED SAVE rejection and no exit persistence |
| Lost first-create reply, DB restarted | Durable operation resolved; one creation attempt |
| First-create outcome UNKNOWN | Explicit recovery confirmed the existing creation, without another create |
| Pending first-create aborted | No row, delayed request fenced, a fresh explicit SAVE succeeded |
| Another creation wins during upload | Winner's password/profile retained; losing client never switched to UPDATE |
| Saved first-game record removed mid-session | QUIT reported missing; no new CREATE operation |
| Death after first SAVE, then new login | Record deleted, new creation got a different generation, old CREATE replay left replacement unchanged |
| Database unavailable at new-name lookup | Admission failed as unavailable; no phantom persona |

Female characters were exercised in the creation-failure/recovery cases. Saved
character fields were checked against each run's live SCORE output. Native versus
external records matched all words except independently rolled character stats
and native timestamps; these are not deterministic across separate runs.

Native `.PM` was renamed out of reach before external operation. FILCOM `/B`
confirmed unchanged retained bytes, and source hashes matched. Private fixture
credentials/record snapshots are mode 0600 under the private run directory and
must not be published as reports.

The test performs a clean KSYS shutdown after building and starts the compiled
image on the same disk, then performs another clean KSYS at completion. Earlier
attempts remain under `external-creation-first`, `-compiled`, `-native` and `-wake`.
They include a corrected BCPL command-syntax error and pre-LOGIN terminal stalls.
Private `creation-debug-*` runs also retain failed reboot/GET/re-entry/fixture
attempts. Removing unnecessary world resets and using the clean post-build reboot
gave the passing final run. The exact cause of every earlier terminal/GET stall
is not established; this milestone does not claim to fix generic emulator boot or
world-reset reliability. No failed storage call is automatically retried by the
acceptance harness.

SQL evidence: `runtime/persona-creates-final/` verifies clean templates, no early
publication, uniqueness, immutable and failed intent, concurrent creation,
CREATE/RESOLVE races, old create/delete replay after recreation, fresh generations,
outage and restart. Prior UPDATE and DELETE acceptances passed at
`runtime/persona-writes-creation-regression/` and
`runtime/persona-deletes-creation-regression/`. The final host suite passed 105 tests.

## Reproduction

```sh
.venv/bin/python -m tests.integration_native_creation
.venv/bin/python -m tests.integration_persona_creates
.venv/bin/python -m tests.integration_external_creation

.venv/bin/python -m tools.prepare --external-creation --output build/mud-creation-example
```

Use fresh output paths. The native game code ended at octal `505253`, below DBADAT
at `520000`; original DBASE regenerated 25,247 words. Keep matching executable and
world files together. MariaDB remains optional for native builds:

```sh
.venv/bin/python -m tools.prepare --always-open --output build/native-always-open-example
```

That last command selects original native persistence with only the opening-hours
change. No external-storage flag or MariaDB dependency is needed.
