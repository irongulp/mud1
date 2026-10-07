# Persona storage analysis

## Status and recommendation

This is the source-analysis milestone for [external-storage.md](external-storage.md),
performed on 2026-09-26. It describes the supplied `source/` implementation, not
an implemented external backend. Source references below use that directory's
line numbers, including the embedded POWER source in `MBOOTS.MAC`.

Follow-up: the standalone [storage bridge probe](storage-bridge-probe.md) has
since verified a secondary-TTY PING/PONG channel, 36-bit round trips and selected
failure/isolation cases. It has not implemented the logical-record adapter or
changed the game. Statements about tests not run below describe this analysis
milestone; the follow-up report records the new transport evidence separately.
Later [channel-pool tests](storage-channels.md) verify MUDGUEST ownership and
release, and the [R1 draft](persona-read-protocol.md) defines the read-only record
exchange. The [native R1 proof](persona-read-native.md) subsequently verified
synthetic record decoding, handover and flow control. The later
[MariaDB milestone](persona-mariadb.md) verifies a bounded database-backed getter
through that standalone reader. The [generated read-only MUD adapter](external-login-readonly.md)
verifies actual login, gameplay and re-entry. The later
[existing-persona SAVE prototype](external-save-existing.md) verifies explicit
saves and recovery. The [eligible-exit variant](external-exit-existing.md) also
verifies normal QUIT updates and skip/recovery cases. Later
[death deletion](external-death-existing.md) and
[logical persona creation](external-persona-creation.md) have native acceptance;
broader lifecycle equivalence remains pending.

**Recommended boundary: a guest-side logical record adapter below persona
policy, with explicit read/write scopes and detached record buffers.** Keep
authentication, profile conversion, save eligibility and score checks in BCPL.
Replace persona file opens, lookup/allocation/block writes and enumeration through
that adapter. Do not replace general TOPS-10 file I/O or simulate a `.PM` disk
layout in MariaDB.

Intercepting just `searchrec()`/`saverec()` is insufficient. Startup opens the
persona file, callers decode disk-relative offsets, PURGE scans blocks, and the
separate POWER maintenance program has its own implementation. These dependencies
are inventoried below.

This work is static analysis, informed by previously recorded native tests. No
new native experiment, external-storage round trip or transport feasibility test
was performed. The proposed contract and validation matrix are implementation
requirements, not claims of passing tests.

## 1. Authority, inputs and scope

- Preserve `source/` byte-for-byte. Future changes belong in generated `build/`
  trees with reproducible patches. `tools/prepare.py:67–108` copies the local
  archive, extracts embedded subfiles and applies the optional availability
  patch; it does not replace local BCPL with the differing upstream copies.
- `source/MBOOTS.MAC:189` introduces embedded `POWER.BCL`; the later DBADAT
  subfile starts at line 998. POWER is a separate maintenance program, not a
  second implementation linked into MUD's normal persona calls.
- The native defaults include `ESSEX=true`, `RELAXED=true`, `CORELOW=false`
  (`source/DUNGEN.GET:19–27`). PURGE is therefore not automatically excluded by
  the low-core conditional in `source/MUD5.BCL:250–258`.
- Persona filename `PS6` is populated from the DBASE persona declaration
  (`source/DBASE.BCL:888–895`); it is not intrinsically a hard-coded MUD name.
  The installed restoration uses `MUD..PM`: the generated extension starts with
  a dot. File calls use `ps6`, extension `.pm`, and `mainta`; several use device
  `all`, while SAVE/PURGE use `disc`.
- A backend must identify the configured persona store as well as the name.
  A proof with one instance can configure one store namespace, but must not
  accidentally merge different games or separate test disks into one table.

Existing evidence and procedures:

- [restoration.md](restoration.md): executable/data preparation and runtime.
- [archwizard-password-audit.md](archwizard-password-audit.md): authentication
  and ATTACH persistence experiments.
- [archwizard-provisioning.md](archwizard-provisioning.md): first-install
  creation, credential preservation and private fixture practice.
- [inspection.md](inspection.md): read-only saved-record snapshots and native
  ENQ contention tests.

## 2. Native file and record representation

### 2.1 Header, addressing and buffers

`source/DUNGEN.GET:773–818` defines:

| File word offset | Meaning |
|---|---|
| 0–252 | 253 hash-bucket heads |
| 253 | Not assigned a header field by this implementation; preserve on archival import |
| 254 | `DEL`: head of deleted-record/free chain |
| 255 | `FLEN`: logical next-free word offset |
| 256 onward | 12-word record slots |

An initialized file's allocated slot count is `(FLEN - 256) / 12`. Native
readers also accommodate the initial `FLEN=0` state; do not interpret it as a
negative record count. A live record is recognized by nonzero `WRD1` in scans.
Deletion does not compact the file.

`WDSPERBUF=128`, but `BUFFERS=(FULLBUFSIZE+1)/5*2=256`: the dump-mode transfer
window covers two disk blocks, allowing a 12-word record to cross a 128-word
boundary. `rec` during lookup is a file word offset. Its address in the loaded
window is `dmpbuf + rec rem 128`, and its starting disk block is `rec/128+1`.
Do not implement a one-block-only decoder by mistaking `WDSPERBUF` for the
whole transfer size.

`dmpbuf` and `cbl` are process statics (`source/MUDLIB.BCL:89–90`), also used for
other game files. `load.block()` caches by `laststream` and `lastblock`; it may
return without reading. `save.block()` writes via `laststream`, normally using
`lastblock` (`source/MUDLIB.BCL:1267–1278`). Generic command loading also touches
this cache (`source/MUDLIB.BCL:1682–1694`). New persona buffers must not disturb
world-file I/O or rely on a stale shared dump buffer.

### 2.2 Complete 12-word record map

Offsets are zero-based. Bit positions use least-significant-bit numbering;
`selector width:shift:offset` extracts that field. The authoritative declarations
are `source/DUNGEN.GET:802–815`, with profile selectors at lines 368–391 and
serialization in `source/MUDLIB.BCL:1369–1384`.

| Offset | Field / bits | Meaning and native treatment |
|---|---|---|
| 0 | `POINTR`, 36 bits | Next active record in the hash chain, or next free record when deleted. File bookkeeping, not logical persona identity. |
| 1 | `PN`, bits 18–35 | TOPS-10 programmer number. `peen` is the right half of GETPPN (`MUDLIB.BCL:2052–2055`). Written when profile game count is 1, retained otherwise. Not the current player slot. |
| 1 | `GAMES`, bits 0–17 | Persisted games played. Loaded into a full profile word; ordinary login increments it, chained entry does not. |
| 2 | `WRD1`, 36 bits | Packed name length and first four characters, plus sex in bit 0. Copied from profile word 14. Zeroed on deletion. |
| 3 | `WRD2`, 36 bits | Remaining five name characters, plus profile dormancy/asleep bit in bit 0. Copied from profile word 15. Zeroed on deletion. |
| 4 | `SCRE`, 36 bits | Score, used in native signed comparisons and arithmetic. Copied to/from profile `SCORE`. |
| 5 | `STRN`, bits 27–35 | Nine-bit strength. |
| 5 | `DXTY`, bits 18–26 | Nine-bit dexterity. |
| 5 | `STNA`, bits 9–17 | Nine-bit stamina. |
| 5 | `STMX`, bits 0–8 | Nine-bit maximum stamina. |
| 6 | `LSTM`, 36 bits | Native universal date/time word returned by GETTAB through `ud.time()`. Updated on save; used for last-game display and stamina recovery. |
| 7 | `WIZD`, 36 bits | Saved profile `STATES`, with invisibility cleared on save if the persona is not currently in wizard mode. |
| 8 | `PSWD`, 36 bits | Original password transformation result, copied from session `ps.word`. Zero triggers password assignment at login. |
| 9–11 | Unused, three 36-bit words | No logical fields declared; ordinary `dumpersona()` leaves them unchanged. Preserve as opaque data. |

Known `WIZD` bits are 0 WIZARD, 1 OPR, 2 BERSERK, 3 SNOOPBIT, 4 ATTED,
5 BREEF, 6 INVIS, 7 IGNORE and 8 ISWIZ. Preserve the remaining bits too. ISWIZ
and current WIZARD mode are distinct. `dumpersona()` also sets profile BREEF
from `brief>>1` before copying STATES.

The saved record is **not** the live player profile. Room, carried objects,
player/job number, message queues, combat state and other profile links are not
serialized here. Position/inventory persistence must not be added as a side
effect of externalizing personas.

`ud.time()` reads GETTAB table `#11`, item `#53`
(`source/MUDLIB.BCL:1520–1525`). The display treats its left half as the day and
right half as the day fraction (`source/MUDLIB.BCL:632–646`). Preserve that word;
MariaDB `updated_at` cannot replace it. Conversion to host calendar timestamps
is outside the first contract.

### 2.3 Strings, names and identity

`PACKSTRING`/`UNPACKSTRING` are supplied in `source/MUDLIB.BCL:771–807`.
They use five seven-bit bytes per word, leaving bit 0 outside the text. The
first byte is the length; the next bytes are characters. With `NAMELENGTH=9`,
a persona name occupies two words. `PACKSTRING` clears the destination words
it uses before depositing length and characters.

Native input and lookup rules:

1. Login `readusername()` accepts letters, folds ASCII uppercase to lowercase,
   truncates stored names to nine characters and consumes the remainder of the
   input. The two-argument password use additionally accepts digits
   (`source/MUDLIB.BCL:1033–1062`, `1170–1182`). Thus login `test1` reads `test`.
2. The command scanner's `read.name()` accepts letters and digits and folds
   uppercase (`source/MUD1.BCL:396–405`). ATTACH separately rejects names longer
   than nine (`source/MUD7.BCL:155–164`). A digit-containing ATTACH persona need
   not be directly expressible through the ordinary login parser.
3. There are historical name substitutions, including the conditional
   login `gail` → `gali` and ATTACH `gail` → `glai`. Keep these in BCPL, not in
   an invented universal host-side username validator.
4. `seq()` compares packed words shifted right by one, ignoring each word's
   low flag bit. It loops through `(LENGTH of s1)/5`, inclusive
   (`source/MUDLIB.BCL:1712–1715`). Packed length and trailing padding in the
   compared words participate; this is not arbitrary Unicode string equality.
5. `searchrec()` copies the name and explicitly zeros the second word for
   names of four or fewer characters, then uses
   `((!nam + 1!nam)>>1) rem 253` and follows `POINTR`
   (`source/MUDLIB.BCL:1279–1294`, `1368`). Hashing and textual identity are
   separate concerns; the external store need not reproduce bucket positions.
6. `checkname()` also rejects vocabulary collisions and existing live players
   under `name.door`, with archwizard exceptions (`source/MUDLIB.BCL:1195–1208`).
   This is live-world admission policy, not a SQL unique-key substitute.

Recommended external key: a store namespace plus a validated, canonical packed
name key with the nontext low bits removed and the unused second word normalized
for short names. For ordinary engine-produced names, decoded lowercase ASCII
with a binary comparison is equivalent; retain packed words as the authority
for conversion. On import, detect noncanonical padding, invalid lengths,
unreachable hash entries and duplicate identities rather than silently merging
them. Do not promise equivalence for corrupt/noncanonical records merely because
their displayed text matches.

### 2.4 Host representation

For the first format, retain an archival 12-word image and expose a logical
payload consisting of offsets 1–11. Word 0 is migration provenance only; the
native exporter rebuilds links. Represent raw words as unsigned values in
`0..2^36-1` (fixed 12-digit octal is also convenient for diagnostics). Decode
signed full-word values as `w` below `2^35`, otherwise `w-2^36`. Re-encoding
must preserve all 36 bits. Halfword and nine-bit fields retain their full
unsigned widths; do not clamp them to normal gameplay ranges on the host.

Use separate `format_version` and concurrency `revision` fields, and a
generation identity if revisions can restart after deletion. Decoded JSON is
a projection, not a second independently writable authority. No SQL field or
JSON serializer may truncate values to 32 bits. Password words belong in the
lossless payload, but not ordinary logs, reports or error messages.

New records need a documented initialization rule. Native `addrec()` does not
clear a recycled slot before `dumpersona()`, so unused words survive. There is
also a buffer-order hazard: `addrec()` finishes with block 1 loaded
(`source/MUDLIB.BCL:1364–1366`), but `saverec()` evaluates
`SCRE of (rec rem WDSPERBUF+dmpbuf)` before reloading the record block
(`:1298–1299`). On this creation path the source therefore points the score
check into the header buffer, not reliably at the new slot's retained score.
The player-visible consequences have not been tested natively here.

A zero-filled logical CREATE is not automatically identical for these cases.
Characterize fresh and recycled allocation before claiming exact creation
equivalence; do not silently make a physical header/buffer artefact part of
the logical storage contract or silently fix it during the storage change.

Follow-up: `runtime/native-creation-guard/` now verifies both effects using the
unmodified game. Recycled opaque words survived, and a saved first-game persona
purged mid-session either failed or succeeded in recreation depending on an
unrelated valid hash-bucket entry (observed header values 0 and 304). The subsequent
[creation contract](external-persona-creation.md) explicitly chooses logical
creation compatibility: zeroed new opaque fields, atomic create-if-absent and no
implicit recreation of a missing saved identity. It does not emulate file layout.

## 3. Persistence routines and call sites

### 3.1 Game engine

The following table inventories direct callers of the persona routines in the
game BCPL sources. POWER's independent routines are listed separately below.

| Routine / definition | Call sites and responsibility |
|---|---|
| `createprofile`, `MUDLIB.BCL:1083–1165` | `initialise`, `MUDLIB.BCL:906`: load/authenticate an existing record or initialize an unsaved persona. |
| `searchrec`, `MUDLIB.BCL:1279–1294` | `createprofile:1100`; `saverec:1296`; `deleterec:1309`; `MUD7.BCL` PURGE `:44`, ATTACH `:183`. Returns predecessor offset; found-record status is the global `rec`, not the return value. |
| `saverec`, `MUDLIB.BCL:1295–1306` | `writeprofile:1261` through a conditional function selection; explicit `save`, `MUD7.BCL:21`. Search, optional allocation, score check, serialize/write; return `rec` as success indicator. |
| `addrec`, `MUDLIB.BCL:1336–1367` | `saverec:1297` only. Allocate/reuse a physical slot and link it into the hash table. |
| `dumpersona`, `MUDLIB.BCL:1369–1384` | `saverec:1300` only. Serialize profile and session password into a record, preserving untouched fields. |
| `deleterec`, `MUDLIB.BCL:1308–1335` | `writeprofile:1261` for nonpositive stamina; PURGE at `MUD7.BCL:96`. Missing record is a no-op. |
| `writeprofile`, `MUDLIB.BCL:1209–1266` | `quit`, `MUD7.BCL:389`; exceptional `lock`, `jar`, `getmblock` recovery at `MUDLIB.BCL:1749`, `1778`, `1913`. |
| `save`, `MUD7.BCL:17–30` | SF.SAVE dispatcher, `MUD5.BCL:259–267`. Opens/locks, calls `saverec`, reports success and increments `savedp` only when nonzero. |
| `purge`, `MUD7.BCL:31–122` | SF.PURGE, `MUD5.BCL:250–258`. Single lookup or physical enumeration, password/privilege filtering and optional deletion. |
| `attach`, `MUD7.BCL:155–264` | SF.ATTACH, `MUD5.BCL:245–246`. Live-profile switch or saved-record lookup and password check. |
| `newpersona`, `MUDLIB.BCL:1183–1194` | `createprofile:1158`; missing-target ATTACH at `MUD7.BCL:236`. Initializes memory; does not allocate a disk record. |
| `setpswd` / `encrypt`, `MUDLIB.BCL:1170–1182` | Login existing/zero/new password paths at `:1110`, `1128`, `1161`; `setpswd:1176` calls `encrypt`. ATTACH calls `encrypt` at `MUD7.BCL:204`; PASSWORD calls it at `MUD5.BCL:635`, `647`, `656`. |

Direct block access inside the record implementation:

- `searchrec`: header then candidate record blocks, `:1283`, `1287`.
- `saverec`: record load/write, `:1299–1301`.
- `deleterec`: record, predecessor link, free-list header and record writes,
  `:1313–1334`.
- `addrec`: header, free slot or append, bucket update, `:1339–1366`.
- PURGE: header and sequential blocks at `MUD7.BCL:39`, `41`, `98`, `108`.
- `access()`: initializes `cbl`, checks the persona file and, on the maintenance
  first-attempt path, creates/zeros it using direct `USETO`/`OUTUUO`
  (`MUDLIB.BCL:1590–1621`). External mode must replace this persona-specific
  dependency without removing the other game-file opens.

`assign()`/`deassign()` wrap startup creation, login lookup, writeprofile,
explicit SAVE, PURGE reads/deletes and ATTACH lookup. Their definitions are at
`MUDLIB.BCL:137–161`. Native generic I/O includes `DOFILE`, `LOOKUP.ENTER`,
`CLOSEFILE`, `USETI`, `USETO`, `INUUO`, `OUTUUO`, and `IOUUO`
(`MUDLIB.BCL:237–342`, `716–725`, `808–818`); these also serve non-persona files
and must not be globally redirected.

### 3.2 Exit paths, checkpoints and non-saving cleanup

`quit()` calls `writeprofile()` after removing the player from live lists,
dropping possessions and processing remaining always-run events, but before
recycling the player slot and finishing/chaining (`source/MUD7.BCL:329–413`).
A write outage therefore occurs after substantial live-world teardown; a
host adapter cannot simply resume ordinary play at that point.

Direct `quit()` calls occur in:

- `MUD1.BCL:37`, `54`, `152`: reset, scheduled closure and control-C handling.
- `MUD2.BCL:172`, `247`: travel/action exit and inter-game chaining.
- `MUD3.BCL:342`: `checkout()` death path.
- `MUD5.BCL:140`, `150`, `197`, `732`, `840`, `1946`: command/action exits.
- `MUD6.BCL:452`, `MUD8.BCL:603`: further game-action exits.
- `MUDLIB.BCL:945`: initial-entry demo/berserker rejection.

The exact downstream persistence decision is still `writeprofile`, not a
different save implementation for each exit. `checkout()` can revive an
archwizard/authorized wizard rather than quit (`source/MUD3.BCL:301–343`).

No periodic persona autosave call was found in the supplied engine. Explicit
SAVE and the exit/recovery paths above are the persistence points. The
PASSWORD command changes `ps.word` in memory and announces a later update;
it does not itself save (`source/MUD5.BCL:623–661`). That announcement remains
subject to normal persistence eligibility.

DETACH exits to the monitor and can continue without writing a record
(`source/MUD7.BCL:265–278`). EXORCISE removes a live profile and drops its
possessions without calling persona save/delete (`source/MUD7.BCL:279–328`).
Do not add automatic persistence to these paths or assume abrupt job loss has
the same outcome as QUIT.

### 3.3 POWER maintenance program and restoration companions

The embedded POWER routines use their own record buffers and functions:

| `source/MBOOTS.MAC` range | Persona dependency |
|---|---|
| 320–345 | Interactive edit path calls `searchrec`, `addrec`, `dumpersona`, `save.block`. |
| 347–398 | POWER `dumpersona` edits record fields interactively; it is not MUD's profile serializer. |
| 400–495 | Independent `load.block`, `save.block`, `searchrec`, `saverec`, `deleterec`, `addrec`, `hashval`. `saverec` internally calls search/add/dump/write; no external caller of this POWER `saverec` was found in the subfile. |
| 496–505 | `kill` calls `deleterec`. |
| 607–622, 705–730 | File setup/creation, ENQ/DEQ. |
| 642–670 | `password` scans records by password word. |
| 732–765 | `transfer` scans and updates programmer numbers using direct block I/O. |
| 767–890 | League/enumeration and supporting tree/output routines read records. Some historical output includes password words. |
| 891–963 | `Oneoff` converts an older representation into `.OFF`, constructing hash/record blocks. It is not a general exporter for the current external schema. |

POWER `searchrec` is called from its edit path (`:323`), `saverec` (`:428`)
and `deleterec` (`:438`); `addrec` from edit (`:335`) and `saverec` (`:429`);
`dumpersona` from edit (`:331`, `341`) and `saverec` (`:432`); `deleterec` from
`kill` (`:500`). Their similar names do not prove identical semantics: for
example POWER's `saverec` lacks MUD's `savescr` check.

Modern companions also depend on native files:

- `tools/fixtures/MVPER.BCL:11–48` snapshots saved records under ENQ and omits
  password values. Its host inspection output would be stale in external mode.
- `tools/fixtures/AUDPWD.BCL:19–45` reads raw records, including passwords,
  for private audit. It does not acquire ENQ; use only a controlled coherent
  fixture/snapshot when relying on it for comparison.
- Provisioning uses original game sessions plus the audit reader, so native
  inspector results cannot certify external provisioning without adaptation.

Initial external prototypes must explicitly exclude native POWER and native-file
inspection/provisioning as authoritative tools. Full operational compatibility
needs backend-aware replacements or generated adapters. Leaving a stale `.PM`
file available is not a synchronization mechanism.

## 4. Lifecycle and native policy

### 4.1 Login and creation

`initialise()` calls `access()`, allocates a zeroed live profile and then calls
`createprofile()` (`source/MUDLIB.BCL:868–947`; `getmblock:1924–1926` clears the
profile block). Login proceeds as follows:

1. Read or inherit a chained name, run `checkname`, open `.PM`, lock, search,
   release locks and close the file.
2. If found, convert `rec` from disk offset to buffer address. Authenticate
   using PSWD; a zero PSWD asks for a new session password. Rejected login does
   not call `dumpersona`.
3. Load STATES and score; apply wizard rules. Rationalise strength, dexterity
   and stamina to the native range. Increment GAMES except for chained entry.
4. Load stamina maximum and add `(ud.time()-LSTM)/182` to stamina, then clamp
   it to the native accepted range. Copy the stored first name word to recover
   sex. The second stored name word is not copied by this load path, so saved
   dormancy is not a request to enter asleep. Display last-game time.
5. If absent, `newpersona()` sets score 0, games 1, random characteristics,
   sex and awake state; prompt for password. **No CREATE record occurs yet.**
6. Back in `initialise`, set `savescr` to score, or -1 when score is zero.

The database is not consulted on each command. A record fetched before a
password prompt is a detached snapshot; native locking is not held during user
input. Do not impose a session-long row lock.

### 4.2 SAVE, first allocation and serialization

The SF.SAVE dispatcher rejects ATTED profiles and, for non-wizards, unchanged
scores compared with `savescr`, then calls `save()`
(`source/MUD5.BCL:259–267`). `save()` opens for update and holds `assign()` over
the whole `saverec()` call.

`saverec()`:

1. Looks up the current stored record, rather than trusting the login snapshot.
2. If absent, calls `addrec()`. Allocation refuses profiles with games > 1.
   Otherwise it pops `DEL` or uses `FLEN`, initializes the header if needed,
   advances `FLEN`, and inserts the slot at the head of its hash bucket.
3. Evaluates `SCRE >= savescr` through the current buffer; otherwise it reports
   an unexpected score change and returns zero. For an existing record this is
   the stored score. For a newly allocated record, see the header-buffer hazard
   in §2.4. This is not a generic equality/revision check and not a comparison
   with the proposed new score.
4. `dumpersona()` copies the profile/session fields, stamps native time, preserves
   PN unless games = 1, and writes the record window.

An ordinary explicit SAVE at zero score is allowed for a new persona because
`savescr` starts at -1. `savedp` increments only on a nonzero return from
`saverec`. However, the SF.SAVE dispatcher assigns `savescr=SCORE` after `save()`
returns even when the record score guard returned zero. This subtle state
transition belongs in differential tests. New transport failures must take an
explicit failure path, not fall through the normal success path accidentally.

### 4.3 QUIT and deletion

Before writing, `writeprofile()` may grant wizard eligibility for crossing the
experience threshold alive. Its persistence predicate is:

```text
not ATTED
and name is neither "glai" nor "gali"
and (games > 1 or savedp != 0
     or (stamina > 0 and (chaining != 0 or score != 0)))
```

When eligible, it locks and chooses deletion if stamina <= 0, otherwise save.
A first-game zero-score persona that has never SAVEd normally leaves no saved
record. A previously SAVEd first-game persona can be deleted on death because
`savedp` makes it eligible. Keep this predicate in BCPL.

`deleterec()` searches, returns without effect when absent, zeros both name
words and GAMES, unlinks the hash-chain entry, links the slot to the old free
head and updates DEL. It retains other words, including password/score. The
ordered block writes aim to reduce crash corruption, but are not a database
transaction or proof of crash atomicity (`source/MUDLIB.BCL:1308–1335`).

The file-open error branch in `writeprofile` allows an alive player whose score
has not fallen below `oldscore` to choose to leave without updating or retry.
Otherwise it waits and retries (`:1234–1258`). Preserve the distinction in
policy; do not disguise a database outage as ordinary lock contention or claim
all native error paths already have bounded recovery.

### 4.4 ATTACH and authentication

ATTACH can switch directly to a live profile without a saved-record lookup,
or load a saved/missing target (`source/MUD7.BCL:155–264`). The saved-target
lookup releases its file locks before asking for a password. The check depends
on archwizard privileges, whether a password is set and whether it matches
the current `ps.word`; it differs from direct-login authentication.

For a saved target, ATTACH sets ATTED, then overwrites STATES from WIZD
(`:226–234`). That can clear ATTED. `ps.word` stays the attaching session's
password. Consequently attached SAVE/QUIT can overwrite the target's saved
password. This is demonstrated in the existing password audit, not merely an
inference from the SAVE guard. Copying only selected state bits to “fix” this
would change original behaviour.

`encrypt()` computes a 36-bit arithmetic result from the packed password words
using remainders modulo `(1<<20)-1` and `(1<<25)-1`, followed by multiplication
(`source/MUDLIB.BCL:1178–1182`). Preserve raw bits; do not reinterpret PSWD as
a modern password hash or recompute it on the host for ordinary storage.

The direct-login code has additional checks, including Richard's address-derived
`@name` calculation (`source/MUDLIB.BCL:1112–1123`). Native tests find ordinary
saved credentials accepted for six archwizard names but rejected for Richard;
Richard's ATTACH path is verified. Relinking or adding buffers can change the
address-derived calculation. Test the final modified executable, not only a
codec or unchanged-looking authentication source.

## 5. Concurrency and failure boundary

### 5.1 Native critical sections

`assign()` first acquires shared-world `persona.door`, then ENQs a file-associated
resource numbered **142857 decimal** on `perput`'s channel. `deassign()` DEQs,
then releases the door (`source/MUDLIB.BCL:137–161`). `PERSONA.DOOR` aliases
PDOOR (`source/DUNGEN.GET:863`); PDOOR starts at -1
(`source/DBADAT.MAC:88`). `jar`/`unjar` also affect `lockflg` and have exceptional
recovery behaviour (`source/MUDLIB.BCL:1755–1788`).

The door coordinates jobs sharing the world segment; file ENQ also coordinates
separate native file users such as maintenance/read-only tools. Previous native
inspection tests establish that ENQ waits under contention. The game wrappers
do not expose a structured success/error result. Do not infer fail-fast lock
semantics from a user-facing “someone accessing” file-open error message.

| Path | Lock scope |
|---|---|
| Login / saved ATTACH | Lookup only, released before password prompts and profile conversion |
| SAVE / eligible QUIT | Search → optional allocation → score check → serialization/write, or search → deletion |
| Startup creation | Initial file write |
| PURGE | Initial lookup/header read, each later block load and each deletion separately; not the whole interactive traversal |
| POWER | Its setup obtains file ENQ; several operations retain it across interactive work |

PURGE is not a coherent transaction-wide snapshot. It can release locks while
showing a record and reacquire them to delete by name. Replacing this with a
host snapshot is reasonable for a future contract but must be labelled and
tested as a concurrency difference, especially around deletion/recreation.

### 5.2 Recommended external transaction contract

Preserve a **short store-scoped write transaction** for the initial implementation:

1. Guest starts a write scope; host serializes participating writers to that
   persona store. Initially no external admin/POWER writes bypass this service.
2. Guest reads the current record inside that scope and evaluates the original
   BCPL existence/score conditions.
3. Guest serializes fields and stages a create/update/delete; host atomically
   commits or aborts. Release guest and host coordination in defined order.

This is a storage transaction, not a host implementation of gameplay policy.
Do not hold it across player prompts. A backend-independent service can expose
opaque BEGIN/READ/WRITE/COMMIT/ABORT tokens without exposing SQL; exact operation
names remain provisional. Native mode retains native locking under the same
guest adapter scopes. External mode cannot call ENQ on a nonexistent persona
file and must not assume `persona.door` alone coordinates different worlds.

A later alternative is a conditional write using an opaque revision from a
fresh save-time read, with re-evaluation in BCPL after conflicts. A revision
carried from login would reject updates the native code might allow. This
alternative needs its own behavioural decision and tests; it is not the initial
recommendation. The MariaDB adapter must provide the promised transaction
semantics; future backend adapters must satisfy the same contract.

### 5.3 Error outcomes and recovery

Define distinct responses for FOUND, NOT_FOUND, INVALID_RECORD, UNAVAILABLE,
REJECTED/CONFLICT, COMMITTED and UNKNOWN_OUTCOME. Each request needs framing,
protocol version, bounded size, store/session identity and a request identifier.
These are logical requirements, not a selected wire encoding.

- Read failure stops login/ATTACH with a storage error; never create on outage.
- Known pre-commit failure aborts the transaction and follows an explicit BCPL
  error path without a save acknowledgement or successful-save bookkeeping.
- Lost commit acknowledgement requires a durable operation identity/result.
  Retry/query must resolve the original outcome rather than replay a stale
  replacement after a later update or delete. Outcome tracking and mutation
  need a shared atomic durability boundary.
- Timeout or disconnected guest expires/aborts an uncommitted host scope and
  fences late operations. A timeout after commit remains an ambiguous result
  until resolved. Tokens cannot be reused by a later guest job.
- No unbounded host transaction may outlive a dead session. Guest cleanup must
  release `persona.door`/related state on every bridge error without allowing
  `jar`'s exceptional path to recursively wait on its own write scope.
- QUIT has already torn down live state when writing. On failure it needs a
  bounded persistence-resolution/exit path with an honest result, not an
  attempted return to the ordinary command loop.

This improves failure specification where native dump-mode operations are weak:
`load.block()` and `save.block()` do not check the boolean return from
`INUUO`/`OUTUUO`. Do not claim the new durable-commit acknowledgement reproduces
all native I/O error behaviour exactly. Successful gameplay policy should stay
unchanged; newly specified transport failures are an explicit extension.

## 6. Interception options and affected files

| Option | Assessment |
|---|---|
| Redirect TOPS-10 file/block operations | Retains physical layout and potentially other users, but becomes a filesystem/device project and exposes unrelated I/O. Reject for this milestone. |
| Replace four record functions and emulate `rec`/`dmpbuf` | Small initial patch, but startup and PURGE still access `.PM`; callers require physical offsets; shared-buffer side effects remain. Useful only as a narrowly labelled spike, not the architecture. |
| Guest logical-record adapter with scoped operations | **Recommended.** Slightly more caller adaptation, but storage-neutral records, explicit lifetime and complete inventory of persona-only dependencies. |

The adapter should return a dedicated 12-word-compatible guest scratch record
(word 0 has no backend identity meaning) or an explicit not-found/error result.
Keep the original selectors and profile conversion. Login's `writeudate()`
currently reads global `rec`; adjust that pointer deliberately or pass the
detached record explicitly. Do not fabricate a disk offset to retain
`rec rem 128+dmpbuf` expressions.

The first generated patch is expected to touch:

- `MUDLIB.BCL`: persona startup availability check; lookup/load callers;
  native/external record scopes and adapter; save/delete plumbing; detached
  record lifetime. Keep `dumpersona`, authentication, name checks and
  `writeprofile` eligibility policy semantically intact.
- `MUD7.BCL`: SAVE open/lock plumbing, ATTACH record access, and PURGE lookup/
  enumeration adaptation or explicit prototype exclusion before opening `.PM`.
- `MUDLIB.GET`: declarations for any cross-module adapter functions/buffers.
- Generated build/link preparation: deterministic backend selection and patches.
  Do not grow or reorder the shared world layout casually; no DBASE change is
  justified merely to store personas externally.

`MUD5.BCL` SAVE bookkeeping should initially remain the native policy; test its
zero-return edge case. Change it only if a new error path requires a reviewed
adaptation. POWER and host inspection tooling are follow-up consumers, not
implicitly covered by changing `MUDLIB`.

The smallest useful vertical slice is a read-only external lookup for one
validated fixture, with a generated backend selection and clear rejection of
unsupported mutation/enumeration paths. Then implement updates for existing
records. Creation/deletion and full command coverage follow. A read-only
prototype must not silently write back to `.PM` on QUIT.

## 7. Compatibility and acceptance matrix

Run equivalent fixtures on separate disposable native/external instances with
the same build switches and controlled guest clock. Record visible outcomes,
all logical record words and live/session effects where relevant. Physical hash
chains, free-slot placement and database timestamps are not logical equality
criteria. Compare unknown words and flag bits explicitly. Never print test
passwords in public transcripts.

| Area | Required scenarios and assertions |
|---|---|
| Codec | Zero, bit 35, all 36 bits set, signed score values, halfword/nine-bit boundaries, all name lengths 1–9, both low name flags, unknown STATES bits and words 9–11; exact round trips. |
| File import | Empty/zero header, hash collisions, deleted/free slots, records crossing 128-word boundaries, corrupt length/links, duplicate/canonical-name anomalies; no silent repair or merge. |
| Login | Existing and absent name, uppercase, login digits versus ATTACH digits, name substitutions, vocabulary/live-name rejection, zero password, wrong password, games increment and chained non-increment. |
| Profile load | Rationalisation, zero/positive/negative native time differences, stamina cap, sex, awake entry, saved state/wizard rules, native last-game display. |
| Authentication | Ordinary control plus all seven archwizard names; native Richard direct-login rejection and ATTACH success; wrong/matching/different-password ATTACH; re-run after final relink. |
| Creation | New zero-score QUIT absent; explicit SAVE creates; nonzero-score QUIT creates; missing games>1 record refuses recreation; fresh/recycled allocation, header-buffer score guard and retained opaque words. |
| SAVE | Unchanged-score rejection, wizard exception, stored score below/equal/above `savescr`, preserved PN/unused words, first-game PN update, BREEF/INVIS conversion, `savedp` and failed-save `savescr` behaviour. |
| QUIT/death | Saved versus unsaved first game, games>1, zero/nonzero score, chained exit, nonpositive stamina deletion, privileged revival, excluded names, ATTED gate. |
| Password changes | Change in memory then eligible SAVE/QUIT, skipped persistence, wrong/confirmation-mismatch inputs; compare exact PSWD without authentication redesign. |
| ATTACH | Live target, saved target, missing target; state overwrite, password retention and attached SAVE/QUIT write effects; no assumed protection from ATTED. |
| PURGE/admin | Single lookup and enumerate-all, native password/privilege filtering, interactive finish/save/delete, concurrent mutation semantics; POWER explicitly excluded until adapted. |
| Other exits | DETACH/CONT, EXORCISE, scheduled/reset/control-C exit, abnormal job loss and recovery paths; do not invent autosave. |
| Concurrency | Two independent TOPS-10 jobs/worlds using one store, simultaneous first saves, save/delete races, score-check critical section, stale generation after delete/recreate; no session-long lock. |
| Faults | Unavailable lookup, malformed/truncated response, request mix-up, failure before commit, lost commit reply, duplicate retry, host restart, guest death while locked, delayed fenced request and honest QUIT failure. |
| Durability | Successful save survives service/database/emulator restart; acknowledged commit is distinguishable from unknown outcome; idempotency survives service restart. |
| Authority | External mode works without an authoritative `.PM`, no native fallback or dual writes; native mode remains usable; external inspection cannot report stale native state as current. |

For the principal existing-persona save milestone, codec, login/authentication,
SAVE/QUIT, durability and the relevant failure/locking cases are mandatory.
Creation, deletion, enumeration and maintenance cases gate the broader claim of
complete persona compatibility. Prototype exclusions must be enforced rather
than allowed to execute against a stale native file.

## 8. Migration, rollback and remaining decisions

**Later policy decision:** migration is supported only from native to external.
The original bidirectional requirements below describe the initial analysis, not
the adopted scope. [One-way migration and external recovery](persona-migration.md)
now provides verified import and whole-database backup/restore. There is no
supported external-to-native conversion; a retained native snapshot is historical
state, not a way to preserve later external progress. Fully native builds remain
supported independently.

Import/export uses a quiescent or coherently locked snapshot. Keep original
header/slot metadata as private provenance, but store active logical identities
separately from deleted slots. Native export must rebuild header, chains and
free-list consistently, then prove the resulting file through native login,
SAVE, deletion and enumeration. Verification includes all persisted bits,
including PSWD and opaque words, without including secrets in normal reports.

Select one authoritative backend before starting each instance. There is no
automatic fallback or implied dual-write. Returning a disposable experiment to
its initial disk is easy; preserving external progress on rollback requires a
verified export and a stopped/coordinated cutover. Existing backups of `.PM`
alone are not backups of externally saved personas.

Open decisions before implementation acceptance:

1. **Transport feasibility:** inspect the pinned SIMH/TOPS-10 environment and
   prove PING/PONG from a standalone guest program on a disposable disk. No
   network/device/host-call mechanism is selected by this analysis.
2. **Buffer/address compatibility:** design guest scratch allocation and compare
   link maps; re-run authentication on the actual patched executable. An
   unchanged source expression can behave differently after relinking.
3. **Creation fidelity:** characterize the post-`addrec` header-buffer score
   check and retained recycled-slot words. Decide explicitly which
   physical-artifact behaviours must be retained versus recorded as a limited
   compatibility difference.
4. **Enumeration fidelity:** define ordering and concurrent mutation behaviour
   before supporting PURGE-all. Native slot order is observable and snapshot
   semantics are not identical to its unlocked interactive traversal.
5. **Failure integration:** prove bounded cleanup in the native guest, especially
   QUIT teardown and exceptional memory/door recovery. A host timeout alone
   does not prove guest locks or jobs were released.
6. **Maintenance consumers:** select which POWER operations and inspection/
   provisioning tools are required for operational cutover; adapt or explicitly
   retire their native-file paths for external instances.

The next milestone recommended by this analysis was standalone bridge
feasibility, framing, 36-bit round trips and multi-job/failure isolation. The
[follow-up probe](storage-bridge-probe.md) now records those transport results
and subsequent [native record tests](persona-read-native.md). The remaining
boundary, after the [bounded database getter](persona-mariadb.md) and
[read-only game integration](external-login-readonly.md), is compatible external
persistence and its failure/transaction semantics.

## 9. Validation of this analysis

The source trace covered the persona routines and their direct call sites,
all `.pm` opens found in the supplied engine, shared-buffer accesses, embedded
POWER paths, and the existing inspection/audit companions. Source-linked
behaviour above is static evidence unless explicitly attributed to the earlier
native audits. Proposed tests have not been executed as part of this document.

No game/runtime source or disk was changed. This documentation milestone does
not claim that the bridge exists, that a particular backend can preserve every
native edge case, or that public deployment is ready.
