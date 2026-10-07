# External in-game PASSWORD and PURGE

## Scope

`--external-admin` adds the original in-game PASSWORD and PURGE behavior to the
external creation/SAVE/exit/death build. It is a separate opt-in variant; previous
experimental variants retain their gates and fully native builds remain supported.

POWER is a separate program: `source/MBOOTS.MAC:189` starts its embedded source,
and line 209 declares `/RUNAME:power`. It has not been ported. This milestone also
does not replace the separate native SSH inspection companions, install a public
MariaDB service or supply migration/browser-bootstrap deployment tooling.

Final native evidence: `runtime/external-admin-final/`, with generated code and
provenance in `build/external-admin-final/`. Fourteen administration scenarios and
sixteen authentication comparisons passed. Original-game controls covered four
PASSWORD cases, ordinary filtered enumeration and archwizard menu/enumeration/
deletion behavior. The final host suite passed 115 tests.

## PASSWORD stays in the game

Original `source/MUD5.BCL:623–662` remains the authority:

- Check the present password against the session's `ps.word` using original
  `encrypt()`.
- Read the replacement twice and reject mismatches.
- Allow only one attempt per game, including an incorrect present password or a
  mismatching confirmation.
- Change `ps.word` in memory, not directly in storage.
- Persist through subsequent eligible SAVE/QUIT using original `dumpersona()`.

The generated variant removes the old external PASSWORD gate and retains that
body verbatim. It does not invent a SQL password-update operation or bypass the
original SAVE score/ATTACH restrictions. A successful PASSWORD response is not a
claim that a database write has already occurred. Existing exit eligibility and
bounded failure behavior still determine persistence.

An unresolved SAVE or PURGE blocks PASSWORD before the interactive exchange,
avoiding a new in-memory password transition over an uncertain prior mutation.
These uncertainty gates have no native-file analogue; they are explicit external
transaction handling, not changes to password encoding or authentication rules.

## PURGE policy and menu

The generated routine retains original `source/MUD7.BCL:31–122` policy/display/menu
code while replacing persona-file traversal and mutation:

- The original combat restriction and dispatcher checks remain.
- Ordinary users only see records whose password word matches their session
  password. Non-wizards cannot choose deletion.
- Original `us(me)` archwizard recognition bypasses the password filter.
- Original WIZARD status controls the single-character Save/Delete/Finish menu.
- **Save means keep the displayed record**, not serialize the operator's profile
  over it. Finish stops enumeration. Only Delete requests a mutation.
- The original display is retained, including its historical sex-label quirk
  (`rec!1 bitand 1`, the games/PN word rather than the name's sex bit).

`PURGE <name>` performs targeted inspection. `PURGE THAT` explicitly requests
enumeration. As in native MUD, parser context matters for commands without an
explicit object; the acceptance tests use `THAT` for an unambiguous full traversal.

The routine restores `setbit()`, `flush()` and `alive()` after traversal, including
lookup failures. A pending-operation retry resolves the old operation and returns;
it does not silently begin a new listing. That early return also calls `flush()`.
The native test reproduced why this matters: omitting it let MUD process the same
PURGE command again after reporting the recovered deletion.

## Enumeration contract

MariaDB traversal uses the canonical packed-name key, not native physical slot
order. This is **live keyset traversal**, not a frozen snapshot of the entire table:

- Each next request selects the smallest key strictly greater than its cursor
  within the configured namespace.
- Every individual displayed record is a durable snapshot for its operation.
- Concurrent insertions before the cursor are not revisited; later insertions
  can be encountered. Removed rows can be skipped. Run another traversal for a
  later view of the dataset.
- Malformed records/keys and outages stop the listing with an error. They do not
  masquerade as an empty table or successful end-of-list.
- A command visits at most `purge.limit=2048` records, including filtered records,
  and explicitly reports an incomplete listing at the limit. Targeted lookup is
  separate. The admin build's per-job challenge budget is `admin.calls=8192`;
  other variants retain their earlier bound.

Each lookup returns only one eleven-word record through the existing bounded
worker pipe. There is no unbounded table-sized payload or game-sized record array.

## Conditional deletion and recovery

PURGE deletion is intentionally stricter than death deletion. The database binds
the name, generation, revision and all old words **when the record is selected**.
The original BCPL password/privilege checks and operator decision apply to that
snapshot. Confirmation removes the row only if it still matches the snapshot.

Thus a concurrent password change, ordinary update, opaque-word change or new
generation produces CONFLICT; the operator must inspect again. There is no blind
re-read/retry that could turn an old permission decision into deletion of a changed
persona. Death's existing generation-only deletion remains a separate operation.

New W1 frames use the existing H1 ownership handshake and octal identities:

| Flow | Frames |
|---|---|
| Targeted view | `PSTART` with operation ID, then `KEY`, then credited R1 record |
| Next record | `NSTART` with operation ID, then `NEXT` with cursor (zero pair means start), `NAME` response, client `FETCH`, then credited R1 record |
| Confirm Delete | Fresh handshake, `PDELETE` with the original operation ID, then `KEY` |
| Keep/Finish or recovery | Existing fencing `RESOLVE` |

PSTART/NSTART retire their transport session after the final record ACK. The guest
releases its bridge channel before asking the operator, so human input need not
fit the five-second W1 response deadline. A six-second menu delay passed native
acceptance. Confirmation opens a fresh transport session against the same durable
operation. No database row lock is held while waiting at the menu.

The journal distinguishes `PURGE` and `PNEXT` from UPDATE/CREATE/DELETE, and binds
the enumeration cursor in `cursor_key`. A death DELETE cannot reuse a PURGE view
to bypass the full-record guard. Mutations and terminal outcomes commit together;
replay returns the durable outcome. RESOLVE aborts/fences an OPEN or absent intent,
and a nameless tombstone fences a later request regardless of its cursor.

The bridge defaults to `allow_admin=False`; administration must be explicitly
enabled. The writer also needs the existing explicit DELETE grant. The new
`cursor_key` column is part of fresh private fixture provisioning, not an automatic
migration for an older experimental or deployed database.

PURGE has its own pending state, separate from SAVE bookkeeping:

- Lost replies resolve the original operation without issuing another deletion.
- UNKNOWN prints the operation ID and blocks SAVE, PASSWORD and ATTACH until
  recovery. Retrying PURGE resolves that operation and returns.
- QUIT attempts resolution. If still UNKNOWN, it closes without another write.
- If resolution yields a known abort/conflict, the pending state is cleared and
  the player's own normal eligible exit persistence can proceed. Recovery readiness
  is not the same as deletion success, and never increments `savedp`.
- A pending SAVE must be resolved before entering PURGE.

This preserves the existing external bounded-failure policy rather than native
indefinite file-I/O retry behavior. A view/keep operation changes only journal
metadata; it does not update the persona payload.

## Verification

`tests.integration_external_admin` reuses the disposable build/reboot harness from
the creation milestone. It owns its private disk, ports and MariaDB instance,
collects original-game controls, builds the variant with original DBASE, renames
the native persona file out of reach, and reboots cleanly before external checks.

The fourteen reported scenarios cover:

1. Correct PASSWORD followed by QUIT and old/new password re-entry checks.
2. Incorrect present password, unchanged password and consumed attempt.
3. Mismatching confirmation, unchanged password and consumed attempt.
4. Correct PASSWORD persisted by explicit SAVE.
5. Ordinary password-filtered enumeration and refusal to expose a nonmatching row.
6. Archwizard enumeration matching the native record set.
7. Keep/Delete/Finish, including a delayed menu choice and unchanged kept record.
8. Committed deletion with lost reply and database restart.
9. Password changed after selection: conflict, target retained.
10. Unresolvable deletion, blocked commands, then successful explicit recovery.
11. Enumeration outage reported as failure; command processing restored.
12. UNKNOWN PURGE at QUIT: no additional persistence.
13. Aborted PURGE resolved at QUIT: target retained and own eligible exit saved.
14. PASSWORD/PURGE blocked by a prior unresolved SAVE.

PASSWORD results matched all native persisted words except clock-dependent LSTM;
the test deliberately resets the boot clock between native and external phases.
Sixteen baseline authentication comparisons also passed. FILCOM `/B` confirmed
unchanged retained native persona bytes, source hashes matched, and clean KSYS
shutdowns completed before reboot and at final completion.

`runtime/persona-admin-verified/` records real MariaDB traversal/replay, changed
cursor rejection, full-word and generation conflicts, password-only change without
a revision bump, malformed first-key rejection, absent-operation fencing and
restart checks. UPDATE, DELETE and CREATE regressions passed respectively at
`runtime/persona-writes-admin-regression/`, `runtime/persona-deletes-admin-regression/`
and `runtime/persona-creates-admin-regression/`.

Earlier evidence is retained: `external-admin-first` failed during baseline TTY
setup; `external-admin-native` exceeded the 20-minute tool limit; `external-admin-verified`
reproduced the missing-flush recovery bug; `external-admin-recovery` passed the
initial scenario set. Private `admin-debug-*` runs reproduced the recovery bugs,
including the subsequently fixed suppression of own QUIT after a known abort.
The final acceptance is `external-admin-final`, not those earlier attempts.

Fixture credentials and native password-word snapshots remain in the private
mode-0600 fixture file. Reports contain outcomes and visible record names, not
passwords. Test-owned processes are stopped; no live disk or service is selected.

## Build and remaining scope

```sh
.venv/bin/python -m tools.prepare --external-admin --output build/mud-admin-example
.venv/bin/python -m tests.integration_persona_admin
.venv/bin/python -m tests.integration_external_admin
```

Use fresh output paths. The native build ended at octal `506445`; DBADAT remains
at `520000`, with 25,247 words from original DBASE. The full administration build
and native acceptance can take more than twenty minutes; allow sufficient runtime.

Native storage, including `--always-open` alone, remains independently buildable
without MariaDB. The external flags are mutually exclusive. POWER, external-aware
SSH inspectors, migration/import/export, browser deployment, outbound chaining and
broader arbitrary disconnect/cross-job lifecycle coverage remain separate work.

Follow-up: [external lifecycle and compatible-world chaining](external-persona-lifecycle.md)
now verifies shared first-SAVE recovery, selected stopped-job/disconnect cases,
and opt-in round trips between compatible images sharing a persona namespace.
It documents the remaining limits rather than claiming exhaustive lifecycle parity.
