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

- Chat transcript copying serializes the selected visible DOM rows with explicit
  newlines, preserving blank rows, indentation and displayed wrapping. Keep native
  copying for input fields and selections extending outside the transcript.
  `tests/test_terminal.py` covers partial/backwards selections, Mode 7 wrapping,
  draft exclusion and an actual Chromium keyboard-to-clipboard copy.

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
  Input is edited locally and sent through the existing baud pacer on Enter.
  Only the engine echoes commands. Known login and PASSWORD prompts mask the input;
  no command history is stored. Disconnect/restart clears drafts and queued input.
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
