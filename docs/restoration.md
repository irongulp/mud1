# Restoration record

## Selected baseline

The supplied source was compared with:

- `https://github.com/PDP-10/MUD1`
- Revision `8d2ce6ee5ca1ae3d835538de20aeb87acaae3df1`

The runtime emulator used for successful compilation, multiplayer and browser
tests is SIMH revision `47b7ddabbe5b548cfc32f2fd45f7bed238ff7921`.

Preparation retains local code/data rather than replacing it with upstream.
The reviewed differences are release-notice additions, archive packaging,
a line break between two MUD8 case labels, and a TXTCBT comment. The complete
comparison is generated as `build/mud86/upstream.diff`.

`MBOOTS.MAC` embeds `POWER.BCL` and another `DBADAT.MAC`. Preparation splits
these, removes SUBFIL framing, checks the duplicate database skeleton agrees,
normalizes CRLF, and removes trailing NUL source padding. Tabs, descriptions,
action ordering and executable rules are retained. Interior NUL padding in
historical `.DBA` writing files is preserved.

The additions are `MUD.MIC` and eight `.DBA` files from the pinned repository.
`POWER.BCL` is recovered from the supplied archive, not invented. `TALK.TXT`
and `MUD.WIZ` are still absent; the main world compiled without `TALK.TXT`.

## Host dependencies

For a new checkout of dependencies:

```sh
mkdir -p upstream
git clone https://github.com/PDP-10/MUD1.git upstream/mud1
git -C upstream/mud1 checkout --detach 8d2ce6ee5ca1ae3d835538de20aeb87acaae3df1
git clone https://github.com/simh/simh.git upstream/simh
git -C upstream/simh checkout --detach 47b7ddabbe5b548cfc32f2fd45f7bed238ff7921
make -C upstream/simh pdp10 USEFUL_PACKAGES= OPTIONAL_PACKAGES=
```

The empty make variables suppress SIMH's optional package-install prompts.
During the initial build without those overrides, SIMH automatically installed
Homebrew `pcre`, `libedit`, `make`, `libpng` and `zlib`. Docker was not running;
the working setup uses the native emulator.

SIMH 3.12-2 and 3.8-1 were also investigated locally. They are not the selected
runtime and the directories remain under ignored `upstream/`.

## Historical media

Download using `python3 tools/fetch_media.py URL FILENAME`. The tool records
each actual URL, size and SHA-256 beside the downloaded file in `runtime/media`.
Verify the resulting hash against the table before using a new download.

TOPS-10 tapes come from `https://pdp-10.trailing-edge.com/tapes/`:

| Remote filename | Local filename | SHA-256 of compressed download |
|---|---|---|
| `tops10_ks_bootable_bb-x138c-bb_704.tap.bz2` | `t10boot.tap.bz2` | `d87ebaa1b907d738fa5ab75fb658958c6ccc04bbc95fd4958b7e6abe54071122` |
| `tops10_704_monitoranf_bb-x140c-sb.tap.bz2` | `t10mon.tap.bz2` | `b7f8e9f408b9aab82700bd5222a56db58b295bed9fdeffe9eec322a28df2d1df` |
| `cuspbinsrc_1of2_bb-x128c-sb.tap.bz2` | `t10cusp1.tap.bz2` | `4c29361324c5ca7c55fb88b9c892a8e3e8e0ef2384982957a2dfb4a05a76b3b6` |
| `cuspbinsrc_2of2_bb-fp63b-sb.tap.bz2` | `t10cusp2.tap.bz2` | `f2d5f02aa2e155ca33eb697ffa007ea3355d41139f5cee781f48dd5b94fa601b` |
| `cust_sup_cusp_bb-x130c-sb.tap.bz2` | `t10cust.tap.bz2` | `4c746868aa191a7ac46805249000a79b502c5054027d615469145fe00fee4f2d` |
| `tops10_tools_bb-fp64b-sb.tap.bz2` | `t10tool.tap.bz2` | `bccba75f02e067755fbadfe2f7534d7736159e32870e02551148e24530948de4` |

Run `python3 tools/unpack_tapes.py` once to decompress them.

Compiler tape:

```text
https://raw.githubusercontent.com/PDP-10/essex-bcpl/3fe466d1327cbb5f583d7d79575dbf250d8aa461/BCPL.tap
SHA-256 c5120bf8532c1c4f6cbf435515a7c18b62b32a8b9828b15d3c5d5e037176bfbd
```

The upstream `mud86.tap` and `bcplcompil.tap` were fetched for investigation,
but were **not** used to supply the executed MUD binary. That binary was built
from the prepared local source. The 7.03 prebuilt packs were also investigated;
the selected disk was installed separately from the 7.04 tapes.

## Building a fresh TOPS-10 disk

The detailed historical install dialogue is documented in
[Quentin's TOPS-10 installation guide](https://www.quentin.org.uk/2018/02/14/building-a-dec-pdp10-using-simh/).
The full local operator transcript is `runtime/console.log`.

The current `config/pdp10.ini` deliberately requires an **existing** disk. For
an initial install, use a separate SIMH console configuration that attaches a
new RP06 disk, attaches the boot tape to TU0, and `boot tu0`. At `BOOT>` enter
`/tm02`. Define and refresh DSKB according to the guide, then use `noinit` and
log in as `[1,2]`.

1. Restore `SYSTEM.EXE` and the DEC bootstrap utilities from the boot tape.
2. Exit/restart BACKUP before restoring the monitor and CUSP tapes in native
   mode. **Do not leave `/INTERCHANGE` enabled** for native directory restores.
3. Restore `t10mon`, the two-part `t10cusp1`/`t10cusp2`, `t10cust`, and `t10tool`
   to their native `[10,7,...]` directories.
4. Create HLP:, DOC:, REL:, UNV:, ACT: and UPS: with CREDIR.
5. Start NFT at its `*` prompt, then `python3 tools/install_utilities.py` copies
   the executable/library/help files to their standard directories. This tool
   checks completion after every copy; it is not a fresh-OS installer.
6. Configure SYSJOB.INI and TTY.INI as below.

SYSJOB.INI used here:

```text
SET DEFAULT ACCOUNT SYSTEM
LOG
FILDAE
LOG
ACTDAE
LOG
DAEMON
LOG
QUASAR
LOG
MIC
!
```

TTY.INI used here:

```text
ALL KSYS TEXT FILL:0 LC WIDTH:255
TTY0-37: SPEED:9600
CTY: GALOPR NO REMOTE ACCOUNT "SYSTEM"
STOMP ACCOUNT "SYSTEM"
```

### Verified boot path and unresolved alternative

The selected working path is **boot the original 7.04 tape with `/tm02`**,
then use the installed disk for utilities, compiler, accounts and MUD. The
bootstrap tape remains local media; this does not restore/reformat the disk on
each boot. `tools/boot.py` implements the boot dialogue and fixes the test clock.

Custom monitors were successfully built with 32 DZ lines, 1 MW memory, ENQ/DEQ,
and a BCL: ersatz device. They worked during the original warm build session,
but later disk-based cold boots stalled or produced KAF (keep-alive failure).
Changing SIMH versions and adding a throttle did not resolve that path. These
monitor images (`SYS2`/`SYS3` in `[10,7,MON]`) are not selected by the working
boot script. The precise disk-boot failure remains an investigation item.

Later isolated idle profiling also encountered startup stalls on this tape
path, with both NOIDLE and IDLE, plus an IDLE pause/resume stall. Successful
steady-state performance tests do not settle startup reliability. See
`docs/hosting.md`; the experimental idle profile is not the default.

The tape-boot monitor already provides the terminal lines needed for the tested
multiplayer game. A native BCL: ersatz device is unnecessary for executing MUD;
the build can use the per-job logical assignment described below.

## Compiler installation

During the original installation session, mount `BCPL.tap`, assign MTA0: to
TAPE:, and use BACKUP `/INTERCHANGE` to restore the files to `[1,2]`. Install
`BCPL*.EXE` and `BCPLIB.REL` into SYS: with protection `055`.

The compiler was tested by compiling, linking and starting:

```bcpl
GET "BCL:BCPLIB"
LET START() BE
$( WRITES(TTY,"Hello, MUD86!*C*L") $)
```

It printed `Hello, MUD86!`.

For building MUD, copy the compiler's `.GET` and library `.REL` files into the
build PPN `[2011,2776]`, then `ASSIGN DSK: BCL:` in that job. This avoids needing
to rebuild the monitor merely to resolve `BCL:`. The working disk already has
these files. The modified COMPIL utility is unnecessary when BCPL is invoked
directly.

## Source preparation and transfer

On a fresh output path:

```sh
python3 tools/prepare.py
python3 tools/source_tape.py build/mud86 runtime/media/source.tap
```

Preparation refuses to overwrite an existing output tree. For another audit
run, supply `--output build/another-name`. The upstream checkout must match the
pinned revision and have no tracked modifications.

The source tape is **unlabelled 7-bit ASCII packed into 36-bit words**, using
SIMH record framing. It is not BACKUP format. TOPS-10 PIP copies its sequential
files using `COPY filename=MTA0:` in the order recorded in `source.json`.
The transfer uses CRLF and final record padding, without treating source lines
as interactive terminal input.

Create `[2011,2776]`, mount the source tape at its beginning, assign MTA0: to
the operator job, then run `python3 tools/load_sources.py` at the TOPS-10 monitor
prompt. Its `--skip` option is only for continuing an already positioned tape.
This transfer and the original DBASE run succeeded during the installation
session. The final tape-boot runtime did not expose an assignable MTA0: during
a later export attempt; rebuild/transfer media handling needs further work on
that boot configuration. The files are already present on the working disk.

## Original game compilation

Use the actual `[2011,2776]` login for final database initialization. Changing
the default directory with SETSRC does **not** change the job's PPN; the engine
uses the PPN to determine maintenance access.

These are the direct commands used, equivalent to the essential MUD.MIC steps:

```text
ASSIGN DSK: BCL:
R MACRO
DBADAT=DBADAT
MBOOTS=MBOOTS
<Control-Z>
R BCPL
MUD0/O
MUD1/O
MUD2/O
MUD3/O
MUD4/O
MUD5/O
MUD6/O
MUD7/O
MUD8/O
MUDLIB/O
<Control-Z>
R LINK
MUD0,MUD1,MUD2,MUD3,MUD4,MUD5,MUD6,MUD7,MUD8,MUDLIB,MBOOTS/COUNTER/SET:.HIGH.:502700
DBADAT/G
SSAVE MUD
R BCPL
DBASE/O
<Control-Z>
R LINK
/SET:.HIGH.:430000
DBASE,SYS:BCPLIB/SEARCH/SET:.HIGH.:502700,DBADAT/G
SAVE DBASE
RUN DBASE
```

DBASE generates `MUD.DMP` and the `.RM`, `.TM`, `.OM`, `.MM`, `.CM`, `.GM`
extension files. These extensions contain an initial dot, so listings show
names such as **MUD..RM**. MUD loads the dump and forces `SSA` to save the fully
initialized executable. `RUN MUD` then reaches the persona prompt.

Observed loader diagnostics:

```text
rooms:       420 = last room number       used 4755
maps:          8 = last map number        used 26
vocabulary:                              used 8376
demons:       71 = last demon number      used 288
objects:     482 = last object number     used 4739
travel:      420 = last travel number     used 4062
text:       1114 = last text number       used 847
207 classes, 253 objects and 16 motion words defined
Total space used 25247
```

`71` is the printed last daemon number, not a claim of 71 distinct definitions.
Likewise, `1114` is the last text number printed in file order, not the largest
message ID; the data also contains 1500-series messages.

## Local 24/7 availability build

The installed `MUD.EXE[2011,2776]` now bypasses historical opening-hours
enforcement. The `HOURS` command and its original timetable are unchanged,
and the ordinary game rules, persona data and passwords are retained. This
does not synchronize the guest clock: the normal boot still starts at the
explicit date/time in `tools/boot.py`.

Generate the traceable variant into a **fresh** output directory:

```sh
.venv/bin/python tools/prepare.py --always-open --output build/mud86-always-open
```

Without `--always-open`, preparation remains historical. The option changes
only generated `MUDLIB.BCL`'s `timeok()` function to:

```bcpl
// Local 24/7 build: preserve HOURS data and the original load checks.
and timeok(low)=demo\/~overload(numbargs()->low, low1)
```

BCPL NOT is `~`: there is no backslash between `/` and `~`. The load check
and existing DEMO semantics are preserved; DEMO is **not enabled**. DEMO is
not a substitute for this patch because it changes gameplay and adds a
message to `HOURS`. Login and the periodic closing-warning logic already
call `timeok()`, so neither needs a separate patch. `TXTHRS.GET`, the hours
table in `MUD.DMP`, and the `HOURS` implementation in `MUD5.BCL` are untouched.

`local.diff` records the change and `provenance.json` records the selected
availability policy, original source hashes, and generated file hashes.
`source/` is never modified. Preparation rejects an unrecognized `timeok`
implementation rather than silently applying a guessed patch.

### Guest build and installation used here

The existing guest compiler, libraries and `.REL` files were reused. Because
tape transfer on this running monitor has unresolved device-assignment issues,
TECO made the same narrowly scoped change in a new guest `M24LIB.BCL`. The
original guest `MUDLIB.BCL` and `MUDLIB.REL` remain available. FILCOM compared
the two source files and reported only the expected function replacement.

Before inserting source through CTY, issue `SET TTY NO ALTMODE`: otherwise
TOPS-10 translates `~` into ESC. Insert newline characters using **CR only**;
CRLF input adds an extra LF. The TECO operation used was:

```text
R TECO
ERDSKB:MUDLIB.BCL[2011,2776]<ESC>EWDSKB:M24LIB.BCL[2011,2776]<ESC>Y
Nand timeok(low)=<ESC>0L.UASand overload(low)=<ESC>0LQA,.K
I// Local 24/7 build: preserve HOURS data and the original load checks.<CR>
and timeok(low)=demo\/~overload(numbargs()->low, low1)<CR><ESC>EX<ESC><ESC>
```

The displayed breaks between TECO commands above are for readability, not
extra keystrokes. `<ESC>` and `<CR>` mean those control characters. Verify the
result with `R FILCOM` and `TTY:=MUDLIB.BCL,M24LIB.BCL` in the build PPN.

Under the actual RICHARD OS login `[2011,2776]`:

```text
ASSIGN DSK: BCL:
R BCPL
M24LIB/O
<Control-Z>
R LINK
MUD0,MUD1,MUD2,MUD3,MUD4,MUD5,MUD6,MUD7,MUD8,M24LIB,MBOOTS/COUNTER/SET:.HIGH.:502700
DBADAT/G
SSAVE MUD24
```

The linker reported `.HIGH.` ending at `502577`, below the database boundary
`502700`. `MUD24.EXE` is the **uninitialized** linked image, not the installed
playable image. No DBASE recompilation was needed.

Before installation, an audit persona ran `HOURS` on the old executable and
`WHO` confirmed it was the only player. It quit normally without being saved.
Existing stopped guest jobs retained superseded segments; one stale terminal
job had to be logged off before the guest connection tests could start.

The installation commands were:

```text
COPY MUDHRS.EXE=MUD.EXE
COPY MUDHRS.PM=MUD.?PM
COPY MUD.EXE=MUD24.EXE
RUN MUD
PROTECT MUD.EXE<055>
COPY MUDNOW.PM=MUD.?PM
R FILCOM
TTY:=MUDHRS.PM,MUDNOW.PM/B
```

Use unused backup names on subsequent installations; do not overwrite these
rollback copies. `RUN MUD` under RICHARD loaded the existing `MUD.DMP` and
issued `SSA` to save the initialized executable. FILCOM's binary comparison
reported **No differences encountered** for the persona file before and after
installation. The `.PM` extension begins with a dot, hence `MUD.?PM` rather
than `MUD.PM` in COPY commands.

For executable rollback, with players having quit normally, copy the initialized
`MUDHRS.EXE` back to `MUD.EXE` and restore protection `<055>`. **Do not restore
the persona backup for an executable rollback**: it would discard later player
progress. Taking a host disk-image backup requires stopping the emulator first.

### Validation

```sh
.venv/bin/python -m unittest tests.test_prepare -v
.venv/bin/python -m tests.integration_availability --reset-world
```

The integration test requires the local emulator and an idle operator monitor
prompt. It checks `DAYTIME` and refuses to run during the historical opening
window. It creates a disposable saved persona and leaves it in the persona file.
`--reset-world` additionally requires WHO to show only that test persona, then
performs this operator command under RICHARD to supersede the shared world:

```text
RENAME DSKB:MUD.EXE[2011,2776]=DSKB:MUD.EXE[2011,2776]
```

The guest executable's `<055>` protection prevents MUDGUEST from performing
the original in-game same-name RENAME. Its reset routine can still print the
success message on failure, so the integration test uses the verified operator
operation and reconnects to the fresh world.

Verified at Friday 07:19 (after the historical 07:00 closure): an ordinary
MUDGUEST persona remained active for 330 seconds without a closing warning or
forced exit; `HOURS` retained the exact historical timetable without a DEMO
message; the saved persona/password worked on reconnect and after a world reset.
The saved test persona used for the full run was `Avdiviqm`. Evidence is in
`runtime/availability.log` and the operator transcript. This tested loading and
resetting the game executable, not a full emulator cold boot.

## Accounts and file protections

The local disk has:

- `RICHARD`, `[2011,2776]`: build/maintenance PPN.
- `MUDGUEST`, `[2653,2653]`: unprivileged, auto-runs
  `DSK:MUD.EXE[2011,2776]`.

Both are password-free **local development OS logins**. Persona passwords are
separate and handled by the original engine. The public network should reach
the browser gateway, not these operating-system logins.

REACT settings used: all login times and access types; no login requirements;
core limits `512 512`; context quotas `4 1000`; ENQ/DEQ quota `100`; IPCF quotas
`2 5 2`; DSKB structure quotas `INFINITE INFINITE 0`. REACT access types, login
times, requirements, and structure quotas are submenus, each closed with DONE.

The MUD executable and description/action files have protection `055`; the
persona file and writable `.DBA` files have `022`. Match the persona file with
`MUD.?PM`, and all generated data extensions with `MUD.??M` to handle the
embedded dot. All players execute the **same file in the same PPN**, sharing
its high segment; copying an executable per player would create separate worlds.

## Verification evidence and remaining acceptance work

- Original compiler smoke test passed.
- Original assembler, BCPL compiler, linker and DBASE runs completed.
- Source and prepared-file hashes verified before creating the baseline disk.
- Direct Telnet two-player shared-WHO/shout test passed.
- HTTP assets and two WebSocket players passed against the actual emulator.
- Browser-drop/replacement integration test passed.
- Two real Chromium tabs passed keyboard entry, shared WHO, cross-player shout,
  clean QUIT and page-error checks; screenshot: `runtime/browser.png`.

Host tests verify preservation/transfer/transport, not a second implementation
of game rules. Further gameplay acceptance should cover scoring and persistent
personas with nonzero scores, reset behavior, combat/PvP, mobiles/daemons,
wizard metadata, and disconnects during multi-step commands or combat.

Before increasing the test scope or changing game behavior, preserve a baseline
checkpoint. Prefer the original engine as the reference, not mud-web tests.
