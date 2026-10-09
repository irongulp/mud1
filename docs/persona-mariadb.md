# Read-only MariaDB persona getter

## Verified boundary

A standalone BCPL reader under MUDGUEST now receives complete eleven-word
records **from a real MariaDB database** through the existing H1/R1 bridge.
The adapter is read-only, uses a SELECT-only account and bounds each driver
invocation in a separate killable worker process.

Final evidence: `runtime/persona-mariadb-verified/` (2026-09-26), using Python 3.9,
PyMySQL 1.2.3, local MariaDB 12.2.2 and the pinned TOPS-10/SIMH runtime. All 16
native calls and 59 host unit tests passed. Database fixtures are synthetic;
at that milestone it did not replace the game's `.PM` lookup or SAVE. The later
[read-only MUD variant](external-login-readonly.md) verifies real login/gameplay,
and the separate [existing-persona SAVE mode](external-save-existing.md) adds
explicit writes and durable resolution.

See [persona-read-native.md](persona-read-native.md) for the preceding transport
proof and [persona-storage-analysis.md](persona-storage-analysis.md) for the
remaining game interception requirements.

```text
PRREAD under MUDGUEST
        | H1 handshake / R1 GET / frame acknowledgements
Host ReadSession (owns the bridge socket and epoch)
        | PersonaStore.get(canonical_name_words)
IsolatedPersonaStore (deadline, capacity, bounded private pipes)
        | one short-lived worker; no bridge socket inherited
MariaDbPersonaStore (one SELECT-only connection)
        |
MariaDB personas table
```

## Storage-neutral contract

`tools/persona_store.py` defines `PersonaStore.get(name_words)`:

| Result | Meaning / R1 mapping |
|---|---|
| `LogicalRecord` | Complete validated record → FOUND |
| `None` | Successful lookup positively established absence → NOT_FOUND |
| `InvalidRecord` | Stored data does not satisfy the logical format → INVALID_RECORD |
| `StoreUnavailable` | Connection, permission, timeout, capacity or worker failure → UNAVAILABLE |

The two name words are a canonical logical key, not a filename or SQL expression.
The configured store namespace is trusted host configuration, not a guest field.
The interface does not expose SQL, driver exceptions, cursors or database
transactions to BCPL. Another backend can implement the same getter without
changing H1/R1.

Files:

- `tools/persona_errors.py`: storage-neutral, fixed-message failures.
- `tools/persona_store.py`: read interface and process isolation.
- `tools/persona_mariadb.py`: configuration, key/row conversion and direct adapter.
- `tools/persona_mariadb_worker.py`: private single-lookup worker entry point.
- `tools/fixtures/personas.sql`: experimental schema, provisioned by a separate
  administrator path, never by the getter.

Shared canonical-name validation was extracted from `GetRequest`; store code
does not manufacture a wire request just to validate a logical key.

## Schema and exact representation

The experimental `personas` table has:

| Column | Representation |
|---|---|
| `namespace` | `VARBINARY(64)`, exact case-sensitive store identity |
| `name_key` | `BINARY(9)`, big-endian concatenation of two canonical 36-bit words |
| `format_version` | Payload format, currently 1 |
| `words` | JSON array of exactly 11 unsigned 36-bit integers |
| `revision` | Unsigned metadata counter, initially 1; unused by this read-only API |
| `updated_at` | Database metadata timestamp, not a replacement for native LSTM |

The composite primary key is `(namespace, name_key)`. No database collation is
allowed to reinterpret persona names. PyMySQL binary parameters preserve the
packed key's arbitrary bytes. Native input parsing/case folding still belongs
to BCPL; the host accepts only the canonical key.

The array contains native record offsets **1–11**, excluding the physical
`POINTR` word. It preserves name flags, bitfields, the native password word,
timestamp and unused words exactly. The payload name must match the requested
key after removing only the name flag bits. Values must be integers in
`0..2^36-1`; floats, booleans, negative host integers and out-of-range values
are invalid. Native signed values are represented by their unsigned raw bits.

The query obtains version, byte length and payload in **one row snapshot**. It
returns payload bytes only when the JSON is at most 512 bytes; oversized data
is classified as INVALID_RECORD without transferring the entire value to the
driver. `LIMIT 2` bounds row count and permits rejection of duplicate identities
if an externally managed schema has lost its uniqueness constraint.

A stored JSON `null` is an invalid record, not an absent persona. Unsupported
formats, wrong word counts, malformed JSON and wrong-persona payloads also remain
distinct from absence. Compact JSON produced from eleven words fits comfortably
within the payload cap; excessive whitespace is still subject to that cap.

This schema is not a migration utility. It does not archive native hash/free-list
metadata or reproduce creation/deletion behavior, and `revision` does not imply
that optimistic updates have been implemented.

## Bounded database execution

Use `isolated_mariadb(config)`, not the direct driver adapter, on the bridge path.
Its default limits are:

| Limit | Value |
|---|---|
| Total lookup deadline | 1.5 seconds |
| Immediate worker-reap allowance | 0.25 seconds |
| Concurrent driver workers per shared store instance | 2 |
| Private worker request/reply caps | 4,096 / 2,048 bytes |
| MariaDB statement time | 0.5 seconds |
| MariaDB metadata lock wait | 1 second |
| Driver connect/read/write timeouts | 1 second each |

The parent uses nonblocking pipes and an absolute monotonic deadline covering
worker startup, request transfer, response reception and successful worker exit.
It then validates the entire response and checks closure/deadline again at the
publication decision. Merely printing a valid result before hanging is not
success. Neither a late FOUND nor a late NOT_FOUND may escape that decision.

On failure, the parent kills and reaps its worker. A pathological worker that
cannot be reaped promptly retains its capacity slot until a daemon reaper
confirms exit. At most the configured number of such slots/reapers can exist;
the implementation does not free a slot while leaving an unlimited background
driver call alive. Capacity exhaustion fails immediately rather than queuing
unbounded work.

Driver and server timeouts are additional bounds, not substitutes for the parent
deadline: individual socket reads can otherwise repeatedly reset their timeout.
Killing the local worker closes its database connection; server-side timers
separately limit normal statement/lock processing. This is not a promise of
immediate remote-server cleanup while that server or the host OS is stopped.

Workers receive credentials/configuration through stdin, not command arguments
or temporary credential files. Their stderr is not forwarded. Worker output
contains only a bounded typed result; raw driver messages are not sent into R1.
The password field is excluded from configuration representations, and record
bodies must not be printed or logged by callers.

The getter is synchronous from `ReadSession`'s perspective, so that channel
cannot process a new HELLO during a lookup. The 1.5-second default leaves room
within the native five-second response budget. Workers inherit no bridge socket
and cannot emit a delayed frame directly; epoch binding and acknowledgement
credit remain exclusively in the host session. There is no automatic query retry,
result cache or native-file fallback.

## Permissions and use

Provision the table and data through a separate administrative connection.
The tested reader account has SELECT on the persona table only. Each lookup
also sets the session's default transactions READ ONLY. It does not create,
import, update or delete records, even when the persona is missing.

Application wiring, with configuration supplied privately by the caller:

```python
from tools.persona_mariadb import MariaDbConfig, isolated_mariadb
from tools.persona_session import serve_reads

config = MariaDbConfig(**private_database_configuration)
with isolated_mariadb(config) as store:
    # connected_bridge_socket is an already bootstrapped private channel.
    serve_reads(connected_bridge_socket, store.get)
```

Share one store instance across the intended channel pool to share its worker
capacity. The factory supports a Unix socket or configured TCP host/port; the
acceptance runs used a private Unix socket. Public deployment, connection
encryption policy and credential provisioning are not supplied by this example.

## Reproduction and acceptance

Install the optional, hash-pinned Python dependency in the project environment:

```sh
.venv/bin/python -m pip install --require-hashes -r requirements-storage.txt
.venv/bin/python -m unittest tests.test_persona_store tests.test_persona_session tests.test_persona_protocol tests.test_storage_bridge -v
.venv/bin/python -m tests.integration_persona_mariadb --native
```

MariaDB's `mariadbd` and `mariadb-install-db` must already be available. The test
does not install/start a system service. It creates a fresh 0700 directory,
initializes its own data files with `--no-defaults`, disables TCP and query logs,
and starts only its own server process on a private Unix socket. Fixture setup
uses the private bootstrap root account; bridge reads use a newly generated
SELECT-only credential. Both the database and test emulator are stopped on exit.

`--output runtime/<fresh-short-directory>` selects evidence storage; keep it
short enough for a macOS Unix socket path. Omitting `--native` runs the real
database host checks without booting TOPS-10. Native mode copies the stopped
historical baseline and uses private ports with NOIDLE / 5M / SPEED=*8.

Final results in `runtime/persona-mariadb-verified/report.json`:

| Case | Native result |
|---|---|
| `fred`, nine-character `abcdefghi`, digit-containing `test1` | FOUND, all eleven words verified; 0.921–1.002 seconds |
| Missing row | NOT_FOUND, unpublished |
| Wrong count, unsupported format, wrong name, oversized JSON, JSON null | INVALID_RECORD, unpublished |
| Table held under an administrative write lock | UNAVAILABLE, unpublished; 0.821 seconds |
| Database process paused | UNAVAILABLE, unpublished; 1.325 seconds |
| SELECT permission revoked | UNAVAILABLE, unpublished; 0.308 seconds |
| Database stopped | UNAVAILABLE, unpublished; 0.315 seconds |
| Restart on the same database data directory | FOUND again without a cached/fallback record |
| Two guest jobs concurrently | Both records verified on distinct channels |

All sixteen calls acquired their channel on the first attempt. Six calls
published complete records (66 payload words); ten returned distinct non-FOUND
outcomes with the guest's publication vector untouched. The host-only checks
also verified namespace isolation and that the reader cannot DELETE even through
a separate raw SQL client.

The before/after digest includes every persona table row, its revision and
database timestamp. It matched. Native FILCOM `/B` confirmed unchanged `.PM`
bytes; original source SHA-256 values matched. No worker remained after the
checks. Earlier evidence is retained in `persona-db-host`, `persona-db-native`
and `persona-db-native-2`; the first native run stalled at OPR startup on all
three boot attempts, before PRREAD installation or any native database lookup.

There are 59 passing host tests: 17 for record/worker behavior plus the preceding
42 transport tests. New regressions cover hung/crashed workers, output limits,
capacity, kill/reap, closure and deadline races before publication, malformed
records and ambiguous duplicate rows. After green, canonical-key validation and
worker-result decoding were factored into shared helpers.

## Remaining game integration

The subsequent [generated read-only adapter](external-login-readonly.md) uses
MUD's channel allocator and per-job read-delete TMPCOR provisioning. It passed
actual-game login, targeted authentication comparisons, gameplay and re-entry
without the native persona file. Unsupported mutation/enumeration paths are
explicitly gated. The default build still uses native storage.

The existing-persona SAVE mode now verifies native policy and bounded, idempotent
transactions. A separate [eligible-exit variant](external-exit-existing.md) now
verifies normal QUIT persistence. Creation/deletion equivalence, broader lifecycle
tests, migration and browser/deployment integration remain later work.
