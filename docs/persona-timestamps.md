# Persona timestamps: storage format 3

Format 3 replaces the native date halves and nine boolean state columns with
readable timestamps, and adds creation metadata. Original BCPL gameplay and the
version-1 bridge remain unchanged. Formats 1 (arrays) and 2 (numeric/boolean
columns) remain readable/writable during explicit offline migration.

## Column meanings and precision

| Column | Meaning | SQL type |
|---|---|---|
| `last_saved_at` | Native/emulated time when BCPL serialized the last checkpoint | Nullable `DATETIME(6)` |
| `wizard_mode_at`, `operator_mode_at`, `berserk_at`, `snoop_at`, `attached_at`, `brief_at`, `invisible_at`, `ignore_messages_at`, `wizard_eligible_at` | First successful external persistence observing the current enabled period; NULL means off | Nullable whole-second `TIMESTAMP`, default NULL |
| `created_at` | External row insertion time; unknown historical insertion times remain NULL | Nullable whole-second `TIMESTAMP`, default CURRENT_TIMESTAMP |
| `updated_at` | Real database row update time | Whole-second `TIMESTAMP`, default/on-update CURRENT_TIMESTAMP |

`created_at` appears immediately before `updated_at` in the table definition.
Normal SAVE does not change created_at. Native-to-external imports receive an
external insertion time, not a fabricated historical persona-birth date.
`asleep` remains a boolean. The binary namespace/name key/generation remain
identifiers, not dates. Score/attributes, unknown bits and opaque words are unchanged.

State markers are the authority: non-NULL reconstructs the native bit, NULL
clears it. There are no separate editable boolean copies. The flag name retains
its original meaning; wizard eligibility is distinct from active wizard mode.

## State transition rules

| Previously stored | Successful new checkpoint | Result |
|---|---|---|
| NULL/off | On | Current real UTC time, to seconds |
| Timestamp/on | On | Preserve the original observed timestamp |
| Timestamp/on | Off | NULL |
| NULL/off | Off | NULL |

Times describe observation at successful persistence, not exact in-memory toggle
events. Changes between SAVEs may not be visible. Turning off clears the current
period, so this is not full transition history. The observation clock is read in
the persona transaction; it may precede commit by the time taken to commit.

The timestamp change and durable outcome commit together. Failed transactions,
CAS/PURGE conflicts, aborted pending proposals and terminal operation replay do
not publish/reset state markers. Replaying an old committed SAVE after a newer
state change returns its old outcome without touching current timestamps.

All adapter connections explicitly use UTC. TIMESTAMP converts between the session
time zone and UTC storage: TablePlus can show it in its session time zone. Run
`SET time_zone='+00:00'` in a SQL editor for consistent UTC inspection. DATETIME
does not perform that conversion; last_saved_at is interpreted as UTC game time.

## Native last-save conversion

The exact original LSTM word comprises an 18-bit day count since 17 November 1858
and an 18-bit fraction of a day. Native zero maps to NULL. The full range extends
beyond TIMESTAMP's supported years, so last_saved_at uses DATETIME(6).

Conversion uses integer arithmetic and nearest-microsecond rounding. A native
tick is 86,400 / 262,144 seconds, approximately 0.32959 seconds. Re-encoding by
nearest native tick reconstructs every original fraction exactly; whole-second
storage would not. No duplicate native_day/native_day_fraction fields are kept.

Manual civil timestamps can be represented to finer precision than the native
game can use. The adapter maps them to the nearest native tick; a later game SAVE
serializes native time again. Last_saved_at is not real database updated_at and
must not be substituted for it in the game: LSTM drives last-play reporting and
stamina recovery. The emulated date can differ from the host date.

## TablePlus examples

Refresh the schema or reconnect after migration:

```sql
SET time_zone = '+00:00';

SELECT name, score, last_saved_at,
       wizard_mode_at, invisible_at, wizard_eligible_at,
       created_at, updated_at, revision
FROM personas
WHERE namespace = 'mud'
ORDER BY name;
```

Enable a saved flag:

```sql
UPDATE personas
SET invisible_at = CURRENT_TIMESTAMP,
    revision = revision + 1
WHERE namespace = 'mud' AND name = 'fred' AND revision = 7;
```

Disable it:

```sql
UPDATE personas
SET invisible_at = NULL,
    revision = revision + 1
WHERE namespace = 'mud' AND name = 'fred' AND revision = 8;
```

Use the actual revision you inspected. To enable without resetting an existing
observation, use `COALESCE(invisible_at,CURRENT_TIMESTAMP)`. Changing timestamps
manually can deliberately alter observation metadata. Include a revision increment
and prefer logged-out edits: SQL changes are saved-state changes, not live game
commands. Native snapshot comparisons do not distinguish different non-NULL
observation dates if their flag bit remains the same; revision guards do.

## Migration from format 2

Stop game/bridge sessions and all SQL/DDL writers. Take a fresh private backup:

```sh
.venv/bin/python -m tools.persona_schema --timestamps \
  --config /private/operator-database.json \
  --backup /private/backups/before-persona-timestamps.zip \
  --writer-user persona_writer
```

For the stopped local lab:

```sh
.venv/bin/python -m tools.persona_schema --timestamps \
  --local-state runtime/external-local \
  --backup runtime/external-local/before-persona-timestamps.zip
.venv/bin/python -m tools.serve_external
```

The local option takes the launcher lock, owns the private DB process during
maintenance, and grants the existing runtime writer UPDATE on the new fields.
Game requests never perform schema migration. Fresh init-schema and fresh local
labs now use format 3. A format-1 store must first complete its explicit v2
column migration; there is no silent skip over an unverified legacy schema.

The timestamp upgrade:

- Checks complete v2 columns and InnoDB, rejecting additional fields, persona
  triggers/foreign keys and earlier staging/archive remnants.
- Captures one real UTC observation time for all existing enabled flags. This
  is an explicitly backfilled **first external observation**, not historical
  activation. Disabled flags become NULL.
- Leaves created_at NULL for existing rows because birth/insertion time was not
  recorded. Does not infer it from updated_at, native time or a random generation.
- Converts last_saved_at and verifies exact native words, namespace, generation
  and revision. Existing updated_at microseconds are deliberately truncated,
  not used for concurrency. Operation/import journals remain unchanged.
- Verifies the staging table and rechecks source rows before atomic rename.
  `personas_columns_v2_archive` retains the pre-upgrade rows as historical data.

As with the earlier migration, MariaDB forbids RENAME with table locks active.
Writers/DDL must remain stopped across the unlock/recheck/swap window. DDL and
staging are not a rollbackable online transaction. A failed migration keeps the
original authority and any staging for inspection; no automatic repair/drop is
attempted. A confirmed already-upgraded layout is reported without applying a
new backfill time. Whole-database backups include the archives while retained.

The archive and backup do not preserve future progress when restored. External
recovery uses verified whole-database restore and fresh sessions; conversion to
native files remains unsupported.

## Evidence

- `runtime/persona-times-acceptance/`: migration, metadata order/precision,
  old journal replay, repeated-on preservation, clearing/re-enable, conflict,
  outage/abort, fresh creation-time preservation, manual NULL update, exact
  native words, backup/restore and failed migration preserving the old table.
- `runtime/native-persona-timestamps/`: eight imported native personas, sixteen
  auth comparisons and sixteen more after whole-DB restore, FILCOM/source
  preservation and clean shutdown on the stopped verified always-open image.
- `runtime/external-timestamp-browser/`: Chromium SAVE/PASSWORD/masking, full
  launcher/guest/DB restart, lookup after 75 seconds idle, Roy and PURGE deletion.
- `migration-timestamp-verified`, `backup-times-regression`,
  `columns-times-regression`, `writes-times-regression`: import, backup, v2
  migration and legacy transaction regressions.
- 174 relevant host tests passed, including exhaustive conversion of all 262,144
  day fractions, native boundary/random values and invalid timestamp fields.

The existing default local lab was stopped, backed up at
`runtime/external-local/before-persona-timestamps.zip`, upgraded (two personas),
and restarted at port 8081. Read-only comparison with the v2 archive verified
exact native words/identities and the expected null/truncated metadata. Existing
persona lookup reached the password prompt. This is local acceptance, not a
production deployment or world-storage migration.
