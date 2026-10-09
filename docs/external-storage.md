# MUD1 External Storage

## Purpose

This document describes a proposed architecture for moving persistent MUD1 data out of native TOPS-10 disk files and into modern external storage while preserving the original MUD1 implementation running under TOPS-10 on an emulated PDP-10.

The key principle is:

**Do not port MUD1 away from TOPS-10 and do not make MUD1 database-specific.**

Instead, introduce a small storage abstraction between MUD1 and a host-side storage service.

The initial database implementation should use **MariaDB**, but the interface must remain independent of MariaDB so Redis, PostgreSQL, DynamoDB or another backend could be substituted later.

Historical upstream repository:

`https://github.com/PDP-10/MUD1`

The implementation target is this MUD86 restoration, using its pinned historical inputs and original BCPL/MACRO engine. The upstream link is provenance, not an instruction to substitute a different source revision.

Throughout this project, preserve `source/` byte-for-byte. Generate modified BCPL/MACRO files into `build/` using reproducible preparation steps and reviewable patches. Run prototypes and comparisons on disposable runtime disks, never the live game disk. See [restoration.md](restoration.md) for the existing build and runtime constraints.

---

# 1. Goals

The long-term architecture should allow persistent MUD1 data to live outside the emulated TOPS-10 filesystem.

Candidate data includes:

1. Persona/player records.
2. MUD world/database state.

The first proof of concept should address **personas only**.

A successful first milestone is:

> A player logs into the original MUD1 running under TOPS-10; their persona is obtained from MariaDB rather than the native `.PM` persona file; they play normally; changed persona data is subsequently persisted back to MariaDB.

TOPS-10 should otherwise continue operating normally.

---

# 2. Architectural principle

Do NOT expose SQL, Redis commands, DynamoDB concepts, etc. to MUD1.

MUD1 should communicate in terms of MUD operations.

Conceptually:

```text
                 PDP-10 emulator
                       │
                    TOPS-10
                       │
                     MUD1
                       │
              MUD storage protocol
                       │
              =====================
              PDP-10 / host boundary
              =====================
                       │
                       ▼
             MUD Storage Service
                       │
               Storage interface
                       │
          ┌────────────┼─────────────┐
          ▼            ▼             ▼
       MariaDB       Redis        DynamoDB
       adapter       adapter       adapter
          │
          ▼
       MariaDB
```

Initially only the MariaDB adapter needs to exist.

The PDP-10-facing protocol must not change if the backend database changes.

---

# 3. Why personas are the first target

MUD1's persona subsystem is relatively self-contained.

Relevant source is primarily in:

`MUDLIB.BCL`

Important routines include:

```text
searchrec(name)
saverec(name)
addrec(name)
deleterec(name)
dumpersona(place)
```

The existing persona file uses a `.PM` file.

MUD1 effectively implements a small database itself on top of TOPS-10 random-access file operations.

`searchrec()` hashes a persona name using a hash table with 253 entries and follows `POINTR` chains to locate records.

`addrec()` handles:

- hash-table insertion;
- free/deleted record reuse;
- `DEL`;
- `FLEN`;
- record chaining.

Consequently much of this machinery exists to provide indexed record storage on top of the TOPS-10 filesystem.

An external database can provide those facilities directly.

However, these routines are not yet a clean storage interface. `searchrec()` leaves a disk-relative `rec` and record data in `dmpbuf`; login and ATTACH interpret those side effects directly (`source/MUDLIB.BCL:1100–1106`, `source/MUD7.BCL:183–188`). `purge()` also reads `FLEN` and walks persona-file blocks rather than using only the record routines (`source/MUD7.BCL:31–112`).

Source analysis must inventory direct file/block access and record-buffer assumptions as well as calls to the named functions. Replacing those functions alone does not establish complete external-storage coverage.

---

# 4. Persona lifecycle

The important architectural observation is that MUD1 does not need the persona database for every game operation.

The persona is loaded into the player's in-memory profile.

Gameplay operates primarily against that state.

At appropriate persistence points, the profile is written back.

This is advantageous because the external database does NOT need to participate in every game operation.

The basic lifecycle can therefore become:

```text
LOGIN

MUD1
 │
 ├── request persona "FRED"
 │
 ▼
Host storage service
 │
 ▼
MariaDB
 │
 └── persona data
       │
       ▼
MUD1 profile in PDP-10 memory


       GAMEPLAY

MUD1 operates normally using profile


       SAVE

MUD1 profile
 │
 ├── save persona "FRED"
 ▼
Host storage service
 │
 ▼
MariaDB
```

---

# 5. Storage API

Initially keep the PDP-10-facing API extremely small.

Conceptual operations:

```text
GET_PERSONA
PUT_PERSONA
CREATE_PERSONA
DELETE_PERSONA
```

Possible request semantics:

```text
GET_PERSONA FRED
```

Response:

```text
FOUND
<persona representation>
```

or:

```text
NOT_FOUND
```

Saving:

```text
PUT_PERSONA FRED <persona representation>
```

Response:

```text
OK
```

The precise binary/wire representation should be determined after examining how best to bridge the PDP-10 emulator to the host.

Do not prematurely choose JSON as the PDP-10 wire format.

A compact binary or word-oriented protocol may be considerably easier for BCPL.

The host service can convert that representation into JSON/SQL/etc.

### Coverage and operation semantics

These four operations are a starting point, not a complete compatibility contract. Native persona enumeration, including the `purge()` path, needs an enumeration operation with defined traversal semantics or must be explicitly unsupported in the limited prototype. Full compatibility cannot be claimed while a command still depends on the native persona file.

Define the following before implementing writes:

- whether each operation creates, replaces, or conditionally updates a record;
- which native preconditions remain in BCPL and how their read/check/write sequence remains atomic;
- how enumeration interacts with concurrent creation, deletion and updates;
- protocol and payload-format versions, independently of record revision numbers;
- the mapping from returned logical records to existing BCPL callers, without leaking native disk offsets into the backend-neutral API.

### Failure contract

Distinguish at least `NOT_FOUND`, storage/bridge unavailability, invalid records, rejected updates and an unknown write outcome. A lookup failure must never be treated as an absent persona. A write may commit even when its acknowledgement is lost; timeout alone proves neither success nor failure.

Specify bounded request deadlines, response validation, retry/idempotency rules and recovery for ambiguous writes. Define how BCPL releases locks, reports unsuccessful persistence and handles the player session on each failure path. Do not acknowledge a save before the backend's defined durable commit, or blindly retry an ambiguously completed mutation.

Design this contract during bridge/protocol work, before the first write milestone. Comprehensive failure testing follows, but failure semantics are not deferred until then.

---

# 6. MariaDB representation

For the initial proof of concept, avoid attempting to fully normalise MUD1's persona structure.

A useful initial schema would be approximately:

```sql
CREATE TABLE personas (
    id BIGINT PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    data JSON NOT NULL,
    format_version BIGINT NOT NULL DEFAULT 1,
    version BIGINT NOT NULL DEFAULT 1,
    updated_at TIMESTAMP NOT NULL
        DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP
);
```

The `data` JSON should initially contain a logical representation of the original MUD persona.

For example:

```json
{
    "gamesPlayed": 187,
    "score": 124560,
    "strength": 93,
    "dexterity": 87,
    "stamina": 91,
    "staminaMax": 100,
    "playerNumber": 42,
    "states": 1234
}
```

This example is illustrative.

The table is also illustrative: define ID allocation and name equality before using it. `version` is a concurrency revision; `format_version` identifies the encoded persona layout. They serve different purposes.

**Determine the exact persisted fields and their semantics from the source before defining the production schema.**

Particularly important:

- preserve PDP-10 integer semantics;
- identify signed vs unsigned values;
- preserve bitfields exactly;
- preserve identifiers/object references;
- understand BCPL string representation;
- do not silently truncate 36-bit values into 32-bit host types.

MariaDB `BIGINT` is suitable for individual PDP-10 36-bit integer values where relational columns are eventually desirable.

The native layout is already declared in `source/DUNGEN.GET:776–815`: 12 words containing a chain pointer, packed PN/games fields, two name words, score, four packed characteristics, last-use time, states, password and three unused words. The field map must distinguish file bookkeeping such as `POINTR` from logical persona data and preserve unknown bits until their meaning is established. Do not infer that native `PN` means the current in-game player slot from the JSON example's `playerNumber` label.

Specify a lossless canonical representation and prove encode/decode round trips. Retaining exact 36-bit record words alongside decoded fields is a useful prototype approach; if both are retained, define which representation is authoritative and prevent them from diverging. Do not treat a native chain pointer as an external record identity.

Include `LSTM`: login uses elapsed time since the stored last-use time to restore stamina (`source/MUDLIB.BCL:1148–1152`). The example JSON above is not a sufficient import format.

Derive name canonicalisation and equality from native input, string packing and comparison code, including differences between login and ATTACH. Configure the database key/collation to implement that contract explicitly; a default `VARCHAR ... UNIQUE` collation does not establish compatibility.

---

# 7. Passwords

Treat the existing MUD1 password representation carefully.

The first objective is compatibility, not authentication redesign.

Do not change password semantics while implementing external persona storage.

Initially preserve whatever representation MUD1 expects.

A later project can consider modernising authentication independently.

Keeping this separate makes it much easier to determine whether failures arise from storage changes or authentication changes.

There is a known executable-layout dependency: Richard's direct-login comparison uses an address-derived calculation involving `@name` (`source/MUDLIB.BCL:1115–1121`). Preserving password words and leaving authentication source unchanged does not alone prove unchanged behaviour after relinking a modified executable.

Use [archwizard-password-audit.md](archwizard-password-audit.md) as the baseline. Require native-versus-external authentication checks for ordinary personas and all seven archwizard names, explicitly covering Richard's known direct-login limitation and verified ATTACH path. Test ATTACH followed by SAVE and QUIT: loading the saved states can clear ATTED, and subsequent persistence can write the attaching session's password. Preserve and document the observed native behaviour rather than assuming attachment cannot save.

Reference [archwizard-provisioning.md](archwizard-provisioning.md) for existing fixture/provisioning practice. Authentication compatibility is a gate for accepting a modified executable, not just a schema check.

---

# 8. Concurrency

The native persona implementation uses TOPS-10 locking (`ENQ`/`DEQ`) and MUD's `persona.door` mechanism.

The existing implementation can therefore encounter contention on the persona file.

External storage potentially allows finer-grained locking.

However:

**Do not remove MUD1's concurrency semantics until they are fully understood.**

For the proof of concept, reproduce existing behaviour as closely as practical.

In particular, native save is not an unconditional upsert:

- `saverec()` checks the stored score against `savescr` before writing (`source/MUDLIB.BCL:1295–1306`).
- `addrec()` refuses to recreate a missing record for a profile with more than one game played (`source/MUDLIB.BCL:1336–1338`).
- `writeprofile()` conditionally saves or deletes according to stamina and other profile/session state (`source/MUDLIB.BCL:1224–1264`).

Keep gameplay and persistence eligibility decisions in BCPL. Document the actual lock scope, including file-associated ENQ and the shared-memory door, and preserve the read/check/write critical section across the bridge or provide an equivalent atomic conditional operation. An unconditional host-side upsert is not equivalent. Existing guest-file locks alone cannot coordinate external writers; initially disallow writers outside the defined storage path.

Eventually the host storage service could provide operations such as:

```text
GET_PERSONA(name, version)

PUT_PERSONA(name, expected_version, data)
```

and use optimistic concurrency:

```sql
UPDATE personas
SET data = ?, version = version + 1
WHERE name = ?
AND version = ?;
```

This prevents two sessions silently overwriting one another.

That statement requires the caller to supply the revision it read, check the affected-row count and handle conflicts without silently retrying a stale replacement. Optimistic concurrency is a possible later behavioural change, not an assumed reproduction of native semantics. If adopted, include revision/conflict handling in both the protocol and `PersonaStore` interface, and specify deletion/recreation handling so an old revision cannot match a newly created persona accidentally.

---

# 9. Host storage service

Create a standalone host-side service.

Its responsibilities should be:

1. Accept storage requests from the PDP-10/emulator boundary.
2. Decode PDP-10/MUD representations.
3. Invoke a storage interface.
4. Encode responses for MUD1.

Internally define an interface conceptually similar to:

```text
PersonaStore

get(name)
create(name, persona)
put(name, persona)
delete(name)
```

The MariaDB implementation should implement this interface.

For example:

```text
PersonaStore
     ▲
     │
MariaDbPersonaStore
```

Future implementations might include:

```text
RedisPersonaStore
DynamoDbPersonaStore
PostgresPersonaStore
FilePersonaStore
```

None should require changes to the PDP-10 protocol.

---

# 10. PDP-10/host bridge

This is likely to be the most technically interesting part of the project.

Do not assume the solution before inspecting the emulator and MUD1 environment.

Potential mechanisms include:

- networking from TOPS-10;
- an emulated character/device interface;
- emulator-specific host calls;
- shared communication through an emulated device;
- another simple IPC mechanism exposed by the emulator.

Selection criteria:

1. Minimal modification to MUD1.
2. Minimal modification to TOPS-10.
3. Reliable synchronous request/response operation.
4. Easy debugging.
5. Ability to transfer arbitrary 36-bit MUD values without corruption.
6. Eventually usable for both personas and world objects.

The bridge should be generic enough that world-database operations can later use the same transport.

The feasibility proof should also establish how requests from multiple TOPS-10 jobs are correlated and isolated, how a stalled service affects the emulator and guest locks, and how disconnect/reconnect avoids accepting a stale response. Select transport and framing only after inspecting the pinned SIMH/TOPS-10 environment. PING/PONG proves connectivity, not storage correctness.

---

# 11. Do not replace TOPS-10 storage generally

This project is NOT intended to replace TOPS-10's filesystem.

TOPS-10 should continue storing:

- executables;
- BCPL/MACRO source;
- libraries;
- logs where appropriate;
- operating-system files;
- other normal files.

Only application-level MUD persistence should cross the storage bridge.

Avoid implementing a MariaDB-backed virtual TOPS-10 disk.

That would introduce an unnecessary filesystem/block-device translation layer and couple the solution to TOPS-10 internals.

---

# 12. World database — later phase

Once personas work reliably, investigate externalising the MUD world database.

The same principle applies.

Conceptually expose MUD operations such as:

```text
GET_OBJECT id
PUT_OBJECT id data
```

rather than storage operations such as:

```text
SELECT ...
HGET ...
GetItem ...
```

A possible eventual architecture is:

```text
                 MUD1
                   │
          ┌────────┴─────────┐
          │                  │
      Personas          World objects
          │                  │
          └────────┬─────────┘
                   │
             Storage protocol
                   │
                   ▼
           Host storage service
                   │
             Storage backend
                   │
                 MariaDB
```

Do not attempt this until persona persistence has proved the bridge.

First distinguish the compiled world/database assets from mutable live shared-memory world state. Determine which state survives sessions, which is intentionally recreated on a world reset, and whether any new durability would change gameplay. `GET_OBJECT`/`PUT_OBJECT` is only a sketch, not evidence that individual object CRUD is the correct boundary. Preserve the original DBASE compiler as authoritative for generated game data; do not replace it with a host-side world model.

---

# 13. Observability

One major benefit of external storage is that modern tools can inspect the MUD without understanding TOPS-10 disk structures.

Design the host service with this future use in mind.

Potential later facilities include:

- web-based persona administration;
- world browser;
- object search;
- player statistics;
- score/rank reporting;
- historical state;
- backups;
- auditing;
- world visualisation;
- API access.

Do not implement these during the proof of concept.

They are reasons for maintaining a clean host-side abstraction.

---

# 14. Preserve authenticity

A fundamental project objective is that this remains **MUD1 running on a PDP-10**.

Avoid gradually turning the project into a Linux reimplementation of MUD1.

The following should remain authoritative:

```text
MUD1 BCPL/MACRO code
        │
        ▼
TOPS-10
        │
        ▼
PDP-10 emulator
```

Modern infrastructure exists around that system rather than replacing its execution environment.

Game logic remains in MUD1.

The host service provides persistence, not gameplay.

---

# 15. Proposed implementation phases

## Phase 1 — Source analysis

Trace the complete persona lifecycle.

Document:

- persona record layout;
- every persisted field;
- `searchrec`;
- `saverec`;
- `addrec`;
- `deleterec`;
- `dumpersona`;
- persona creation;
- login;
- logout;
- autosave/checkpoint behaviour;
- locking;
- password handling;
- BCPL/PDP-10 representation details.

Also inventory enumeration, direct block access, `rec`/`dmpbuf` side effects, save/delete preconditions and all critical-section boundaries. Include ATTACH, death, explicit SAVE, conditional QUIT persistence and administrative persona operations. Separate observed native behaviour from intended future improvements.

Produce a field map before changing code.

## Phase 2 — Identify bridge

The standalone [storage-bridge-probe.md](storage-bridge-probe.md) now records a
verified secondary-terminal PING/PONG experiment, exact 36-bit round trips,
concurrent isolated jobs and selected failure cases.
[storage-channels.md](storage-channels.md) verifies MUDGUEST ownership and a
bounded native channel pool. [persona-read-protocol.md](persona-read-protocol.md)
defines the read-only record codec and H1 handover. The standalone
[native R1 proof](persona-read-native.md) now verifies epoch handover, full-record
decoding, credit flow and restart using synthetic records. The later
[MariaDB getter](persona-mariadb.md) verifies bounded database-backed reads through
that standalone reader. The [read-only game adapter](external-login-readonly.md)
then verifies original MUD login/gameplay with TMPCOR challenge provisioning.
Write-transaction semantics and deployment integration remain open.

Inspect the PDP-10 emulator and determine the smallest reliable host communication mechanism.

Implement a trivial proof:

```text
PDP-10 → PING
host   → PONG
```

No database yet.

Before proceeding to writes, document the operation, representation, failure and backend-authority contracts described above. Extend bridge checks to multi-job request isolation, bounded failure and arbitrary 36-bit value round trips.

## Phase 3 — Read-only persona lookup

The host/standalone-reader slice is verified in
[persona-mariadb.md](persona-mariadb.md). The later
[generated read-only game variant](external-login-readonly.md) verifies actual
MUD login, targeted authentication compatibility, gameplay and re-entry with
the native persona file absent. This is a Phase 3 prototype; the principal
load/play/save proof remains incomplete until external persistence is verified.

Implement:

```text
GET_PERSONA
```

Populate MariaDB manually with one known test persona.

Use a source-derived, lossless fixture with known native behaviour rather than constructing a record from the illustrative JSON. Compare decoded values and authentication outcomes with the native baseline.

Demonstrate that MUD1 can retrieve it.

Native PM-file support should remain available during development.

Select one authoritative backend per disposable instance; do not fall back to native data when an external lookup fails.

## Phase 4 — Persona save

The [existing-persona explicit SAVE prototype](external-save-existing.md) now
passes original-game save/re-entry, native field comparisons and lost-acknowledgement
recovery. It intentionally retains gates for automatic exit persistence,
creation/deletion, PASSWORD, PURGE and outbound chaining. This is not yet full
persona lifecycle equivalence or a production deployment.

The later [eligible-exit variant](external-exit-existing.md) also verifies
ordinary QUIT updates, native skip conditions, pending-operation recovery and
exit promotion. The subsequent [death variant](external-death-existing.md)
verifies eligible FOD deletion, native skip conditions, generation-fenced replay
and pending-SAVE recovery. [Logical creation](external-persona-creation.md) now
also has native/SQL acceptance; broader lifecycle coverage remains a separate gate.

Implement:

```text
PUT_PERSONA
```

Demonstrate:

1. login;
2. retrieve MariaDB persona;
3. play;
4. change persisted state;
5. save;
6. verify changed state directly in MariaDB;
7. restart/re-login;
8. verify MUD1 restores the changed state.

This is the principal proof of concept.

Before accepting it, verify native save preconditions and distinguish rejected, failed and ambiguously completed saves. Include a lost-acknowledgement test and verify that retries cannot incorrectly duplicate or replay a mutation. Run the authentication compatibility gate against the modified executable.

## Phase 5 — Creation/deletion

Existing-persona death deletion has native/SQL acceptance in the opt-in
`--external-death-existing` variant. The subsequent
[logical creation milestone](external-persona-creation.md), `--external-creation`,
adds native first-SAVE/eligible-QUIT creation with atomic create-if-absent and
fresh generations. Native allocation quirks were characterized and explicitly
excluded from the relational contract. Administrative PURGE and broader lifecycle
coverage remain pending; this is not full persona administration or deployment.

Follow-up: the [in-game administration milestone](external-persona-admin.md)
implements PASSWORD plus targeted and enumerated PURGE in `--external-admin`.
Native password/privilege/menu policy remains in BCPL; PURGE confirmation uses a
full-record conditional delete and bounded live keyset traversal. Standalone
POWER is explicitly deferred. Deployment and broader lifecycle coverage remain
separate gates.

The [external lifecycle milestone](external-persona-lifecycle.md) subsequently
verifies shared first-SAVE recovery across jobs, selected DET/CONT and EXORCISE
cases, real gateway cleanup on external sessions, guest-loss checkpoint recovery,
and explicitly configured compatible-image chaining within one persona namespace.
Its acceptance is targeted: rare native lock/memory failure callbacks and
production bootstrap/migration are still separate work.

Implement:

```text
CREATE_PERSONA
DELETE_PERSONA
```

Verify behaviour matches the native system.

## Phase 6 — Concurrency and failure behaviour

Test:

- simultaneous access;
- database unavailable;
- bridge unavailable;
- malformed records;
- interrupted saves;
- duplicate persona creation;
- stale updates;
- committed writes with lost acknowledgements;
- retries after service restart;
- lock release and session handling after failure;
- deletion/recreation with an outstanding stale update;
- concurrent enumeration and mutation, when enumeration is supported.

MUD1 must fail safely.

Here this means, at minimum: no false `NOT_FOUND` on outage, no false save acknowledgement, no silent backend fallback, no unbounded orphaned lock, and a defined recovery path for unknown write outcomes. The contract is designed before Phase 4; this phase broadens its fault-injection coverage.

## Phase 7 — Migration

Write a migration utility capable of reading an existing `.PM` persona database and inserting its records into MariaDB.

Do not require existing personas to be recreated manually.

The supported migration policy is now **one-way: native to external**. Import from
a quiescent or coherently locked snapshot; verify record counts, canonical-name
uniqueness and lossless words including passwords/unknown bits. Cutover selects
exactly one authority. External-to-native conversion is intentionally unsupported;
native builds remain independently supported. After external writes, recovery
uses external backups rather than stale native personas. See
[persona-migration.md](persona-migration.md) for implemented capture/import receipts,
verification, whole-database backup/restore, acceptance and cutover procedure, and
[inspection.md](inspection.md) for prior native locking findings.

## Phase 8 — World database investigation

Only after persona storage is stable, perform equivalent source analysis for the main MUD world database.

---

# 16. Compatibility mode

During development it would be highly desirable to retain both implementations:

```text
PERSONA_STORAGE=NATIVE
```

and:

```text
PERSONA_STORAGE=EXTERNAL
```

This allows identical scenarios to be run against both implementations.

It will be invaluable for finding semantic differences.

If practical, build automated comparisons of the resulting persona state.

Treat these as conceptual mode selectors, not existing configuration options. Select the backend before starting the test instance and retain that authority for its lifetime. There is no automatic native fallback on external errors and no implicit dual-write mode.

Start differential scenarios from equivalent fixtures on separate disposable instances. Compare persisted state and player-visible outcomes, accounting explicitly for clock-dependent values. Cover creation, login, SAVE, conditional QUIT, death/deletion, ATTACH, enumeration, concurrent access and the known authentication exceptions. Reverting a disposable experiment to its original fixture is distinct from preserving progress through an operational rollback.

---

# 17. First task for OpenCode

The initial source-analysis report is now available in
[persona-storage-analysis.md](persona-storage-analysis.md). It inventories the
native paths, recommends a guest-side logical-record adapter, and distinguishes
source findings from pending native experiments and bridge implementation.

Do NOT begin by writing MariaDB code.

First inspect the current MUD1 source and produce:

```text
docs/persona-storage-analysis.md
```

The document should identify:

1. every function involved in persona persistence;
2. source filenames and relevant locations;
3. the complete persona record layout;
4. the meaning of each field where determinable;
5. how BCPL strings/names are stored;
6. how persona lookup works;
7. how creation works;
8. how update/save works;
9. how deletion works;
10. locking/concurrency behaviour;
11. every call site of the persistence functions;
12. login/load sequence;
13. save/logout sequence;
14. password representation;
15. any assumptions that could make external storage difficult.

The analysis must additionally deliver:

16. every direct persona-file/block access and dependency on record offsets or buffers;
17. enumeration and administrative command coverage;
18. native transaction boundaries, save/delete preconditions and missing-record behaviour;
19. a lossless field/word representation and source-derived name equality rules;
20. ATTACH, death, SAVE and conditional QUIT persistence sequences;
21. a native-versus-external compatibility test matrix, including executable-layout-dependent authentication;
22. proposed failure, retry and backend-authority contracts;
23. explicit prototype exclusions and the work required before claiming full compatibility.

Then recommend the **smallest interception point** that would allow native persona storage to be replaced without altering MUD1 game logic.

Explain how that boundary handles callers that currently inspect `rec`/`dmpbuf` or scan blocks, and how it preserves atomic native decisions. Cross-reference the existing restoration, password-audit, provisioning and inspection findings rather than treating those questions as uninvestigated.

Do not modify source code during this task.

The immediate objective is to establish the precise abstraction boundary from the actual code rather than designing it from assumptions.

---

# 18. Non-goals for the first implementation

Do not:

- port MUD1 to another operating system;
- replace TOPS-10;
- replace TOPS-10 filesystem storage generally;
- redesign gameplay;
- redesign personas;
- redesign authentication;
- normalise the entire MUD data model;
- build a web UI;
- externalise the world database;
- expose MariaDB/SQL concepts to BCPL;
- optimise prematurely.

The first objective is simply:

**Load and save an original MUD1 persona through a storage-neutral host interface backed initially by MariaDB.**
