# MUD86 restoration

## Purpose and constraints

- Serve the supplied original MUD86 BCPL/MACRO-10 engine with a browser terminal.
- Preserve `source/` byte-for-byte. Generate into `build/`; use the original
  DBASE compiler for authoritative game data. Do not reimplement gameplay in JS.
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

- Chat appears directly after Default in Settings. It uses Default's font/colours
  and an expanding 80-column document transcript, with a fixed bottom command form.
  `web/chat.js` projects xterm's parsed buffer into text-only DOM rows, so CR,
  rubout and VT erase sequences retain their original meaning. The existing
  10,000-line scrollback limit still applies; there is no fixed-height viewport.
  Input is edited locally and sent through the existing baud pacer on Enter.
  Only the engine echoes commands. Known login and PASSWORD prompts mask the input;
  no command history is stored. Disconnect/restart clears drafts and queued input.
  Send Tab inserts a tab into the unsent Chat draft; the terminal modes send it
  directly. Switching to/from Chat requires confirmation even at the same 80×30
  parser geometry. Settings restores focus to the active input, not hidden xterm.
  `tests.integration_chat` checks real-game login/editing/INFO, saved-password
  reconnect, expanding output and Settings. It leaves a disposable saved persona.
- Terminal styles live in the Settings dialog and persist in browser localStorage.
  Original is the default: green, Menlo/Consolas, 16px, 80×30. VT220 uses white
  GlassTTY lettering at 20px, 80×24. BBC Mode 7 uses Bedstead at 20px, 40×25.
  BBC Mode 0 uses BBC Master-family bitmap lettering at 16px, 80×32; its
  source is VileR's CC BY-SA 4.0 Master 512-2y font, not an exact MOS ROM font.
  The old `bbc80` preference migrates to `bbc0`. These reproduce lettering,
  not BBC graphics or teletext control codes. Font provenance is in
  `web/vendor/GlassTTY-LICENSE.txt`, `Bedstead-LICENSE.txt`, and `BBCBitmap-LICENSE.txt`.
  `terminalReady` loads fonts before opening xterm and enabling style/Connect controls.
  Live font/colour changes preserve the session. Dimension changes during an
  active connection require confirmation; Cancel/Escape leaves the saved style
  and session unchanged. Confirm sends the reserved binary WebSocket `restart`
  control frame, clears queued input, and waits for gateway QUIT/KJOB cleanup
  before the socket closes and automatic reconnect applies the new dimensions.
  The binary control is never forwarded to the original game.
  Mode 7 deliberately uses TOPS-10/Telnet width 255, then `web/wrap.js` reflows
  original lines to 40 columns AFTER receive pacing. This avoids monitor-inserted
  breaks splitting words. Other presets use upstream width 80. Always set width
  before login, even when reusing a line. Wrapping stays fixed for the session
  alongside its dimensions, independent of live font/colour changes.
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
  via Tab in the terminal; the footer advertises this shortcut. Live browser tests
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
