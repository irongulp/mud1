# MUD86 restoration

## Purpose and constraints

- Licensing: independently authored restoration software is GPL-3.0-only, scoped
  by root LICENSE; COPYING is verbatim pinned GNU text. Original MUD/source/data
  retain upstream custom not-for-profit notices. Never add that restriction to
  the GPL host/browser code or treat the whole historical image as GPL-licensed.
  See THIRD_PARTY.md and docs/licensing.md. TOPS-10/DEC and Essex BCPL runtime
  redistribution permissions remain unverified. The maintainer explicitly chose
  to keep runtime-v1 public with a prominent review notice; do not publish a
  replacement historical binary as though notices alone resolve permission.
  Local format-2 runtime packages include checksummed NOTICES.txt; installers
  retain format-1 compatibility and never replace existing mutable game disks.
  Installed apps include licence files and setup source. Browser legal links
  expose only whitelisted documents, and xterm 5.5.0 preferred-form source is
  bundled under web/vendor/ with its MIT notice and pinned source provenance.

- Serve the supplied original MUD86 BCPL/MACRO-10 engine with a browser terminal.
- Preserve `source/` byte-for-byte. Generate into `build/`; use the original
  DBASE compiler for authoritative game data. Do not reimplement gameplay in JS.
- A fully native build must remain supported, including `--always-open` alone:
  original TOPS-10 persistence with only the schedule change. MariaDB and all
  later external persistence are opt-in, never dependencies of native builds.
- Supported migration is one-way native -> external. External -> native conversion
  is deliberately unsupported; retain native snapshots as historical recovery
  points, not rollback preserving external progress. External recovery uses whole
  database backups, including journals/additional data, and fresh guest sessions.
- Use plan/red/green/blue for nontrivial changes. Host unit tests use unittest.
- No delegation/subagents unless the user explicitly asks.

## Current working system

- macOS arm64; Python 3.9 virtual environment at `.venv`.
- SIMH revision `47b7ddabbe5b548cfc32f2fd45f7bed238ff7921`, `upstream/simh/BIN/pdp10`.
- TOPS-10 7.04 disk: `runtime/disks/tops10-704.dsk`.
- **Boot via the original tape and `/tm02`**, as in `tools/boot.py` and
  `config/pdp10.ini`. Custom disk-boot monitor cold starts failed/stalled; avoid
  switching to SYS2/SYS3 without investigating. Tape boot has passed browser tests.
- A full local operator transcript is in `runtime/console.log`. It is diagnostic
  material, not a clean installation script; it includes failed experiments.
- The original executable and generated data are in `[2011,2776]`. Ordinary
  browser connections use MUDGUEST `[2653,2653]` and its auto-start program.
- `tools/serve.py` starts the gateway on loopback :8080. Emulated Telnet :2020.
- `tools/console.py` is a local Unix-socket/PTY operator aid, never public-facing.
- The live executable has a local 24/7 availability patch; historical `HOURS`
  output is preserved. Reproduce with `tools/prepare.py --always-open --output
  build/mud86-always-open` on a fresh output path. Default preparation remains
  historical. The repeatable boot clock still starts Friday 03:00.
- Read `docs/restoration.md` for media hashes, build commands and limitations.

## Important findings

- External persona storage remains a proposal; its source-analysis milestone is
  in `docs/persona-storage-analysis.md`. The recommended boundary is a guest-side
  logical-record adapter, not generic disk I/O. Startup `access()` opens/creates
  `.PM`, PURGE scans blocks, and embedded POWER has independent readers/writers;
  changing `searchrec`/`saverec` alone is insufficient. PN is the TOPS-10 programmer
  number, not the player slot. Native `addrec` retains recycled-slot contents and
  ends with the header loaded; `saverec` checks SCRE through that buffer before
  reloading the record. Creation equivalence needs a native edge-case experiment.
  No backend implementation or native storage-equivalence tests were performed
  for that analysis. The later transport-only probe is described below.

- `tests.integration_storage_bridge` now verifies a standalone BCPL secondary-TTY
  PING/PONG probe on disposable disks (NOIDLE / 5M / SPEED=*8). BRGP uses TRMOP
  against an assigned SLAVE line, separate from its controlling TTY. Per-line
  raw loopback listeners reserve DZ 6/7 outside the ordinary pool; this PDP-10
  target has 32 DZ lines, not eight. Bootstrap with a CR/echoed CRLF, then force
  monitor-level NO ECHO: program echo suppression alone leaked partial replies.
  Host responses use a single CR; CRLF introduces an extra input terminator.
  Native decoding passed all 36 bits, malformed/stale/wrong-word rejection,
  ~5-second partial/silent/disconnect timeouts, reconnect and two simultaneous
  jobs on separate lines. FILCOM verified persona bytes unchanged. Final evidence
  is runtime/storage-bridge-decode-green; earlier red runs remain. Ten host tests
  cover framing/identity/deadlines. See docs/storage-bridge-probe.md. This initial
  probe predates the MUDGUEST pool/read-protocol work below; neither milestone
  implements a persona adapter or database service.

- `tests.integration_storage_channels` verifies MUDGUEST [2653,2653] can claim
  SLAVE terminals with native OPEN, use TRMOP and explicitly RELEASE them. A
  two-member pool on DZ 6/7 gives prompt NO_CHANNEL on exhaustion; same-PPN jobs
  cannot read/write/set another job's terminal (TRMOP error 1). Concurrent claims,
  fallback, timeout release and Ctrl-C/KJOB recovery passed. Final evidence:
  runtime/storage-channels-permissions-green; the original twelve bridge cases
  also passed under runtime/storage-channels-bridge-regression. OPEN's argument
  vector needs `$move ac,args; $open #17,0(ac)`, not the stack slot `args`.
  BRGP diagnostic modes 8/9/10 are auto/hold/foreign-access; its fixed channel 17
  is fixture-only, not suitable for MUD's already-open file channels. Operator
  socket bootstrap is still needed; OPEN/RELEASE does not fence old host replies.
  See docs/storage-channels.md. `tools/persona_protocol.py` defines host-only R1
  GET/FOUND/NOT_FOUND/UNAVAILABLE/INVALID_RECORD framing for native offsets 1–11,
  with a 72-bit epoch, 36-bit sequence, ordered words and final XOR check. Eighteen
  R1 plus ten B1 tests passed at that milestone. See docs/persona-read-protocol.md;
  the later native R1 transport proof is below. No actual MUD/database adapter or
  external persona lookup has been claimed.

- `tests.integration_persona_read` verifies PRREAD's H1/R1 synthetic-record reader
  under MUDGUEST. A fresh 72-bit controller challenge binds a fresh host epoch;
  HELLO/OFFER/ACCEPT/READY precede one GET. One response frame per ACK avoids an
  ~800-byte typeahead burst. Native code stages all 11 words, checks identity,
  order, checksum and packed name, then publishes; errors assert UNPUBLISHED.
  23 completed native cases passed, including two jobs, killed-owner same-socket
  handover with old OFFER/READY/WORD injection, responder restart, clean KSYS and
  same-disk reboot with old-handshake replay. FILCOM passed before/after reboot;
  source hashes stayed unchanged. Evidence: runtime/persona-read-verified.
  42 host tests cover B1/R1/H1 and sockets. See docs/persona-read-native.md.
  Fast fault-test reconnects exposed SIMH busy responses and a brief NO_CHANNEL;
  the harness bounds only those pre-protocol retries, never failed-read retries.
  All final calls claimed on the first attempt. Challenge provisioning is still
  via the private controller, channel 17 is fixture-only, and the getter is an
  in-memory fixture at that milestone. The later database getter is below;
  actual MUD integration remains pending.

- `tests.integration_persona_mariadb --native` verifies actual MariaDB records
  through unchanged PRREAD under MUDGUEST. Evidence: runtime/persona-mariadb-verified
  (MariaDB 12.2.2, PyMySQL 1.2.3, Python 3.9): 16 native calls and 59 host tests
  passed. Stored malformed/oversized/null/wrong-name/unknown-format rows return
  INVALID_RECORD; lock, pause, revoked SELECT and stopped DB return UNAVAILABLE,
  never NOT_FOUND. Restart and two concurrent reads passed. Persona-table rows
  including metadata, native .PM bytes and original source hashes stayed unchanged.
  `isolated_mariadb()` uses a SELECT-only adapter in one subprocess per lookup:
  1.5s parent deadline, 0.25s reap allowance, two slots, bounded pipes; un-reaped
  workers retain slots. Check closure/deadline again before publication, even
  after successful worker exit. Driver/socket timeouts alone are insufficient.
  SQL bounds payloads to 512 bytes and two rows; namespace + canonical 9-byte
  packed name is the key, JSON holds native offsets 1–11. Revision is metadata,
  not implemented write concurrency. Optional requirements-storage.txt pins the
  MIT PyMySQL wheel/source hashes. Tests own a 0700, Unix-socket-only MariaDB
  directory and process, never a system service. See docs/persona-mariadb.md.
  Actual game integration is described below; external SAVE remains pending.
  The first native attempt's three OPR boot stalls are retained.

- `tools.prepare --external-readonly` generates a real MUD login/ATTACH adapter;
  the default stays native and `source/` is unchanged. `tests.integration_external_login`
  passed with MUD..PM renamed out of reach: 16 native-vs-external password
  comparisons across all archwizards plus Extguest, Richard's known direct-login
  rejection, wrong/Roy/correct ATTACH passwords, INFO/world access, movement,
  original scoring (777 -> 788), two players sharing WHO, re-entry restoring 777,
  missing persona/token and database outage/recovery. SAVE/PASSWORD/PURGE,
  exit-time persistence and outbound chaining are explicitly gated. SQL rows and
  retained native persona bytes stayed unchanged. Evidence: runtime/external-login-verified;
  generated diff/provenance: build/external-login-verified. See docs/external-login-readonly.md.
  The reader uses MUD's FINDCHANNEL/HOPEN/RELEASE and a detached record buffer.
  ROSEED supplies two full words through job-local in-core TMPCOR RSE; the game
  atomically reads/deletes them, derives per-lookup challenges with a bounded
  XOR counter, and resets private seed state at initialise(). SEEDCK verified
  all 72 bits across GET/START and second-read absence. No persistent token file.
  The private controller verifies ROBOOT at low 140 (linked first), then runs
  ROSEED, GETs the image and STARTs it. Monitor DEPOSIT did not read back the
  requested value in the discarded experiment; do not use that bootstrap path.
  Game code ended at 503120; game and original DBASE were relinked with DBADAT
  at 510000, and original DBASE regenerated 25247 words. MUDNAT.EXE alone is not
  a rollback on the new-address world files. Serial 100ms-per-line COPY plus full
  TYPE comparison passed; whole-file TECO line editing failed due partial buffers.
  Treat BCPL W-numbered diagnostics as build failures. In code generation `_`
  is assignment, not an identifier character; append AND routines before the
  library's final top-level assembler block. Native ROEXP is a private quiescent
  fixture export containing password words, never a logged/public inspector.
  Browser/bootstrap deployment, writes, creation equivalence and migration remain.

- `tools.prepare --external-save-existing` is a separate explicit-SAVE-only
  variant. `tests.integration_external_save` passed original-game SAVE/re-entry
  (score 11), native field comparisons except time, 16 authentication comparisons,
  unchanged-score/score-guard rejection and native-equivalent attached Richard
  SAVE (including its password overwrite). Evidence: runtime/external-save-verified;
  prepared code: build/external-save-verified. Code ended 504421; DBADAT/DBASE were
  linked at 520000. Automatic QUIT persistence, creation/deletion, PASSWORD,
  PURGE and outbound chaining remain gated. See docs/external-save-existing.md.
  W1 snapshots a fresh save-time record; BCPL checks SCRE >= savescr and uses
  unchanged dumpersona(). SQL compares generation/revision/all old words, with
  up to three native re-read/recheck retries on CONFLICT. Generation must be
  freshly assigned on recreation. Operation ids are independent of transport
  epochs. The proposal is durably bound before the persona transaction; mutation
  and terminal outcome commit together. RESOLVE locks the journal identity and
  aborts/fences OPEN or absent operations; it is NOT a passive status query.
  Lost reply plus DB restart resolved without a second update; an outage retained
  UNKNOWN and blocked new saves/ATTACH until recovery. Recovery bookkeeping uses
  the serialized checkpoint score, not later gameplay. W1 COMMIT checks an upload
  XOR checksum before reaching the store. Bounded workers carry no bridge socket.
  tests.integration_persona_writes passed replay, stale/generation conflict,
  immutable-intent and commit/resolve races at runtime/persona-writes-verified.
  The native write harness has a 0600 private-fixtures.json containing disposable
  credentials/control records; never publish it as an operator report. Native
  persona bytes and source hashes remain unchanged by external saves.

- `tools.prepare --external-exit-existing` adds eligible alive-persona updates
  from original writeprofile(), leaving the native predicate/promotion prefix
  intact. Explicit-SAVE-only and read-only modes retain their prior gates.
  tests.integration_external_exit passed 13 scenarios and 16 auth comparisons:
  ordinary/idle QUIT matched native fields except time; Gali and zero-score
  one-game Richard ATTACH skipped, while a prior Roy SAVE qualified attached
  QUIT with native password/PN effects. Lost exit replies resolved once; new or
  prior UNKNOWN outcomes closed at the monitor without another write. Aborted
  pending SAVE did not invent savedp; confirmed pending SAVE used its frozen
  score before persisting later gameplay. Score guard and ISWIZ promotion passed.
  WREXIT helpers never call error()/quit() or jump to mainloop after teardown;
  output is restored to TTY before storage. Deletion is still gated, not a dead
  profile update. Evidence: runtime/external-exit-verified; build likewise named.
  Code ended 504712; DBADAT/DBASE remain at 520000. Native persona bytes/source
  hashes stayed unchanged. See docs/external-exit-existing.md. Arbitrary
  disconnect/recovery paths, death/deletion, creation and deployment remain.

- `tools.prepare --external-death-existing` adds eligible STAMINA<=0 deletion.
  `tests.integration_external_death` passed twelve cases, four native FOD controls
  and sixteen auth comparisons at runtime/external-death-acceptance. Ordinary
  death deletes; Gali and unsaved one-game ATTACH skip; prior/confirmed SAVE
  qualifies attached death, aborted pending SAVE does not. Lost replies resolve
  once; unresolved SAVE blocks deletion; outages report unconfirmed/UNKNOWN and
  close without deferred writes. Missing row is a no-op; changed generation is
  CONFLICT without retry. W1 DSTART/credited snapshot/DELETE is explicitly opt-in.
  Journal kind binds UPDATE vs DELETE; deletion plus outcome is atomic, fenced
  by generation captured at operation start (not login), without SAVE score or
  revision guard. Real SQL races/replay/restart passed at runtime/persona-deletes-acceptance;
  SAVE regression passed at runtime/persona-writes-delete-regression; 96 host tests
  passed. Source and retained native .PM bytes unchanged. Code ends 505053;
  DBADAT remains 520000. See docs/external-death-existing.md. The new journal kind
  is in the fresh fixture schema, not a deployed-database migration. Creation,
  PURGE, PASSWORD and deployment remain gated/pending. A.DEATH/F.DEAD narration
  need not mean STAMINA<=0: FOD against an ordinary player is the verified path.
  Native GAMES is RH of logical word 1, not a full word at offset 5. The audit
  Guest.attach helper expects an archwizard prompt; ordinary ATTACH uses `\n*`.
  Earlier extended harness failures remain under external-death-verified/final.

- `--external-creation` now enables logical new-persona creation through original
  BCPL, verified at runtime/external-creation-reboot (11 cases, 16 auth comparisons,
  four native control scenarios, FILCOM/source preservation, clean KSYS/reboot).
  SQL creation/races/replay/restart/failed-intent passed at runtime/persona-creates-final;
  UPDATE/DELETE regressions are persona-writes-creation-regression and
  persona-deletes-creation-regression. 105 host tests passed. See
  docs/external-persona-creation.md. Code ends 505253; DBADAT stays 520000.
  Character creation remains in BCPL; login alone does not persist. W1 CSTART
  returns a credited zeroed logical template, then original dumpersona()/PUT/
  checksummed COMMIT inserts if absent, with a fresh generation and immutable
  CREATE journal intent. No upsert or conflict-to-UPDATE fallback. Job-local
  WRCREATE tracks new admissions; committed SAVE/recovery retires that authority,
  so a missing saved record is not implicitly recreated. New ATTACH retains ATTED:
  native SAVE rejects it and QUIT skips. Cross-job unsaved-live ATTACH creation
  authority remains outside this milestone. PASSWORD/PURGE/deployment still pending.
  Native allocation characterization at runtime/native-creation-guard proved
  retained recycled opaque words and the header-buffer score bug: a saved first-game
  persona purged mid-session failed recreation with header 0 but succeeded when
  an unrelated hash entry made it 304. Following the relational-storage discussion,
  external creation deliberately does not emulate those physical artifacts: new
  opaque words zero, no header score check; existing opaque words remain preserved.
  Earlier build/TTY/debug failures remain. The final harness removes unnecessary
  world resets and cleanly reboots after compiling; exact causes of earlier
  pre-LOGIN/GET stalls are not established. PMEDGE is a destructive disposable-test
  fixture, never a live inspector. Its report excludes passwords.

- `--external-admin` adds in-game PASSWORD and PURGE. Native acceptance at
  runtime/external-admin-final passed 14 scenarios and 16 auth comparisons,
  original PASSWORD/PURGE controls, FILCOM/source preservation and clean KSYS/reboot.
  115 host tests passed; SQL admin evidence is persona-admin-verified, and existing
  UPDATE/DELETE/CREATE regressions are persona-{writes,deletes,creates}-admin-regression.
  See docs/external-persona-admin.md. Code ends 506445; DBADAT stays 520000.
  PASSWORD retains its original once-per-game attempt rule and changes ps.word
  only; normal SAVE/eligible QUIT persists it. Pending SAVE/PURGE blocks new
  password transitions. PURGE retains original password/us(me)/WIZARD policy
  and Save (keep)/Delete/Finish menu. PSTART binds a view; NSTART/NEXT/NAME/FETCH
  performs live canonical-key traversal, not a frozen whole-table snapshot.
  The 2048-record bound reports incomplete listing; admin challenge budget is
  8192. Views release the bridge before human input; a six-second menu delay passed.
  PDELETE confirms the original journal operation on a fresh transport, comparing
  generation/revision/all displayed words. Changed records conflict without retry.
  Journal kinds PURGE/PNEXT and cursor_key require the fresh fixture schema, not
  a deployed migration. Never route these through generation-only death DELETE.
  PURGE pending state is separate from SAVE; resolution does not invent savedp.
  A recovery-only PURGE return must flush() or MUD reprocesses the same command.
  A known abort/conflict clears uncertainty and must permit own eligible QUIT;
  UNKNOWN closes without another write. Native regressions caught both mistakes.
  Original PURGE sex display uses rec!1's low bit (games), not the name's sex bit;
  it remains unchanged. POWER is standalone (/RUNAME:power in MBOOTS.MAC:209)
  and explicitly outside this milestone, as are external SSH inspectors and
  deployment/migration. Earlier failures and private admin-debug evidence remain.

- `--external-lifecycle` replaces job-local creation names with shared lifetime
  state (`WRLIFE.BCL`, `XLSTATE.MAC`, 36 seven-word slots outside DBADAT). Compile
  MUD3 as well as MUDLIB/7/5 and link XLSTATE before DBADAT. Fresh allocation and
  retirement tag/invalidate slots; live ATTACH selects the shared lifetime.
  Password/savedp/savescr remain job-local. First CREATE's operation id is shared;
  another job can resolve a stopped creator without crediting its SAVE as its own.
  Metadata locks hold no bridge round trip. Normal pending-create wait is 12s,
  total preparation bound 15s. Native cross-job controls: native-crossjob-first.
  The game command is DET, not DETACH. DET/CONT, EXORCISE and slot-reuse guards
  prevent stale sessions from persisting a replacement profile.
  `--chain-target mud --chain-target valley` explicitly enables compatible-image,
  same-namespace handover. It uses a 13-word read-delete in-core TMPCOR XCH packet,
  preserving context and the bridge seed/counter across RUN; no legacy ASCII
  handover compatibility is claimed. Source checkpoint failure blocks destination
  launch. Original native chaining controls rejected handover; independent CHAINCK
  validated the outgoing frame, and the VEC-alias suspicion was disproved.
  Opted-in MBOOTS normalizes RUN lookup pointer 77 (device at 77, PPN at 101),
  retaining its old 75/77 path. New world data need read protection <055>.
  Valley in this test is a DBASE-compiled MUD clone, not recovered historical data.
  Final evidence external-lifecycle-green: 15 cases, 16 auth comparisons, 102
  unique HELLO challenges, FILCOM/source preservation; 142 host tests passed.
  Real gateway cleanup passed ordinary/lost-reply/PASSWORD/PURGE/creation-question
  states via its existing cleanup function. SIGKILL guest loss restored confirmed
  score 0, not unsaved 11, on a fresh stopped-image copy against the same DB.
  New private ports avoid SIGKILL TIME_WAIT; production bootstrap/restart remains.
  Code/shared state end 510047, DBADAT stays 520000 and DBASE total 25247.
  See docs/external-persona-lifecycle.md. Rare native lock/memory failure callbacks
  and exhaustive cross-job/interruption combinations remain unverified. Keep
  earlier native-chain/lifecycle failures and private debug evidence. Narrow TECO
  N/EX edits worked for the world headers/portal with complete rendered comparison;
  RUN DBASE -valley selects VALLEY.TXT. Do not revive the failed live tape swap.

- One-way migration tooling: tools.capture_personas / PMSNAP.BCL captures full
  native header/slots under original file-associated ENQ 142857, DEQs before output.
  Capture includes password words: never transcript it. NativeSnapshot validates
  canonical hash reachability, free chains, cycles/duplicates/unreferenced slots,
  all 36 bits; max 8192 slots. Private checksum archives publish atomically at 0600.
  tools.persona_migrate imports only active logical words into an unused namespace,
  assigning fresh generations/revision 1; all rows and read-back-verified receipt
  commit together. Identical retry consults receipt only, never resurrects deleted
  personas; explicit verify compares current records before admission. init-schema
  requires empty DB, is DDL/nontransactional, not an upgrade/repair command.
  tools.persona_backup captures entire selected MariaDB DB including extra tables,
  views/routines/triggers/events; not server users/grants/config/disks. Private SQL
  bundle, bounded dumper, schema/row fingerprints. Stop writers/DDL for cutover;
  backup also holds table/view READ locks. Restore to same DB name on isolated
  recovery instance with scheduler off; no overwrite of changed/occupied targets.
  Fingerprint verification then fences INIT/OPEN journals to ABORTED under WRITE
  locks; fresh guests only. Trusted SQL archives only; checksum is not a signature.
  SQL restore/DDL can be partial on failure: use fresh empty target, no auto repair.
  Evidence migration-final, backup-acceptance, migration-native-final: 129 host
  tests; eight native personas/one deleted slot, 16 imported plus 16 restored auth
  comparisons, FILCOM/source preservation and KSYS. Native capture from
  migration-native-verified matched ROEXP; its later fresh-build source transfer
  timed out. Acceptance explicitly copied stopped external-lifecycle-green image,
  not claiming fresh build success. Earlier failures remain. See docs/persona-migration.md.
  No actual live cutover/deployment performed; native builds remain independent.

- `tools.serve_external` is a foreground loopback browser lab at :8081, default
  private persistent state runtime/external-local. Copies stopped verified image
  external-lifecycle-green/machine-1 once; subsequent starts retain disk and DB.
  Uses verified test runtime/database helpers, not the systemd installer. Empty
  external personas; retained native fixture records are not imported. Roy can
  be created/SAVEd with a user-chosen password for PURGE testing. Source image
  retains original schedule (Friday 03:00 boot), not an always-open rebuild.
  Optional gateway session_bootstrap runs server.external_bootstrap: stop initial
  MUDGUEST autostart at name prompt, examine ROBOOT, ROSEED fresh 72-bit token,
  GET/check/START, expose only new intro. Whole 30s bound; failures normal KJOB
  cleanup. Native gateway remains default. State lock, private config/db/disk,
  separate ports and readiness metadata. Shutdown cleans browsers with bridge/DB
  alive, then KSYS/DB stop. Idle bridge timeouts retire owner and permit fresh H1;
  dead workers stop the lab. Bounded three startup retries, never failed-read retries.
  Chromium evidence runtime/external-local-password: create/SAVE/PASSWORD/masking,
  full launcher/DB/guest restart and changed-password re-entry (live GAMES=2).
  35 host bootstrap/launcher/gateway tests passed. Stored GAMES updates on SAVE/QUIT,
  not login. See docs/external-local.md. Production deployment remains separate.

- Persona storage format 2 is authoritative named columns, defined by
  tools.persona_columns.ColumnPersona/table_ddl(); R1/W1 wire version stays 1.
  Score is signed 36-bit; PN/games/native-time halves are 18-bit, attributes 9-bit.
  Known STATES bits are individual booleans; unknown_state_bits retains high bits,
  plus password_word and opaque_9/10/11. CHECKs enforce widths/name-key agreement.
  No packed persona array duplicates the live authority. Journal word snapshots
  remain unchanged. Adapters detect complete legacy vs column schema per connection;
  imports support both, fresh init-schema/local labs use columns. personas.sql is
  deliberately legacy test data. tools.persona_schema performs an offline verified
  staging/table swap, preserving all words/gen/revision/time and journals; creates
  a whole-DB backup first, leaves historical personas_words_archive. Requires all
  writers/DDL stopped: MariaDB forbids RENAME under LOCK TABLES, so source is
  rechecked after unlock before atomic swap. Failed staging is retained, not auto
  repaired. Additional persona columns/triggers/FKs need explicit migration.
  --local-state owns launcher lock and private DB for upgrade; regrants column
  UPDATE privileges. Manual UPDATE should increment revision with a revision guard,
  preferably logged out; SQL doesn't change a live BCPL profile. No revision trigger.
  Evidence persona-columns-acceptance, native-persona-columns (16 imported +16
  restored auth controls), external-columns-browser (SAVE/PASSWORD/PURGE/restart);
  166 host tests passed. Local external-local's one saved persona was backed up at
  before-persona-columns.zip, upgraded and exactly verified, then restarted :8081.
  Browser PURGE required gateway input credit at the exact unstarred menu prompt;
  regression/Chromium deletion passed. Private MariaDB fixtures now own tmp/ to
  avoid shared OS-temp initialization failures. See docs/persona-columns.md.

- Long-running external-local lookup failure was traced to both raw TTY6/7
  assigned to job 1 STOMPR in INIT, not invalid MariaDB columns: direct worker
  reads returned FOUND but guest OPEN failed. tools.serve_external now removes
  only STOMP from the private copied guest's SYS:TTY.INI, keeps other settings,
  saves XTTY.INI under the operator directory, verifies and KSYS/reboots before
  readiness; later starts are idempotent and verify STOMPR absent. The optional
  terminal initializer must not reclaim the storage pool. Native/default/deployed
  configs and the source disk remain unchanged. Browser setup already sets type/
  width; native LOGIN and MUDGUEST autostart still pass. Chromium acceptance:
  external-local-stomper-verified and external-local-idle-verified (75-second idle
  lookup, SAVE/PASSWORD/restart/PURGE). no-stomper's earlier final KSYS timeout
  and private bridge-init-check experiments remain. Local saved records retained.

- Local Connecting loop after long uptime was the historical opening schedule:
  at Friday 15:21 MUDGUEST returned to monitor before the name prompt, and the
  bootstrap waited until timeout. ExternalBootstrap now bounds/reads the preamble
  and detects monitor/EOF early. tests.integration_external_availability builds
  only X24LIB timeok change, links ROBOOT at 140 and DBADAT at 520000, initializes
  from existing MUD.DMP, preserves XHRS.EXE and restores MUD.EXE<055>. No DEMO or
  DBASE rerun. external-always-open-green passed Chromium at Friday 15:19; its
  clean stopped compiled/guest.dsk is the new serve_external default source.
  tools.install_external_availability patched the stopped existing external-local
  disk in place under its lock with before-always-open.dsk backup; MariaDB unchanged.
  always-open.json records completion. Old lifecycle-green source retains hours
  if selected explicitly. 48 relevant host tests passed. Earlier out-of-hours
  fixture's final BATCON/KSYS timeout remains; green is the completed acceptance.
  See docs/external-local.md. Do not replace an existing game disk to install this
  executable patch or restore the full backup just to roll back the executable.

- Persona storage v3: tools.persona_timestamps converts LSTM to last_saved_at
  DATETIME(6) (MJD epoch 1858-11-17, 18-bit day/fraction), zero -> NULL; integer
  rounding exactly reconstructs all native fractions. Nine STATES fields become
  whole-second TIMESTAMP NULL DEFAULT NULL x_at markers. NULL=off, non-NULL=on;
  successful off->on timestamps UTC observation, on->on retains, on->off clears.
  Observe at persistence, not in-memory toggle; no complete transition history.
  created_at whole-second TIMESTAMP before whole-second updated_at; new rows get
  insertion time, SAVE preserves creation, old rows remain created_at=NULL.
  All adapter connections use UTC. Existing v1 arrays/v2 columns remain supported;
  fresh schema/local labs use v3. Journal word snapshots and R1/W1 version stay 1.
  tools.persona_schema --timestamps uses persona_timestamp_schema offline verified
  table swap, archive personas_columns_v2_archive, one UTC backfill for enabled
  flags and deliberate updated_at microsecond truncation. Generations/revisions/native
  words/journals preserved. Same no-writers/DDL requirement as column migration.
  Evidence persona-times-acceptance, native-persona-timestamps (16+16 auth),
  external-timestamp-browser (SAVE/PASSWORD/restart/75s idle/PURGE); 174 host tests.
  Local two personas backed up before-persona-timestamps.zip, exactly verified
  against v2 archive after upgrade and restarted :8081. See docs/persona-timestamps.md.
  Manual SQL timestamps still need revision guards; non-NULL observation date
  changes may leave native flag words identical. asleep stays boolean. Namespace/
  name_key/generation are identities, not dates. No native/world code changed.

- The 24/7 build replaces only generated `MUDLIB.BCL`'s `timeok()` schedule gate
  with `demo\/~overload(numbargs()->low, low1)` (BCPL NOT is `~`, no extra escape).
  See `build/mud86-always-open/local.diff`; `source/` remains byte-for-byte intact.
  Do not use DEMO as a substitute: it changes gameplay and adds to HOURS output.
  Guest build uses `M24LIB.BCL/REL` instead of `MUDLIB.REL`; `MUD24.EXE` is the
  uninitialized linked image. Installed `MUD.EXE` was initialized from the existing
  `MUD.DMP` under RICHARD and restored to protection `<055>`. No DBASE rerun needed.
  Rollback executable is `MUDHRS.EXE[2011,2776]`. `MUDHRS.PM` is the pre-install
  persona backup; FILCOM /B against `MUDNOW.PM` found no differences after install.
  Never restore that persona backup just to roll back the executable.
  `tests.integration_availability` passed a 330-second out-of-hours guest session
  starting Friday 07:19, unchanged HOURS, saved-password re-entry and world reset.
  It leaves disposable saved personas (including `Avdiviqm`) and requires an idle
  operator monitor prompt. `--reset-world` must only be used on this local test game.
  For TECO source edits via CTY, use `SET TTY NO ALTMODE` or `~` becomes ESC;
  send CR rather than CRLF for inserted newlines. FILCOM verified only the expected
  timeok change in the guest copy. Full procedure is in `docs/restoration.md`.
- MBOOTS.MAC contains SUBFIL sections for POWER.BCL and DBADAT.MAC plus a final
  archive delimiter. The duplicate DBADAT agrees after framing is removed.
- Missing MUD.MIC and eight .DBA assets come from pinned PDP-10/MUD1 revision
  `8d2ce6ee5ca1ae3d835538de20aeb87acaae3df1`. MUD.WIZ remains unrecovered.
- A local replacement `DSKB:MUD.WIZ[2011,2776]` now contains `grobble` on a
  CRLF-terminated line, protection `<055>`. This is a local authorization entry,
  not recovered historical data. Created with TOPS-10 COPY from TTY and verified
  with TYPE/DIRECTORY. `WIZARD MODE` consults this file to authorize wizard mode;
  adding an entry does not itself reset the world or change persona passwords.
- Archwizard password audit: ordinary saved passwords authenticate Roy, Brian,
  Ronan, Friday, Yawn and Debugger, but are rejected for Richard. This was tested
  in historical and 24/7 private builds, via MUDGUEST and RICHARD OS accounts.
  Richard's stored PSWD stays unchanged; the same password and identical stored
  word work for an ordinary control persona. The exception in MUDLIB.BCL changes
  the in-memory comparison value, not the stored word on a rejected login.
  Do not advertise a generated Richard password as a verified direct-login credential.
  See `docs/archwizard-password-audit.md` and `tools/audit_archwizards.py`.
  `tools/fixtures/AUDPWD.BCL` is a separate read-only inspector; do not instrument
  MUD itself, as changing its layout could affect the address-derived check.
  The standalone BCPL library's DOFILE takes 15 arguments, unlike MUD's 11-arg wrapper.
- Richard ATTACH is now verified on the private 24/7 audit image through MUDGUEST:
  existing saved Roy login grants `maint`; different passwords prompt, wrong/Roy's
  passwords are rejected, Richard's correct password succeeds. Matching password
  values skip the prompt. ATTACH's password question has no following `*` because
  it sets `pretend=true`. WHO and wizard-only GO WRDBE confirm the attached persona;
  SCORE's Novice label is point-based and does not indicate missing wizard powers.
  **Do not assume attached SAVE/QUIT is protected.** ATTACH sets ATTED, then loading
  the saved STATES word clears it (MUD7.BCL:226,234; DUNGEN.GET:368–373). Session
  `ps.word` stays Roy's. Native tests confirm SAVE as Richard succeeds and replaces
  Richard's PSWD with Roy's; QUIT also does so if Roy was SAVEd earlier in that
  session. QUIT alone preserved this zero-score/one-game fixture, but other normal
  persistence conditions can trigger writes. The prior blanket no-SAVE/no-update
  interpretation was wrong. `--richard-attach` in tools/audit_archwizards.py tests
  six cases, restores the private AUTH0 fixtures, and stops its emulator. See
  docs/archwizard-password-audit.md and the ignored attachment-report.json evidence.
- `tools/provision_archwizards.py` is the standalone first-install step for all
  seven names, including Richard. It takes an explicit loopback Telnet `--port`,
  creates/SAVEs missing personas, and preserves existing nonzero passwords. Use
  the same private `--state-dir` on reruns; its 0600 initial-credential journal is
  written before creation, atomically updated and locked. `--show-credentials`
  explicitly reveals only known matching values with a password-manager reminder.
  Richard is labelled attachment-only; native password drift is reported, never
  silently reset. Zero-password existing records and ambiguous interrupted SAVEs
  stop for reconciliation. No authentication code is patched. The read-only
  AUDPWD companion is compiled through a maintenance TTY, without transcript logs.
  Pace COPY-from-TTY source transfers at 50 ms per line: echo can precede COPY's
  consumption; unpaced reruns overflow typeahead (XOFF/BEL and a truncated line).
  `tests.integration_provisioning` passed first creation, CLI rerun, all seven
  login checks, Richard ATTACH and preservation/detection of attached SAVE's
  password change on a disposable historical-baseline disk. See
  `docs/archwizard-provisioning.md`; this is not the full installer/deployment stack.
- Original DBASE produced 420 rooms, 482 object instances, 207 classes, 253
  vocabulary objects, 16 motion words and 25247 words of database space.
- SETSRC changes the path, not the maintenance PPN. Initialize MUD under the
  actual RICHARD login. BCPL can use ASSIGN DSK: BCL: with local library files.
- Generated extensions start with a dot: MUD..RM etc. Use MUD.??M / MUD.?PM.
- Source-transfer tapes from tools/source_tape.py are unlabelled PIP tapes, not
  BACKUP savesets. Do not use BACKUP to restore them.
- Exit/restart BACKUP to clear INTERCHANGE before native directory restores.
- SIMH emits nonstandard WILL LINEMODE: the gateway declines that option.
- Gateway setup commands must end with a single CR, not CRLF. TOPS-10 treats
  the extra LF as another input terminator; after LOGIN it reaches MUD as an
  empty persona name, producing a duplicate `*`. Browser smoke checks assert
  one name prompt on both initial connection and automatic reconnect.
- Original MUD's `NOECHO()` sets GETLCH/SETLCH local-copy bit (GL.LCP), not
  program no-echo (GL.NEC). TOPS-10 SCNSER's TTVID clears local copy during
  rubout handling, printing deleted password characters in backslash notation.
  `server/password_input.py` recognizes the original pre-game password prompts
  and buffers silent line editing until Enter; only the completed line goes
  upstream. The game still validates passwords. No filtering of game output.
  `tests.integration_passwords` verifies creation and existing-password editing
  in all four styles. It uses SAVE because zero-score new personas otherwise
  are not persisted on QUIT; these tests leave disposable saved personas.
- Match browser/Telnet columns to TOPS-10 `SET TTY WIDTH`: 79 versus 80 makes
  INFO wrap isolated letters onto new lines. Before login, issue `SET TTY TYPE VT100` on each DZ connection;
  Telnet's terminal name alone does not enable TOPS-10 display-mode erasure.
  Browser input normalizes BS to DEL/RUBOUT. The browser smoke test checks
  visual and server-side editing plus INFO's lack of browser soft-wraps.
- A TCP close alone can leave a TOPS-10 local TTY job alive. Gateway cleanup
  performs QUIT/KJOB and validates the new persona prompt before exposing output.
- Wizard RESET from MUDGUEST fails with MUD.EXE protection <055>: the original
  resetgame() opens the executable but its same-name RENAME fails. It prints
  the success message even on that failure. A verified operator reset is to
  log into the password-free RICHARD OS account and issue
  `RENAME DSKB:MUD.EXE[2011,2776]=DSKB:MUD.EXE[2011,2776]`.
  This supersedes the shared segment without changing file protection or needing
  a persona password. Old players remain in the old world; quit/reconnect to
  join the reset world. Separate old/new WHO lists verified this behavior.
  This direct operation does not set the old segment's in-game `supers` flag.
- Do not edit an active SIMH .ini file: a running DO script can retain its file
  offset, and stopping simulation may execute newly shifted trailing content.
- SIMH's makefile can auto-install packages. Build with USEFUL_PACKAGES= and
  OPTIONAL_PACKAGES= to suppress that behavior.

## Hosting / idle measurements

- Keep WebSocket receiving separate from prompt-fenced guest sending. Waiting for
  input credit inside the receiver can starve PONG and restart frames, closing a
  responsive browser after the heartbeat deadline. Pending input is byte-bounded
  (including the sender's in-flight wait); overflow closes1009. Gateway tests
  cover responsive PONG, real Chromium, ordered prompt release, overflow and
  restart/logout cleanup. Existing running gateways need restart to load changes.

- SQL editor access is managed by tools.database_access during MariaDB setup:
  127.0.0.1:3307, skip-name-resolve, private database-editor.json credentials,
  and a column-granted updatable persona_editor view. Game storage still uses
  its Unix socket; unconfigured PrivateDatabase/local labs stay socket-only.
  Never enable TCP without the account-isolation step: historical root has an
  empty socket password. Numeric loopback root/game/anonymous identities are
  locked, and non-local root/game/anonymous identities are locked idempotently. TCP root,
  game, anonymous and wrong-password rejection passed MariaDB 12.2.2/macOS and
  10.5.29/AlmaLinux ARM, including a 127.0.0.2 source and actual SSH forwarding.
  mud86_editor_revision fires only for USER()'s editor login, including no-op or
  timestamp-only updates; game writes still increment once. Pending SAVE CAS
  conflicts passed, but edits must be logged-out to avoid later stale-profile
  overwrites. Identity/revision/metadata edits, base tables/passwords/journals,
  INSERT/DELETE and DDL are denied. Credentials, object definitions and exact
  grants are preserved/verified; drift or a locked editor stops setup for reconciliation.
  ALTER USER re-lock of an already-locked hostname account failed on MariaDB 12;
  inspect mysql.global_priv's account_locked before changing it. Whole-DB backup/
  restore retains the view/trigger; paired configuration reprovisions users/grants.
  Evidence: runtime/db-editor-verified, database-editor-alma-report.json and
  editor-service-verified (browser SAVE/PASSWORD then SQL score 123 seen on login).
  SQL acceptance calls the production driver directly; bounded-worker unit tests
  and the real game-service check retain production deadlines. Earlier rapid
  isolated-worker fixture runs hit UNAVAILABLE/UNKNOWN under local Docker load;
  keep their evidence rather than increasing worker deadlines.
  GUI clients and the updated native-x86 installer matrix remain separate checks.

- Scheduled maintenance: `mud86ctl maintenance on --graceful|--wait`, `status`,
  `off`. `/etc/mud86/maintenance` gates Nginx and gateway admission and survives
  setup/restart; only readiness-checked off removes it. Nginx serves independent
  503/no-store HTML with Retry-After 900 while game/gateway are stopped. Terminal
  close 4015 selects 15-minute retry; handshake failures consult independent
  `/maintenance-status` JSON because browser WebSockets hide HTTP response headers.
  `/internal/maintenance` counts handlers through QUIT/KJOB cleanup; loopback-only
  in gateway, denied by Nginx. Wait holds management lock, Ctrl-C leaves notice
  enabled; failed count never implies zero. Stop gateway before runtime for
  graceful cleanup. Counts exclude independent operator/Telnet jobs. Host/browser
  and disposable AlmaLinux Nginx tests cover this; full installed systemd and
  target-host SELinux maintenance acceptance remain unrun. See docs/deployment.md.

- Deployment acceptance clients must stay on loopback and reject redirects before
  following them, including WebSocket upgrades (`tests.deployment_http`). The TLS
  fixture redirects port 80 to `https://mud.etimbo.com` without the host-mapped
  port: using HTTP after that step could reach the public server. The cutover
  precheck uses `--native-url https://127.0.0.1:38443`; after explicit HTTP-only
  setup, checks return to the mapped HTTP endpoint. Reuse the native acceptance
  report's verified persona identity and require its exact greeting. Earlier CI
  fixture calls may have created disposable public personas; they are not valid
  local cutover evidence. Never infer local persistence from a redirected login.

- External AlmaLinux deployment CI run 37695126208 passed at commit 6a6a2f6:
  native install/rerun/login/timing/backup, Chromium multiplayer, HTTPS/WSS,
  container reboot, populated native-to-MariaDB cutover and fresh external setup.
  Both external modes passed re-entry, backend-aware inspection, installer rerun,
  backup and restart. Private reports: runtime/external-deployment-ci-green.
  Setup now waits for Nginx's expected local vhost mode after reload (10s bound,
  no redirect following); reload itself is asynchronous. 28 focused tests passed.
  Earlier native initial-monitor/OPR stalls and one browser editing failure remain
  unresolved. This Linux matrix does not independently cover external PASSWORD/
  PURGE, deployed restore or external host reboot; retain separate milestone
  evidence and target-host ACME/SELinux/cutover checks. No actual VPS cutover.

- Read-only SSH inspection: `tools/inspect_game.py`, dispatched by `mud86ctl`
  through `tools/deploy.py`. Commands: personas/persona, files/file, logs, errors;
  explicit `inspection-install` compiles independent MVPER/MVTXT companions.
  Setup installs/verifies them after provisioning. Queries never recompile or
  enter MUD. MVPER uses original file-associated ENQ resource 142857 and explicit
  DEQ before output; contention **waits**, verified with an independent holder.
  Host responses are bounded at 90 seconds/4 MiB, with interrupt/KJOB cleanup.
  Persona snapshots cap at 2048 records and never emit PSWD values. Large vectors
  must use NEWVEC: a stack VEC for the snapshot caused an illegal-memory-reference
  fault. SIXBIT requests use octal shifts: decimal multiplication lost bit 35.
  MVTXT retains a 64-KiB tail with an explicit truncation flag, scans at most 4 MiB,
  and transmits framed octal character groups instead of raw monitor-like text.
  Original MPPN `#2600002776` means **[2600,2776]**, separate from [2011,2776].
  The baseline MUD.LOG there is missing/inaccessible; readers report this rather
  than creating it. Error scans cover host journals/guest console, not private
  player TTYs. Native inspection integration passed lock contention, concurrent
  SAVE, FILCOM /B byte preservation, CLI, text tails, password preservation and
  original source hashes; evidence runtime/inspection-check-final. Real AlmaLinux
  ARM journal integration passed. Full new x86 deployment/remote update remains
  unrun. See docs/inspection.md for operation and coverage semantics.

- `%SIM-INFO:` listener/tape startup lines are normal, not diagnostic-review
  findings; keep detection for other lines in the same journal entry and explicit
  warning/error priorities. Finding counts are messages, not distinct incidents.
  Gateway stop timeout report exposed missing active-WebSocket shutdown handling:
  aiohttp can wait 60 seconds, exceeding systemd TimeoutStopSec=45. The gateway
  now tracks request handlers and uses on_shutdown to cancel active transport so
  its existing QUIT/KJOB finally block runs; handlers already cleaning up are
  awaited without a second cancellation. Tests cover multiple connected browsers
  and a logout in progress. The remote server still needs this follow-up update.

- Remote gateway close tracebacks (September 20–22) reproduced with pinned
  telnetlib3 2.0.8: BaseClient.connection_lost feeds EOF before queued _process_rx.
  SimhClient now cancels the pending task and synchronously drains queued bytes
  before forwarding closure; final output/Logged-off is preserved. Its parser
  override completes fragmented IAC commands before using the base chunk scanner,
  which otherwise starts in text mode. Late data and pre-negotiation closure are
  guarded. Review these private-library hooks before any dependency upgrade.
  Browser send OSErrors become BrowserDisconnected, not upstream failures;
  unavailable notifications are best-effort, and original QUIT/KJOB cleanup runs.
  Upstream warnings include exception type to make blank TimeoutErrors useful.
  Explicit Python ERROR/CRITICAL/WARNING messages now retain their severity in
  inspection reports. 58 transport/gateway/inspection/deployment tests passed
  macOS Python 3.9 and disposable AlmaLinux ARM Python 3.12. Follow-up VPS update
  remains pending; do not infer that every historical warning had these causes.

- ATTACH creation-question cleanup is now reproduced and fixed in the gateway.
  `logout_guest()` tries QUIT, then on timeout uses server-controlled Ctrl-C,
  confirms the monitor, and KJOBs; each wait is bounded at three seconds. No KJOB
  without a monitor, no automatic EXORCISE. LOGIN-sent/intro-timeout sessions also
  need cleanup. Defer upstream-error browser closure until cleanup: closing first
  let cancellation interrupt cleanup in the regression. Logs include connection
  IDs, setup/cleanup stages and exception types, never raw terminal payloads.
  64 host tests passed macOS 3.9 and AlmaLinux ARM 3.12. The disposable native
  `tests.integration_gateway_cleanup` passed Ctrl-C, disconnect, restart and
  shutdown at ATTACH's sex question, using Roy and missing letter-only targets.
  SYSTAT confirmed guest-job removal, FILCOM /B byte-identical saved personas,
  password preservation and normal re-entry. Final evidence is under
  runtime/gateway-cleanup-deployment-speed (NOIDLE / 5M / SPEED=*8); red failure
  is retained under runtime/gateway-cleanup-red. SYSTAT emits PPNs without brackets;
  Logged-off can precede job disappearance briefly, so poll with a deadline.
  Select throttle before spawning SIMH: an exploratory mid-run reconfiguration
  stalled. Remote deployment of this cleanup follow-up is still pending.
  User also confirmed ordinary-persona ATTACH/QUIT password overwrite and EXORCISE
  from another archwizard removing the abandoned live presence. Neither original
  behaviour is patched. Login readusername accepts letters only (test1 -> test),
  whereas ATTACH's read.name accepts digits, so test names must be alphabetic.

- AlmaLinux deployment entry point: `setup.sh` → `tools/deploy.py`. Root-managed
  `mud86ctl` lives in `/usr/local/bin` with an alias in `/usr/bin`: AlmaLinux's
  sudo secure_path can omit `/usr/local/bin`. Existing hosts can add that symlink
  without restarting the game. Keep both paths working on installer reruns.
  Root-managed
  app snapshots live under `/opt/mud86`, persistent disks/journal under
  `/var/lib/mud86`, configuration under `/etc/mud86`. Existing disks are never
  replaced on setup reruns. `server/runtime.py` is the foreground systemd
  supervisor, with a state lock, original tape boot, UTC boot clock, actual MUD
  readiness probe, bounded retries and KSYS shutdown. The gateway has an HTTP
  readiness post-check; management commands must wait for both services after
  a restart. A new boot invalidates the prior clean-shutdown marker. Backups
  require confirmed shutdown and the runtime lock, and publish atomically.
- `tools/package_runtime.py` builds only from the pinned stopped first-playable
  checkpoint. It rebuilt the 24/7 executable using original DBASE, found zero
  personas and completed KSYS before packaging. `deploy/runtime.json` pins the
  archive and both members. Never publish a disk used for provisioning tests.
- Deployment uses a separate NOIDLE / 5M throttle / DZ SPEED=*8 profile. Native
  x86 AlmaLinux CI has passed initial install, rerun, saved-player re-entry,
  sleep timing, backup/restart and Chromium multiplayer. Docker x86 translation
  on the M5 was unreliable at boot, including with throttle; do not treat its
  failures or occasional successes as native x86 acceptance. Native ARM Linux
  and macOS boot/reboot controls also ran. See the deployment workflow and
  docs/deployment.md for final checks and public ACME/SELinux/IONOS limitations.
- Gateway deployment checks reproduced pasted commands escaping past QUIT and
  abort controls reaching the monitor. The gateway now rejects unsupported C0
  controls, serializes submitted lines until a game prompt (including ATTACH's
  unstarred password question), and closes on a monitor return even before a
  persona greeting. Tests cover QUIT, rejected entry and control-character cases.
- `.github/workflows/deployment.yml` tests a one-CPU/2-GB AlmaLinux systemd
  container on native x86. After Docker restart, wait for systemd's D-Bus socket
  before issuing service commands; the first CI reboot failure was that test
  race, not a failed guest boot. Test output redacts archwizard credentials.
  Run 35499541986 passed the complete native x86 workflow, including HTTPS/WSS
  with a test certificate and the reboot browser check; original sleep timing
  measured 5.980, 5.982 and 6.010 seconds. Public ACME issuance and enforcing
  SELinux on the actual IONOS VPS remain target-host checks.

- Read `docs/hosting.md` before selecting or promoting an idle configuration.
- On Apple M5, isolated IDLE + DZ `SPEED=*8` tests used about 17–18% of one
  core versus about 99.5% without IDLE. Eight paced WebSocket players had
  p95 full-response latency about 0.267 seconds. Clock and representative
  original sleep/daemon timing comparisons passed.
- IDLE at the original terminal rate saved CPU but regressed long-response
  latency. The faster DZ setting affects transport, not game-clock speed.
- Startup and IDLE pause/resume verification also stalled. Startup stalls were
  seen with NOIDLE too; adding a settling delay did not resolve every case.
  The live/default configuration remains unchanged. `config/pdp10-idle.ini`
  is experimental, selected only via the `SIMH_CONFIG` environment variable.
- `tools/benchmark_idle.py` and `tools/verify_idle.py` use disposable baseline
  disk copies and private ports; do not redirect them to a live game disk.

## Validation

- The Settings modal has four tabs in order: Settings, About, Licences, Links.
  The selected tab visually joins the bordered, scrollable content panel.
  Tab headings have no extra focus outline; focus follows the selected tab.
  Every open resets to Settings and focuses its tab heading. Tab still CLOSES
  the modal (explicit user preference); Escape/Return to game also close it.
  Left/Right/Home/End navigate focused tab headings. Send Tab is Settings-only.
  Scrollable content keeps tabs/footer visible on small screens. Licence content
  is loaded once from `/static/legal.html`'s `#licence-content` section, with a failure link
  and retry on reselect, so the standalone page and modal share one source.
  Use the static URL so a local gateway started before /legal was added can still
  display the notices without a restart. The Links panel starts directly with its list.
  Licence sections begin with Original MUD, then Browser and restoration software,
  then Fonts and other components. Full licence documents and the component
  inventory link to GitHub's rendered files so they also work with older local
  gateways that return 404 for /legal/...; bundled .txt font notices stay static.
  The MUDDL resource links to the inherited Michael Lawrie PDF on GitHub: the
  requested Wayback snapshot returned 503 during the link audit. All 27 unique
  modal/standalone legal-page destinations returned 200 after repair on 2026-09-20.
  Outbound resource/licence links use a new tab with noopener. About credits
  Tim Rogers's browser server version, built using OpenCode and GPT-6 Astra.
  Browser tests cover exact link order, default/reset state, keyboard shortcuts,
  narrow-screen layout, licence-loading recovery and preservation of Chat drafts.

- Chat transcript copying serializes the selected visible DOM rows with explicit
  newlines, preserving blank rows, indentation and displayed wrapping. Keep native
  copying for input fields and selections extending outside the transcript.
  `tests/test_terminal.py` covers partial/backwards selections, Mode 7 wrapping,
  draft exclusion and an actual Chromium keyboard-to-clipboard copy.

- The shared Chat command/password input uses `autocomplete="new-password"`
  with form-level `autocomplete="off"` to discourage website-login autofill;
  Firefox can ignore input-level `off` after recognizing a login field. These
  are hints, not a guaranteed suppression of password-manager UI (including
  generated-password suggestions). The user confirmed the updated Chat input
  looks good in Firefox on 2026-09-20. `MUD86_TEST_BROWSER=firefox` or `webkit` selects
  another engine for `tests.test_terminal` (default Chromium). The Chat
  login/editing/reconnect test passed Chromium and WebKit; local Playwright
  Firefox 141 failed to finish launching with sandbox/graphics errors.
  Wait for paced text to appear before testing native Backspace in WebKit.
  Non-Chat mode uses xterm's separate textarea: set the same `new-password`
  hint via `terminal.textarea` immediately after `terminal.open`, before focus.
  Its typing/reconnect regression passed Chromium and WebKit; the non-Chat
  Firefox saved-login popup still needs user verification.
  Follow-up: the user reproduced the popup in Chat after a saved-persona login.
  Firefox's LoginManagerChild uses `hasBeenTypePassword`, so changing a password
  input back to text does not stop it being treated as a login field. Chat now
  creates a fresh text input on password-to-command transitions (also disconnect),
  copying attributes except type rather than cloning the password element.
  `PacedChatInput.bindInput` rebinds the existing editor without resetting its
  queue; Chat key handling is delegated to the form. Draft, selection and focus
  survive, and replacement must not steal focus from Settings. Docking/resizing
  still uses the same element. The regression passed Chromium and WebKit; the user
  confirmed the follow-up fixes the Firefox popup on 2026-09-20.
  See Mozilla's `toolkit/components/passwordmgr/LoginManagerChild.sys.mjs`,
  especially `isLoginManagerField` and `_getPasswordFields`.
- Chat mode is a separate Settings switch, stored in `mud86-chat-mode`, alongside
  the independent `mud86-terminal-style` preference. The old `chat` style migrates
  to Default + Chat enabled. Chat inherits the chosen style's font, colours and
  width (40 for Mode 7, 80 otherwise), with no fixed transcript height.
  Input is inline after the parsed cursor until the transcript fills the screen
  and the reader is at the bottom; only then does it dock to the display frame's
  lower edge. The docked strip shares main's width, edges, background and 1px
  outline. One padded row is reserved inside main to keep docking scroll-stable; there
  is no separate input border, page spacer or Send button. Enter submits commands.
  The docked strip has 6px vertical padding and projects the current standalone
  engine prompt beside the input (including wizard/invisible/converse variants).
  Its transcript row keeps its height but hides that prompt while docked; the
  xterm buffer is untouched, so completed command echoes retain their prompts.
  Scrolling up restores inline input without forcing focus or scroll position.
  The same input element preserves drafts, selection and password masking across
  docking/resize transitions. Its Command label is accessible-only. The header is
  sticky with an opaque style-matched background in every presentation.
  `web/chat.js` projects xterm's parsed buffer into text-only DOM rows, so CR,
  rubout and VT erase sequences retain their original meaning. The existing
  10,000-line scrollback limit still applies; there is no fixed-height viewport.
  `web/chat-input.js` applies the selected send baud to local typing/paste/edit
  operations (10-bit framing). Enter queues behind pending edits, then sends the
  complete line in one WebSocket message without a second upstream throttle.
  Projected draft/selection state preserves typeahead, replacement and backspace
  while the visible field catches up. Zero-cost Enter/selection operations retain
  order with paced edits. Disconnect/restart clears both the visible draft and queue.
  Regular terminal input still uses the original outgoing SerialPacer; receive
  pacing is independent and unchanged. Tests selecting draft text must first wait
  for the local edit queue to display it, even at 9600 baud (20ms clock ticks).
  Only the engine echoes commands. Known login and PASSWORD prompts mask the input;
  no command history is stored.
  Send Tab inserts a tab into the unsent Chat draft; the terminal modes send it
  directly. Toggling Chat requires the existing session-restart confirmation even
  without a geometry change. Style changes preserve the Chat switch. Settings
  restores focus to the active input, not hidden xterm.
  `tests.integration_chat` checks real-game login/editing/INFO, saved-password
  reconnect, adaptive input, pinned header and Settings. It leaves a disposable
  saved persona. `--style bbc40` exercises the 40-column Chat presentation.
- Terminal styles live in the Settings dialog and persist in browser localStorage.
  Original is the default: green, Menlo/Consolas, 16px, 80×30. VT220 uses white
  GlassTTY lettering at 20px, 80×24. BBC Mode 7 uses Bedstead at 20px, 40×25.
  DEC VT52 (`vt52`) uses Fritz Mueller's MIT-licensed ROM-extracted font at 15px,
  white on black, 80×24. IBM PC MDA (`mda`) uses VileR's Web IBM MDA at 14px,
  green on black, 80×25; IBM PC CGA (`cga`) uses Web IBM CGA-2y at 16px,
  light grey on black, 80×25. Both IBM fonts are CC BY-SA 4.0. All three are
  bundled unmodified; provenance and hashes are in `VT52-LICENSE.txt` and
  `IBMPC-LICENSE.txt`. These are presentation presets; keep upstream VT100
  setup and width 80 for all three. Tests check loaded fonts, ASCII cell widths,
  exact 80-column wrapping, persisted Chat styling, and live session retention.
  BBC Mode 0 uses BBC Master-family bitmap lettering at 16px, 80×32; its
  source is VileR's CC BY-SA 4.0 Master 512-2y font, not an exact MOS ROM font.
  The old `bbc80` preference migrates to `bbc0`. These reproduce lettering,
  not BBC graphics or teletext control codes. Font provenance is in
  `web/vendor/GlassTTY-LICENSE.txt`, `Bedstead-LICENSE.txt`, and `BBCBitmap-LICENSE.txt`.
  `terminalReady` loads fonts before opening xterm and enabling style/Connect controls.
  Font, colour and row-count changes apply live when the column width is unchanged,
  preserving the connection, scrollback, draft and baud queues. Width changes during an
  active connection require confirmation; Cancel/Escape leaves the saved style
  and session unchanged. Confirm sends the reserved binary WebSocket `restart`
  control frame, clears queued input, and waits for gateway QUIT/KJOB cleanup
  before the socket closes and automatic reconnect applies the new dimensions.
  The binary control is never forwarded to the original game.
  Mode 7 deliberately uses TOPS-10/Telnet width 255, then `web/wrap.js` reflows
  original lines to 40 columns AFTER receive pacing. This avoids monitor-inserted
  breaks splitting words. Other presets use upstream width 80. Always set width
  before login, even when reusing a line. Wrapping stays fixed for the session
  alongside its column count, independent of live font/colour/row-count changes.
  The formatter tracks a logical line and its cursor for CR, BS, tabs and CSI
  erase/horizontal motion. Explicit newlines are preserved, not joined into
  paragraphs; this is a line-oriented MUD presentation, not a full VT reflow engine.
  Trim trailing padding only when a logical line completes: padded 80-character
  lines can otherwise create an extra blank wrapped row. Retain spaces during
  editing, and preserve explicit blank lines.
  `tests.integration_styles` passed original-game login, backspace editing and INFO
  wrapping in Chromium at both BBC widths.
- `web/serial.js` provides per-browser receive/send pacing with 10-bit framing;
  the controls offer 9600/9600, 300/300, and 1200/75 without changing guest TTY
  speeds. Tab opens/closes the native Settings dialog; Escape also closes it.
  The terminal cursor is hidden while Settings is open and focus returns on close.
  Cursor options alone are insufficient: CSS also hides xterm's DOM cursor while
  a dialog is open and makes dialog carets transparent for native caret browsing.
  Keep native dialog focus restoration intact (do not blur the terminal before
  showModal). Literal Tab remains available via the right-aligned Send Tab button.
- The terminal automatically connects after fonts load, without a header button.
  Socket closure clears queued input and reconnects after paced output and xterm
  writes drain, preserving scrollback and speed/style preferences. Failed attempts
  back off from 1 to 30 seconds; normal game exits reset the delay. Settings open
  via Tab or the compact top-right header Tab/cog button, using the same toggle handler.
  The icon and button have thin outlines. Live browser tests
  verify QUIT returns to a fresh persona prompt while retaining earlier output.
- `tests/test_terminal.py` uses Chromium with a fake WebSocket and virtual clock
  to check baud rates, panel controls, and reconnect queue isolation without SIMH.
  Browser smoke checks must wait for the incoming pacing queue before examining
  rendered output, since WebSocket receipt no longer means text is displayed.

```sh
.venv/bin/python -m unittest discover -s tests -v
python3 tests/integration_multiplayer.py
.venv/bin/python -m tests.integration_web
.venv/bin/python tests/browser_smoke.py
.venv/bin/python -m tests.integration_styles
.venv/bin/python -m tests.integration_chat
```

Integration tests require the original runtime. Chromium smoke additionally
needs :8080 and the browser binaries under runtime/browsers. Tests create
disposable personas; do not run against an unrelated public service.

## Operational scope

This is a local playable prototype. The original game code is running, but
exhaustive gameplay/persistence, missing wizard data, arbitrary disconnect
states and public deployment remain follow-up work. Keep those distinctions
clear in claims. Back up disk images only while the emulator is stopped.
