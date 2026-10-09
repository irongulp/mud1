# External SAVE for existing personas

## Verified result and scope

The `--external-save-existing` generated variant now supports **explicit SAVE
of an existing MariaDB persona from the original MUD engine**. It loads the
persona, plays using the original BCPL world/actions, saves the changed state,
and restores the saved score on re-entry. A database restart also preserves it.

Final native evidence is `runtime/external-save-verified/`, with generated
sources/diff in `build/external-save-verified/`. The active `MUD..PM` was renamed
out of reach. The retained native persona file and host `source/` bytes remained
unchanged during external play.

This is the principal load/play/**explicit SAVE** proof for existing personas,
not complete native persistence coverage. Automatic QUIT/exit persistence,
creation, deletion/death persistence, PURGE, PASSWORD and outbound chaining
remain gated. The read-only variant and default native build remain available.

Follow-up: [external-exit-existing.md](external-exit-existing.md) adds eligible
exit updates in a separate generated mode. The explicit-SAVE-only mode described
here retains its automatic-persistence gate.

## Native policy and field equivalence

SAVE admission remains in the original `MUD5.BCL` dispatcher: forced-command and
speech checks, the ATTED restriction and the non-wizard unchanged-score check.
The adapter then obtains a **fresh save-time snapshot**, not the login snapshot,
and BCPL checks:

```text
stored SCRE >= savescr
```

If the guard fails, it prints the original score-change message and returns
zero. The original dispatcher still updates `savescr` after that normal zero
return; transport failures instead take an explicit error path. `savedp` is
incremented only after a confirmed commit.

The original `dumpersona()` is retained verbatim. It supplies PN/games, both
name words, score, packed characteristics, native LSTM, states and PSWD, leaving
untouched fields intact. The host does not calculate scores, change passwords,
clamp attributes or implement this policy.

The native test first records a successful ordinary SAVE and an attached
Richard SAVE using the native file implementation. External saves are compared
against those logical record words. All words matched except LSTM, which is
generated at the actual save time; the external timestamp advanced. The ordinary
route scored **11**, explicitly saved it and restored **11** on re-entry.

All 16 correct/wrong-password comparisons across the seven archwizards and an
ordinary control also matched the earlier native baseline. Richard's direct-login
restriction remains. Attached SAVE reproduces the historical password/PN behavior,
including writing the attaching session's password to Richard; this behavior
has not been redesigned. See [archwizard-password-audit.md](archwizard-password-audit.md).

## Atomicity without moving gameplay policy to SQL

The initial write adapter uses a short optimistic compare/update boundary:

1. BEGIN captures the current logical record, generation and revision in a
   durable operation journal and returns the record to BCPL.
2. BCPL applies its native score guard and serializes the proposed record.
3. COMMIT binds that proposal durably to the operation ID.
4. In a separate short transaction, the host locks the operation and persona,
   compares the saved generation, revision **and all prior words** with current
   storage, then atomically updates the persona and journal outcome.

The proposal-binding step may survive even when the mutation never happens.
Its purpose is to prevent a caller from substituting different data under the
same operation ID after an interrupted first attempt. The persona mutation and
its terminal COMMITTED outcome are always in one transaction.

A mismatch returns CONFLICT without changing the persona. The guest retries at
most three times, with a new operation ID and fresh snapshot each time, and
re-evaluates the BCPL policy. This is not a blanket maximum-score policy: the
native test deliberately introduces a higher stored score during a save, and
the retry may still save the lower in-memory score when the original `savescr`
condition permits it. A stored score below that threshold is rejected in BCPL.

Bounded conflict failure is an explicit extension to native ENQ waiting. The
prototype does not claim identical timing or indefinite-wait behavior under
contention.

## Durable operation identities and resolution

Each SAVE receives a nonzero 72-bit operation ID from its first fresh client
challenge. This ID is **independent of subsequent transport epochs**. If a reply
is lost, a new H1 handshake can resolve the original operation without reusing
the old epoch or resending a newly serialized profile.

The journal and persona table are scoped by the same configured namespace.
Identical duplicate commits return the recorded result and do not increment the
revision again. An old retry after a later save does not restore old data.
Different proposed words under a bound operation ID return REUSED.

**RESOLVE is a fencing write operation, not a passive status query.** It locks
the operation identity, including the initially absent case:

- COMMITTED remains COMMITTED.
- OPEN/INIT becomes ABORTED atomically.
- An absent operation receives an ABORTED tombstone.
- Other terminal outcomes remain terminal.

Thus resolution cannot report a safe abort and then allow a delayed old BEGIN
or COMMIT to mutate the persona. A concurrently committing transaction either
wins first and is reported committed, or observes the abort fence and cannot
write. Plain “no journal row visible” would not be sufficient.

The native reader automatically attempts resolution after an ambiguous commit
response. If the database remains unavailable, it reports **outcome unknown**
and retains the operation ID. Subsequent SAVE resolves that old operation before
any new save; ATTACH is refused while the outcome is pending. QUIT remains an
explicitly non-saving exit in this variant.

On later confirmation, recovery updates saved bookkeeping using the **serialized
checkpoint score**, not whatever score the player may have acquired since the
uncertain attempt. It reports the previous outcome and requires another SAVE
for new changes. It never labels those new changes as saved merely because the
old operation committed.

The journal must not be pruned while retries remain valid. No retention/archival
policy is implemented here. Backups/cutover must keep persona generations,
revisions and operation history coherent; restoring only one table is not a
supported recovery procedure.

## W1 wire extension

H1 and normal R1 reads remain unchanged. Every W1 frame fits the existing
79-byte line-body limit. `E` is a 24-octal-digit epoch, `O` a 24-digit operation
ID, `N`/`W` twelve-digit words and `II` a two-digit octal ordinal:

```text
Guest -> W1 BEGIN E O
Host  -> W1 ACK E 00
Guest -> W1 KEY E N0 N1
Host  -> R1 FOUND/WORD/END snapshot, using existing R1 acknowledgement credit
Guest -> W1 PUT E II W       (native offsets 01 through 13 octal)
Host  -> W1 ACK E II         (one upload word per acknowledgement)
Guest -> W1 COMMIT E CHECKSUM
Host  -> W1 RESULT E STATUS
```

All host-to-guest frames end with a single CR. COMMIT includes the same 36-bit
XOR construction as R1: format version, word count and all eleven uploaded words.
Missing/incorrect checksums, incomplete uploads, wrong order, name or epoch
cannot reach the database commit call. The checksum detects transport errors;
it is not authentication.

After a new H1 handshake, `W1 RESOLVE E O` returns a durable/fenced result.
`W1 ABORT E` resolves/fences the current prepared operation when BCPL declines
the save. Statuses include COMMITTED, CONFLICT, ABORTED, NOT_FOUND,
INVALID_RECORD, UNAVAILABLE, UNKNOWN and REUSED. A timeout after COMMIT is never
silently converted to NOT_FOUND or a definite failure.

## Database and process boundary

`tools/fixtures/persona_writes.sql` is an experimental, administrator-applied
extension to the read schema:

- Existing personas gain a 9-byte generation identity. Backfill while quiescent;
  every recreated identity must receive a fresh nonzero generation. NULL/zero
  generations are not writable through the adapter.
- `persona_operations` records the key, immutable before/after words, expected
  generation/revision and durable outcome, keyed by namespace and operation ID.

The tested writer account has SELECT and column-limited UPDATE of persona words
and revision, plus SELECT/INSERT/UPDATE on its operation journal. It cannot
create or delete personas and cannot change their generation. Schema changes
and fixture backfill use a separate administrative connection.

`tools/persona_write_mariadb.py` contains the SQL transactions;
`tools/persona_write_worker.py` runs one operation per bounded worker;
`tools/persona_writes.py` provides typed, storage-neutral methods/results.
`tools/persona_write_session.py` owns framing, epoch checks and upload credit.

The existing process boundary still caps concurrency at two workers and bounds
each call to 1.5 seconds plus a 0.25-second reap allowance. Workers receive no
bridge socket. A worker timeout during COMMIT or RESOLVE yields UNKNOWN even if
the server may already have committed. Statement/socket timers remain additional
defenses, not the publication deadline. Transaction durability relies on the
database's configured storage guarantees; the tests include database restart,
not physical power-loss acceptance.

## Validation and reproduction

```sh
.venv/bin/python -m tools.prepare --external-save-existing --output build/mud-save-example
.venv/bin/python -m tests.integration_persona_writes
.venv/bin/python -m tests.integration_external_save
```

Use fresh output paths and the optional storage dependencies described in
[persona-mariadb.md](persona-mariadb.md). Both integrations own private MariaDB
instances; the native test also owns a disposable baseline copy and private ports.
It uses the original compiler/DBASE and the existing TMPCOR bootstrap. The write
image's database is linked at octal `520000`; it is not an executable-only
replacement on older-address world files.

Host transaction evidence: `runtime/persona-writes-verified/`.
It verifies duplicate/concurrent commits, old retries after newer saves,
changed-intent rejection, stale snapshot and generation conflicts, missing-row
non-creation, absent-operation tombstones, prepared-intent fencing, restart and
commit/resolve races. The six final simultaneous commit/resolve races all
resolved ABORTED; sequential resolve-after-commit and concurrent identical
commits separately verify the COMMITTED cases.

Native evidence: `runtime/external-save-verified/`:

| Case | Result |
|---|---|
| Ordinary original-game SAVE | Native-equivalent fields, saved score 11, re-entry and database restart preserve it |
| Unchanged-score SAVE | Original non-wizard rejection preserved |
| Request not delivered to database, reply lost | Resolution aborts; delayed original commit is rejected |
| Commit succeeds, reply dropped, database restarted | Automatically resolved committed; revision increments once |
| Commit succeeds but database stays down | UNKNOWN; ATTACH blocked; later SAVE confirms the old outcome without another mutation |
| Concurrent administrative change | CAS conflict, fresh read and native policy retry; one game update |
| Stored signed score below `savescr` | Original BCPL guard rejects; no persona update |
| Richard ATTACH then SAVE | Native-equivalent password, PN and other record words, excluding clock-dependent LSTM |
| Preservation | Host source and retained native persona bytes unchanged |

Native tests compare all eleven words except time, which must advance relative
to the earlier native control. The original `dumpersona()` text is also checked
unchanged. Sixteen authentication comparisons still pass on the relinked image.
The final combined preparation, bootstrap, store and transport unit check passed
84 tests, including W1 credit/order/checksum rejection and unchanged R1 reads.

The native harness keeps disposable fixture credentials and control records in
`private-fixtures.json` under its 0700 output directory, with mode 0600. This is
a private fixture checkpoint, not an operator log or a publishable report.
Reports do not contain passwords or record bodies. Earlier failed/partial runs
remain, including compiler diagnostics and an outer harness timeout; the final
run completed and stopped its private services.

## Remaining work

The later exit variant verifies eligible alive-persona QUIT updates and
teardown-safe recovery. Creation/deletion and the native recycled-slot edge case,
broader lifecycle/disconnect acceptance, operation-history administration,
migrations and browser/production bootstrap remain separate steps.
