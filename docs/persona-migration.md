# One-way native persona migration and external recovery

## Supported policy

Native-to-external migration is supported by the experimental tools below.
External-to-native conversion is intentionally unsupported. A native world can
still be built and run independently, including `--always-open` alone, without
MariaDB. Supporting that build does not require every future external data field
to fit the historical `.PM` format.

Before external play starts, an unsuccessful cutover can be abandoned and native
operation resumed from its untouched snapshot. After external play starts, that
snapshot is only a historical recovery point: returning to it discards subsequent
external progress. Recovery after cutover uses external database backups. There
is no automatic native fallback, dual write or reverse-export command.

These are local/operator maintenance tools, not deployment integration. They do
not automatically stop game services, configure an external browser bootstrap,
grant database accounts, migrate an old experimental schema or switch a live game.

## Tools and boundaries

- `tools.capture_personas`: independent native PMSNAP companion and private host
  snapshot capture. Explicit loopback port, device, persona filename and PPN.
- `tools.persona_snapshot`: lossless native image validation and private archive.
- `tools.persona_migrate`: fresh-schema initialization, import and verification.
- `tools.persona_backup`: whole selected MariaDB database backup and verified restore.

The external storage implemented here is MariaDB. Other backends would need their
own importer and recovery implementation. No Redis or DynamoDB adapter is claimed.

## Native capture

For interactive browser testing on a private copied disk with an empty external
store, see [the local external launcher](external-local.md). It provides local
per-session bootstrap, not automatic migration or production deployment.

Stop admission and let native players quit before final capture. Back up the
emulated disk only after stopping the emulator. Then, if needed, boot a private
copy of that stopped disk to perform the capture. Selecting the final snapshot
while native players continue writing gives a coherent point-in-time image but
does not capture their subsequent progress and is not a valid final cutover.

Example (use the actual private terminal port):

```sh
.venv/bin/python -m tools.capture_personas \
  --port 22020 --device dskb --persona-name mud --ppn 2011,2776 \
  --install --output /private/migration/native-personas.json

.venv/bin/python -m tools.persona_migrate inspect \
  --snapshot /private/migration/native-personas.json
```

The parent directory must already exist; use an owner-only directory. Omit
`--install` after PMSNAP has been compiled on that private disk. It is not the
ordinary public inspector: its response includes password words and must never
be sent to console transcripts, logs or published terminal recordings.

PMSNAP uses the same file-associated ENQ resource 142857 as native MUD. It reads
the complete header and logical slots into NEWVEC memory, then explicitly DEQs
and closes before terminal output. Acquisition may wait for a native writer;
the host capture has a ten-minute deadline and bounded output. It does not patch
or link the game. Interrupted/truncated output has no valid completed snapshot.

The snapshot is atomically published as mode 0600, never replacing an existing
path. It includes all physical header/slot words, a format version and SHA-256
over five-byte encodings of each unsigned 36-bit word. The framing also checks
word offsets, total count and final XOR. Neither checksum is an authentication
signature; retain trusted private files.

Validation covers logical length, slot alignment, hash chains, canonical names,
duplicate identities, bucket placement, cyclic/shared references, deleted/free
chains and unreferenced allocated slots. A zero-length empty header is accepted.
Corruption is rejected rather than repaired or silently omitted. Bounds are
8,192 allocated native slots and 4 MiB of capture/JSON. Deleted slots and reserved
header contents remain private provenance; only reachable live logical records
are imported. Each record retains offsets 1–11 exactly, including password,
native timestamp, flags, signed bit patterns and unused words. Offset 0's physical
chain pointer is not relational identity.

## Database configuration and provisioning

Commands read an owner-private JSON file, mode 0600, with `MariaDbConfig` fields:

```json
{
  "database": "mud86_personas",
  "user": "migration_operator",
  "password": "REPLACE_WITH_PRIVATE_CREDENTIAL",
  "namespace": "mud",
  "unix_socket": "/path/to/mariadb.sock"
}
```

For TCP, use `host`/`port` instead of `unix_socket`. Credentials are read from the
file, not placed on a command line or printed. Provision the database and account
separately. Runtime accounts should retain only their required permissions;
migration/backup accounts are operator credentials, not player credentials.

Initialize a **fresh, empty database**:

```sh
.venv/bin/python -m tools.persona_migrate init-schema \
  --config /private/migration/database.json
```

This installs the current persona, operation-journal and import-receipt schema.
Fresh initialization now uses [authoritative persona columns](persona-columns.md),
storage format 2. The importer still supports existing complete format-1 array
schemas; upgrading those is a separate offline command.
It rejects a database containing existing tables, views, routines or events.
DDL is not transactional: an interrupted initialization may leave a partial
schema. Keep services stopped, inspect it, and recreate a fresh database rather
than assuming the command can repair it. Existing compatible stores can use a
fresh namespace without initialization; this is not a general schema upgrade.

## Atomic import and verification

Keep the destination's game/bridge stopped and select a fresh namespace. Then:

```sh
.venv/bin/python -m tools.persona_migrate import \
  --config /private/migration/database.json \
  --snapshot /private/migration/native-personas.json

.venv/bin/python -m tools.persona_migrate verify \
  --config /private/migration/database.json \
  --snapshot /private/migration/native-personas.json
```

Import requires compatible InnoDB primary keys, no persona rows and no operation
history for the chosen namespace. It serializes importers with a named lock and
uses SERIALIZABLE transactions/gap locks in the runtime writer's lock order.
Stop other writers for cutover regardless; transaction locks are not a replacement
for operational coordination.

Every persona gets a fresh nonzero 72-bit generation and revision 1. The eleven
native words are read back and compared before commit. All persona rows and the
read-back-verified `persona_imports` receipt commit together. The receipt records
snapshot/logical digests and counts. It contains no password projection or public
credential report. A transaction error before commit rolls back all data; a lost
commit acknowledgement is reported as uncertain, never silently retried.

To recover an interrupted import, repeat **the identical snapshot and namespace**.
A matching durable receipt returns `already_imported`; another snapshot is
rejected. Import replay never inserts records again, even if gameplay subsequently
deleted or changed them. In particular, `already_imported` does not mean the current
database still matches the old native snapshot. Use `verify` before initial
admission for that comparison. After external gameplay, differences are expected.

Reports contain counts, namespace and hashes, not record payloads. Retain the
native snapshot as private provenance. Do not import again into another namespace
as a supposed update or reconciliation step.

## Cutover checklist

1. Stop native admission, finish sessions and obtain the final snapshot/disk backup.
2. Stop the destination bridge/game; provision compatible schema and a fresh namespace.
3. Import and verify every logical word/count. Resolve an uncertain import through
   its receipt before proceeding.
4. Perform controlled authentication and SAVE/re-entry checks using the intended
   external executable. Richard's historical direct-login exception remains;
   its correct saved password is not a verified direct-login credential.
5. Create and validate an external backup before admitting normal players.
6. Start only the external instance as authority for that namespace; keep the old
   native writer disabled. Preserve matching executable/world files and config.
7. Maintain tested external backups. Never switch to a stale native file on a DB outage.

## Whole-database backup

Stop/quiesce game and bridge writers and schema changes. The command also holds
READ locks on the selected database's tables/views while fingerprinting and
dumping, then releases them. This can block writers: schedule it as maintenance.
Avoid concurrent DDL and uncoordinated privileged maintenance. The tool does not
automatically verify that external services have been stopped.

```sh
.venv/bin/python -m tools.persona_backup backup \
  --config /private/migration/database.json --file /private/backups/store.zip

.venv/bin/python -m tools.persona_backup check \
  --file /private/backups/store.zip
```

Backup includes **the whole selected database**, not merely one namespace or the
current persona columns: operation journals, import receipts, extra tables and
views/routines/triggers/events are retained. It does not include server users,
grants, global settings, other databases, game disks or configuration files;
back those up/provision them separately. Cross-database dependencies require a
separate coordinated recovery plan.

The private ZIP contains MariaDB SQL plus a manifest with SQL SHA-256 and schema/
row fingerprints. Binary values, decimals and microsecond timestamps are verified.
Row fingerprints are bounded-memory multiset hashes with count/sum/XOR, so
physical row ordering need not match. Credentials live in a temporary private
client-options file; dump stderr/payload is never printed. Dump execution defaults
to a ten-minute bound and at most 1 GiB SQL. Publication is atomic, mode 0600 and
non-overwriting. Failed/oversized dumps leave no published backup. Private temporary
files and the archive contain credentials in persona words; protect them accordingly.

`check` verifies archive shape, size bounds, manifest consistency and SQL checksum.
It does not prove successful restoration or cryptographically authenticate the
archive. A restore drill is still required; use only trusted archives because
restore executes SQL.

## External-to-external restore

Restore on an isolated recovery instance, with game/bridge/writers stopped and
the event scheduler disabled. Create an empty database with the **same database
name** as the backup; use a new MariaDB instance to keep the existing production
database untouched. Provision suitable users/definers separately. Retaining the
database name avoids unsafe rewriting of stored SQL/dependencies.

```sh
.venv/bin/python -m tools.persona_backup restore \
  --config /private/recovery/database.json --file /private/backups/store.zip

.venv/bin/python -m tools.persona_backup verify-restore \
  --config /private/recovery/database.json --file /private/backups/store.zip
```

An occupied target is never dropped or overwritten. An exact already-loaded backup
can be verified and finalized, and an exact finalized restore can be retried.
Changed/unrelated targets are rejected. Failed SQL restore may leave partial DDL/
rows; keep services stopped and retry into a new empty recovery database. Restore
is not a transaction around arbitrary SQL DDL.

After loading, complete database/schema fingerprints must match. The command then
fences INIT/OPEN journal entries to ABORTED under WRITE locks and verifies the
expected finalized fingerprints. Terminal outcomes, generations, revisions and
extra data remain unchanged. Old uncommitted operations cannot later execute
against recovered state. Never resume old guest jobs: boot fresh external sessions
with fresh bootstrap challenges. Reconcile uncertainty against the restored journal
and recognize the backup's recovery point; writes made after that backup are not
recovered by this procedure.

The server must keep events disabled until verification, including after failures.
The SQL may carry event definitions and original definers; do not enable them or
grant missing-definer privileges without the deployment's recovery procedure.

## Verified evidence and limitations

- `runtime/migration-final/`: lossless import, atomic rollback, bad-receipt rejection,
  concurrent import, lost commit reply recovery, receipt-only retry after deletion,
  restart, CLI, schema initialization and operation-history rejection.
- `runtime/backup-acceptance/`: whole-database data/object preservation, owner-account
  credentials with special characters, restore fencing, post-restart verification,
  no overwrite after fresh gameplay, fresh/repeated restore reporting and CLI.
- `runtime/migration-native-final/`: eight personas plus one deleted native slot,
  all logical words compared, sixteen original-versus-imported authentication checks
  and sixteen more after DB backup/restore, retained native bytes/source unchanged,
  clean KSYS shutdown. Imported gameplay used the native file out of reach.
- 129 relevant host tests passed, including ten new snapshot/backup tests.

Native PMSNAP capture came from `runtime/migration-native-verified/`, independently
matched ROEXP and passed FILCOM before compilation. Its fresh-build command later
exceeded forty minutes during source transfer. Final game acceptance used a stopped
copy of the previously verified `external-lifecycle-green/machine-1` image and that
private captured fixture, explicitly recorded in the final report. It does not
claim the interrupted fresh build completed. Earlier TTY/FILCOM/receipt/schema
failures remain in their evidence directories. One final backup attempt failed
during disposable MariaDB system-table initialization; the subsequent standalone
acceptance passed. No live disk/service cutover was performed.

Native ENQ contention was already established by the inspection companion, whose
lock sequence PMSNAP reuses. This milestone verified quiescent coherent capture
and byte preservation; it did not repeat exhaustive concurrent-capture contention.
The native-file bound, import JSON format and MariaDB fingerprints reject unsupported
corruption/types rather than repair them. Production service orchestration, runtime
bootstrap/provisioning, schema upgrades and deployment rollback remain follow-up
work. None requires adding a supported external-to-native conversion path.
