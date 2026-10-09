# Authoritative, readable persona columns

**Current schema:** [storage format 3](persona-timestamps.md) replaces the native
time halves and nine booleans described below with last_saved_at and nullable
observed-state timestamps. It also adds created_at before whole-second updated_at.
This document records the earlier format-2 layout and migration.

Persona storage format 2 stores values in ordinary MariaDB columns. There is no
`words` array in the current `personas` table. The typed host-side `ColumnPersona`
model translates values losslessly to/from the eleven native logical words.
BCPL gameplay and R1/W1 framing are unchanged: the wire format is still version 1.
Storage format and wire format are distinct.

This is a first step toward readable application data, not an implementation of
external world persistence. Native builds and original world compilation remain
supported; migration stays one-way native -> external.

## Read and update in TablePlus

Refresh the table/schema after upgrading, or reconnect. Run:

```sql
SELECT name, sex, games_played, score,
       strength, dexterity, stamina, maximum_stamina,
       wizard_mode, wizard_eligible, brief, revision, updated_at
FROM personas
WHERE namespace = 'mud'
ORDER BY name;
```

These scalar columns are editable in the normal table editor. Prefer changes
while the persona is logged out: an active job has its own in-memory profile and
does not immediately receive SQL changes. Its later fresh SAVE can replace an
administrative change under the original score/serialization rules.

Inspect the revision, then update with optimistic concurrency:

```sql
SELECT name, score, strength, revision
FROM personas WHERE namespace = 'mud' AND name = 'fred';

UPDATE personas
SET score = 1500, strength = 80, revision = revision + 1
WHERE namespace = 'mud' AND name = 'fred' AND revision = 7;
```

Use the actual inspected revision, not example 7. Zero affected rows means the
record no longer matches. There is no automatic revision trigger: include its
increment in the same committed administrative change, including grid edits.
Runtime SAVE increments it automatically. Full native-word comparisons also
detect changed snapshots, but revision makes the concurrency boundary explicit.

CHECK constraints reject out-of-range values, overlapping unknown/known flag bits
and a name inconsistent with its packed key. Normal MariaDB type-conversion/
strict-mode rules apply. SQL does not execute gameplay rules or grant a new kind
of in-game admission authority. `password_word` is encoded, not plaintext; use
in-game PASSWORD for normal changes. Identity renaming needs a deliberate operation,
since changing `name` alone would disagree with `name_key` and fail.

## Field reference

The full native range is retained, rather than clamping to typical gameplay values.
Representability does not imply sensible gameplay; native profile-loading rules
still apply when a player enters the game.

| Columns | Meaning / range |
|---|---|
| `namespace` | Persona-store identity |
| `name`, `name_key` | Canonical lowercase ASCII name, 1–9 letters/digits, with unchanged packed bridge key |
| `programmer_number` | Native PN, 0–262143; `OCT(programmer_number)` gives historical octal, not the player slot |
| `games_played` | Native 18-bit count, 0–262143 |
| `sex` | `male` or `female`, mapped to first name word's low bit |
| `asleep` | Second name word's low flag, 0/1 |
| `score` | Signed 36-bit score, -34359738368–34359738367 |
| `strength`, `dexterity`, `stamina`, `maximum_stamina` | Unsigned nine-bit attributes, 0–511 |
| `native_day`, `native_day_fraction` | Exact 18-bit LSTM halves, 0–262143; not Unix time or SQL updated_at |
| `wizard_mode`, `operator_mode`, `berserk`, `snoop`, `attached`, `brief`, `invisible`, `ignore_messages`, `wizard_eligible` | Known saved STATES bits 0–8, 0/1 |
| `unknown_state_bits` | Remaining STATES bits in original positions; 0–68719476735 with low nine bits clear |
| `password_word` | Original encoded unsigned 36-bit password; zero means none |
| `opaque_9`, `opaque_10`, `opaque_11` | Three untouched native words, each 0–68719476735 |
| `format_version` | Column layout version 2, distinct from wire version |
| `generation`, `revision` | Existing incarnation/update metadata, preserved by schema conversion |
| `updated_at` | MariaDB update time, independent of native LSTM |

There are no independent packed-score/attribute/state copies. The packed key is
an identity constraint, not a second independently editable name. Exact arrays
in `persona_operations.before_words/after_words` remain immutable journal intent/
history; they are not the current saved persona authority.

## Fresh schemas and compatibility

`tools.persona_migrate init-schema` and new local labs now install columns.
`tools.persona_columns.table_ddl()` defines the schema. `tools/fixtures/personas.sql`
remains a deliberate legacy fixture for compatibility/corrupt-row tests.

The adapter detects either complete layout, rejects partial layouts, and can
read/write existing format-1 array stores during transition. A gameplay request
never performs schema migration. Imports detect the selected layout and write
that representation; receipts, journals and whole-database backup remain supported.
Future backends can use the named logical model without emulating SQL columns.

## Explicit offline upgrade

Stop all game/bridge writers, live jobs and direct SQL/DDL writers. The generic
command creates a private whole-database backup before touching schema:

```sh
.venv/bin/python -m tools.persona_schema \
  --config /private/operator-database.json \
  --backup /private/backups/before-columns.zip \
  --writer-user persona_writer
```

For a stopped local lab:

```sh
# Stop tools.serve_external cleanly first.
.venv/bin/python -m tools.persona_schema \
  --local-state runtime/external-local \
  --backup runtime/external-local/before-persona-columns.zip
.venv/bin/python -m tools.serve_external
```

Always use a fresh backup path. The local option takes the launcher state lock,
starts the private DB for maintenance, uses its private root socket account, grants
the existing runtime writer named-column UPDATE permissions, then stops the DB.
The generic option requires a suitably privileged private operator config.
Existing SELECT/INSERT/DELETE grants remain; `UPDATE(words,revision)` alone is
insufficient for the new schema.

The upgrade checks the expected legacy columns and InnoDB engine, rejects
persona-attached triggers/foreign keys, and refuses pre-existing staging/archive
tables. Additional persona columns require an extended migration, not silent loss.
It bounds conversion at 65,536 rows across namespaces and leaves other tables
and operation/import journals unchanged.

It fills `personas_column_upgrade`, verifies every reconstructed word, namespace,
generation, revision and timestamp, rechecks source rows, and atomically swaps:

- `personas` becomes the verified column table.
- `personas_words_archive` retains historical pre-upgrade arrays.

Copying holds table locks, but MariaDB forbids RENAME while those locks are active.
Locks are released before source recheck/swap: **writers and DDL must remain stopped
throughout**. This is an offline verified table replacement, not an online
transaction around DDL. Failed staging never becomes authoritative. A failure
may leave staging data; inspect it with services stopped and use the backup/fresh
recovery instance rather than assuming automatic repair. An uncertain swap needs
inspection before restart.

The archive is historical, not rollback preserving later progress. Runtime only
accesses `personas`; editing the archive has no gameplay effect. Retain it until
verification and backup are complete, then remove only by explicit operator action.
Whole-database backups include it while present. No native-file writer is added.

## Evidence

- `runtime/persona-columns-acceptance/`: exact upgrade/metadata preservation,
  pre-upgrade journal replay, SQL score/strength edits, eight invalid updates
  rejected, stale SAVE/PURGE conflicts, CREATE/UPDATE/death/enumeration, restart,
  backup/restore and failed conversion preserving the original authority.
- `runtime/native-persona-columns/`: eight native imported personas and sixteen
  authentication comparisons, plus sixteen after restoring the column DB;
  logical words/native disk/source preserved. This reuses the stopped verified
  lifecycle image and earlier capture, not a new compilation claim.
- `runtime/external-columns-browser/`: Chromium creation/SAVE, PASSWORD/masking,
  full launcher/database/guest restart and re-entry, Roy creation and PURGE deletion
  through the actual gateway and column adapter.
- Legacy transaction/admin/backup/import regressions passed at
  `persona-writes-columns-verified`, `creates-columns-regression`,
  `deletes-columns-regression`, `admin-columns-regression`,
  `backup-columns-regression`, and `migration-columns-verified`.
- 166 relevant host tests passed. Codec tests cover full-width random values,
  signed scores, names/flags, invalid columns and conversion of SQL edits.

Browser PURGE exposed the gateway's missing input credit at its unstarred menu.
A failing host test reproduced it. The gateway now permits input at the exact
`Save, delete or finish? ` prompt, alongside ATTACH's existing password question;
the Chromium deletion check passed.

Local lab `runtime/external-local` was cleanly stopped, backed up at
`before-persona-columns.zip`, upgraded (one existing saved persona) and restarted
on port 8081. Read-only comparison with the archive verified exact words/metadata.
The config and passwords were retained. This is a local cutover, not deployment.

Parallel legacy regressions hit MariaDB initialization errors in the shared OS
temporary directory. Each fixture now owns private `tmp/`; subsequent checks passed.
Earlier evidence includes the corrected locked-RENAME failure and remains retained.
