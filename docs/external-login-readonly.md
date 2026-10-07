# Original MUD with read-only external personas

## Verified result

The generated **external-readonly** variant now runs the original MUD engine
with login and saved-persona ATTACH records supplied by MariaDB over H1/R1.
Gameplay and password checks remain in BCPL. This is no longer only a standalone
record-reader test.

Final evidence: `runtime/external-login-verified/report.json`; generated sources
and audited diff: `build/external-login-verified/`. The disposable test renamed
the native `MUD..PM` file out of reach before external login, so native-file
fallback could not explain success.

Verified in the actual game:

- Correct/wrong-password outcomes matched a native baseline for all seven
  archwizard names and an ordinary control persona (16 comparisons).
- Richard's stored password remained rejected for direct login, as in the
  historical baseline. ATTACH from Roy rejected an unrelated password and Roy's
  password, then accepted Richard's correct password.
- The ordinary persona loaded a database score of **777**, moved from the road
  through the house to the bedroom, and used original MAKE/UNMAKE BED actions.
  Its in-memory score reached **788**. Re-entry restored **777**.
- INFO, LOOK, INVENTORY, SCORE and WHO worked. A second externally loaded player
  joined the same original shared world; WHO showed both players.
- SAVE, PASSWORD and PURGE were explicitly refused. QUIT used the original
  teardown and reported that the persona was not saved.
- Missing personas did not trigger creation. Missing bootstrap tokens and a
  paused database caused lookup failure before the password question. Login
  recovered after the database resumed.
- All MariaDB persona rows, including metadata, remained unchanged by play.
  FILCOM `/B` found the retained native persona file byte-identical to its
  pre-build snapshot. Host `source/` hashes stayed unchanged.

This completes a targeted **Phase 3 read-only login slice**, not the project's
principal load/play/save proof. There are no external writes, creation,
deletion, migration or production/browser deployment in this milestone.

Follow-up: [external-save-existing.md](external-save-existing.md) now verifies
explicit SAVE for existing personas in a separate generated mode, with durable
outcomes and lost-acknowledgement recovery. This read-only variant keeps its gates.

## Reproducible generated variant

```sh
.venv/bin/python -m tools.prepare --external-readonly --output build/mud-readonly-example
```

Use a fresh output directory. The default remains the native persona build;
`source/` is never edited. `--always-open` remains a separate optional flag and
is not required by this test, which boots during historical opening hours.

The generated variant changes:

| File | Change |
|---|---|
| `MUDLIB.BCL` | Native persona startup dependency removed; lookup returns a detached logical record; normal password/profile conversion retained; persistence routines gated; H1/R1 reader added |
| `MUD7.BCL` | SAVE/PURGE gated; ATTACH uses a logical record pointer; outbound game chaining refused before teardown |
| `MUD5.BCL` | SAVE and PASSWORD refused at command dispatch |
| `ROBOOT.MAC` | Small low-memory build marker and reserved words for controller validation |
| `ROSEED.BCL` | Private per-job challenge provisioning helper |

`local.diff`, output hashes, input hashes and `persona_storage` metadata record
the variant. Source anchors must match before preparation publishes an output
tree. Host tests compare the original authentication/profile-loading fragment
with the generated version; native authentication tests validate the relinked
executable as well.

The reader is generated from the native-tested PRREAD routines with library-local
names and without its synthetic-fixture assertions or diagnostic word output.
It stages all eleven words, validates the response/name/checksum, and only then
returns the dedicated record buffer. It does not pretend that this buffer has a
native disk offset. World-file `dmpbuf` and its block cache remain separate.

The adapter uses MUD's `findchannel()`, `hopen()` and `release()` helpers. It does
not hard-code channel 17, which is already available to MUD's ordinary file I/O.
The tested game continued reading its original world files after persona lookup.

## Fresh per-run challenge provisioning

The private controller does not put a challenge into the player's game input.
It performs the following sequence on its own monitor connection:

1. GET the configured MUD image and verify its low-memory bootstrap marker.
2. Run the separate ROSEED helper and supply a fresh random 72-bit run seed.
3. ROSEED writes two full words into the current job's **in-core TMPCOR `RSE`**
   entry and exits to the monitor.
4. GET the MUD image again, verify the marker, then START normally.
5. The game's first lookup atomically reads and deletes the TMPCOR entry.

`tools/persona_bootstrap.py` supplies the controller side. `SEEDCK.BCL` verifies
the full all-ones 72-bit value across GET/START and confirms that a second
read-delete finds no token. Native gameplay proves the same path under MUDGUEST.
No seed file is written to a guest disk. TMPCOR is job-local and does not survive
job destruction or emulator reboot.

At `initialise()`, the adapter resets its private run state. On first lookup it
consumes the token, requires a nonzero high word, and retains the run seed only
in that job's memory. Lookup number `n` derives its challenge as
`(seed_high, seed_low XOR n)`, for at most 1,024 lookups per run. This gives
distinct challenges within the run, including successive ATTACH attempts;
independently random run seeds separate runs. H1 still establishes a fresh host
epoch for every lookup. Tokens correlate/fence traffic; they do not authenticate
a player or replace the original password checks.

A new execution without an available token fails closed. An unused token may
remain in its job until consumed, replaced by the controller, or discarded with
the job; a previously used token cannot be read a second time. The controller
must remain trusted and provision fresh seeds. This is not yet integrated into
the browser gateway's login/setup sequence.

ROBOOT must be linked first with `/SET:.LOW.:140`. The controller checks octal
location `140` for `621714324560` and the following two reserved words for zero.
It does not modify these words. This marker is a build-layout check, not a
cryptographic image signature; the controller must load its trusted image path.

An earlier DEPOSIT-based experiment did not read back the requested value on
this monitor. Verification stopped it before game entry. That approach was
discarded in favor of the verified TMPCOR mechanism; the monitor behavior was
not patched or attributed to a proven underlying cause.

## Native build and game data

The acceptance harness builds only on a disposable copy of the stopped baseline.
It first creates native password fixtures and records their authentication
outcomes, then exports logical words privately using `ROEXP.BCL`.

ROEXP is deliberately limited to small, quiescent test fixtures. Its output
includes native password words and is kept only in host memory, never written
to an operator transcript or JSON report. It is not the production migration
utility or a concurrent snapshot interface.

Modified sources are copied at 100 ms per line and compiled serially. Full TYPE
output is compared against generated text, allowing terminal tab expansion and
discarded end-of-line padding. BCPL `W`-numbered diagnostics are build failures,
even when the compiler subsequently writes a REL file.

The final linked game code ended at octal `503120`. The harness places DBADAT at
`510000`, checks for code overlap, relinks the **original** DBASE compiler to the
same data base, and regenerates the world with that compiler. It reported the
original **25,247-word** database size. The engine then performs its normal
initialization/save procedure under the actual RICHARD OS account.

The resulting world files and executable belong together. Do not treat the
retained pre-build `MUDNAT.EXE` as an executable-only rollback on those regenerated
files; the historical image used a different database placement. The ordinary
native preparation path and fresh baseline remain the comparison/rollback path
for this disposable experiment.

## Read-only behavior and deliberate limits

Login and saved-persona ATTACH preserve the original password decisions and
profile conversion. The historical Richard direct-login exception and attached
profile state behavior have not been redesigned.

Persona mutation is intentionally unavailable:

- SAVE and PASSWORD stop before changing/saving persona credentials or records.
- PURGE cannot enumerate/delete a stale native file.
- Exit-time `writeprofile()` preserves its existing non-storage processing but
  reports no persistence instead of saving or deleting.
- The underlying save/add/delete routines are also gated defensively.
- Missing-record login/ATTACH does not create a persona.
- Outbound inter-game chaining is refused before teardown, avoiding a switch
  into another game's unsupported persistence path.

The original standalone POWER and native-file inspection/provisioning tools are
not external-store administration tools. The native fixture file was renamed
to `PMHOLD.PM` only on the private disk and retained for comparison. These tests
do not modify live runtime configuration, player data or the public gateway.

## Reproduction and evidence

```sh
.venv/bin/python -m pip install --require-hashes -r requirements-storage.txt
.venv/bin/python -m unittest tests.test_prepare tests.test_prepare_personas tests.test_persona_bootstrap -v
.venv/bin/python -m tests.integration_external_login
```

The native test also needs the previously installed MariaDB tools and original
runtime/compiler checkpoint. `--output runtime/<fresh-short-directory>` selects
evidence; a matching fresh directory is generated under `build/`. The copy and
compile steps take several minutes. Private database and emulator processes are
stopped on exit; no runtime release package is published.

Final run: `runtime/external-login-verified/`. It records 26 H1/R1 lookups,
authentication outcomes, score checkpoints and preservation results. Compiler
logs, DBASE output and rendered source comparisons are retained separately;
fixture passwords and exported persona words are not logged.

The final host check passed 74 preparation, bootstrap, store and transport tests.
The bootstrap tests verify that unexpected image headers are rejected before
provisioning and that the controller supplies all 72 seed bits. Native SEEDCK
and the actual-game tests provide the corresponding monitor/runtime evidence.

Earlier failed experiments remain: simultaneous connection/transfer attempts,
BCPL generator diagnostics, a rejected DEPOSIT bootstrap and unsuccessful
whole-file TECO line edits. The installed TECO paged large sources rather than
providing the assumed whole-file buffer; source comparison caught those edits
before compilation. The final harness uses the slower verified full-copy path.

## Next milestone

The subsequent existing-persona SAVE and
[eligible-exit](external-exit-existing.md) milestones verify native policy,
atomic updates and fenced recovery. The recycled-slot/header-buffer creation
experiment, deletion/death, enumeration, administration, migration and
browser/deployment integration remain separate acceptance work.
