# Essex MUD86 — original engine, browser access

A working local restoration of Essex MUD86. Gameplay runs in the original
BCPL/MACRO-10 executable under SIMH and TOPS-10 7.04. The browser is an xterm.js
terminal; the Python server only bridges WebSocket and Telnet connections.

## Licensing

The independently authored restoration software is **GPL-3.0-only**; see
[LICENSE](LICENSE) for scope and [COPYING](COPYING) for the full terms. The
original MUD source/world retains its **custom not-for-profit terms** and is
not relicensed by that GPL grant. Vendor assets retain their own licences.

**Historical runtime redistribution review is incomplete.** Runtime-v1 remains
downloadable at the maintainer's direction with this notice, but the applicable
permissions for the bundled TOPS-10/DEC and BCPL components have not been
established by this review. See [THIRD_PARTY.md](THIRD_PARTY.md),
[NOTICE](NOTICE) and [docs/licensing.md](docs/licensing.md).

## Repository and branch

This is the `main` branch of
[irongulp/mud1](https://github.com/irongulp/mud1), a fork of
[PDP-10/MUD1](https://github.com/PDP-10/MUD1). It starts from upstream revision
`8d2ce6ee5ca1ae3d835538de20aeb87acaae3df1`. The historical game files at the
repository root retain their upstream contents; `source/` separately preserves
the supplied restoration archive used by the existing preparation tools.
The fork's `laravel` branch retains the earlier migration work.

A fresh clone includes the source, browser assets and licences, gateway, tests,
and restoration tools. The restored guest disk, personas, local logs, downloaded
media, build outputs and Python environment are **not** in Git. The AlmaLinux
installer downloads a checksum-pinned starter runtime and generates credentials
locally. The local playing instructions further below use the restored development
runtime described in [docs/restoration.md](docs/restoration.md).

## Install on AlmaLinux 9

On a fresh VPS, point `mud.etimbo.com` at the server and allow TCP 80/443 in the
provider firewall. From the checkout, run:

```sh
sudo ./setup.sh --domain mud.etimbo.com
```

Setup installs the original 24/7 game, provisions all seven archwizards, configures
Nginx/HTTPS and installs boot-persistent systemd services. Copy the displayed
credentials into a password manager. Reruns preserve existing game data and
passwords. Use `sudo mud86ctl status`, `restart` or `backup` afterward.

Read [docs/deployment.md](docs/deployment.md) for DNS, certificate email, persistence,
backup behavior and the exact validation scope.

## Play on this checkout

Open **http://127.0.0.1:8080**; the terminal connects automatically. Choose a persona name,
press `m` or `f` when asked for sex, and enter a persona password. Try `look`,
`who`, `west`, or `shout hello`. Separate tabs are separate players in one world.
`quit` ends the game and the gateway logs out the terminal. The browser then
reconnects to the persona prompt automatically. Close the tab when finished.

In Chat mode, select transcript text and use normal Copy (Ctrl+C / Cmd+C or the
browser menu). Plain-text copies retain the displayed line breaks, blank lines,
indentation and wrapping, including Mode 7's 40-column layout. Partial selections
copy only the selected text; unsent commands are separate from the transcript.

Reconnecting preserves the transcript, selected style and baud rate, and waits
for queued output to finish displaying. Queued keystrokes are discarded. Pending
terminal widths apply on reconnect. Failed connections retry with exponential
backoff from one second up to 30 seconds, with a message in the terminal.

Switching among the 80-column styles (Default, Computer Centre on Square 2,
DEC VT52, IBM PC MDA, IBM PC CGA, and BBC Micro Mode 0) applies immediately,
including the new visible row count, without
ending the session. Switching to or from 40-column BBC Micro Mode 7 opens a
confirmation dialog, as does toggling Chat mode.
**Cancel** (or Escape) keeps the current session and setting. **Change settings and
reconnect** ends the session through the gateway's logout flow and automatically
reconnects with the new style. You then enter your persona name to rejoin the game.

Additional period display presets work in both terminal and Chat modes:

| Preset | Terminal layout | Lettering and colour |
|---|---|---|
| DEC VT52 | 80 × 24 | ROM-extracted VT52 font, white on black |
| IBM PC MDA | 80 × 25 | MDA 9×14 font, green on black |
| IBM PC CGA | 80 × 25 | Thick CGA font with doubled vertical pixels for 80-column text, light grey on black |

These are display presentations; the upstream VT100-compatible terminal protocol
is retained for game input and editing. Font attribution, licences and SHA-256
hashes are in `web/vendor/VT52-LICENSE.txt` and `web/vendor/IBMPC-LICENSE.txt`.

Press **Tab** while the terminal has focus to select
a simulated connection speed: **9600** directly wired (the default), **300/300**,
or **1200/75** dial-up. The pair means receive/send baud: 1200/75 displays up to
120 characters per second and sends typing at 7.5 characters per second.
The browser approximates 10-bit serial framing in both directions; the emulator
retains its 9600-baud configuration, and slower upstream output can still limit
the effective rate. Each browser has its own selection, retained on reconnect
but reset on page reload. Switching speeds also changes the rate of queued text.
The modal has **Settings**, **About**, **Licences** and **Links** tabs. Settings
is selected each time it opens. About explains the game's history and the original
engine/browser setup, and credits Tim Rogers's browser server version built using
OpenCode and GPT-6 Astra. Licences displays the notices inline, with links to the
full texts and source. Links lists historical and restoration resources, beginning
with Richard Bartle's website; resource links open in a new browser tab.

**Tab**, **Escape** or **Return to game** closes the modal. When a tab heading is
focused, Left/Right arrows and Home/End select a section. **Send Tab to game** is
available in Settings to forward a literal tab if needed. Long panels scroll
inside the modal, keeping the tab strip and return button visible.

The restored disk and dependencies have already been created locally. When the
services are stopped, restart them from this directory:

```sh
python3 tools/boot.py
python3 tools/serve.py
```

`boot.py` starts the operator-console process and waits for TOPS-10 to boot.
`serve.py` starts the browser gateway in the background and prints its PID.
For a foreground gateway instead:

```sh
.venv/bin/python -m server.gateway
```

### What is running

```text
Browser / xterm.js
    → WebSocket :8080
    → Python transport gateway
    → Telnet / emulated DZ terminal :2020
    → Original MUD.EXE on TOPS-10 7.04
    → Shared world, original actions, timers, combat and persona files
```

Both network listeners bind to **127.0.0.1**. This checkout is a local prototype,
not a public deployment. A remote deployment needs a hostname/TLS reverse proxy
for the gateway and an operational account/session policy. The operator and
emulator interfaces are separate from the browser service.

## Fidelity and current boundaries

### First-install archwizard protection

Before opening a new installation to players, use
[`tools/provision_archwizards.py`](docs/archwizard-provisioning.md) to create and
SAVE all seven archwizard personas with private, compatible generated passwords.
The standalone command takes an explicit private Telnet port and retains initial
credentials in an owner-only journal. Reruns preserve existing personas and
report changed credentials instead of resetting them. `--show-credentials`
prints known matching passwords for copying to a password manager.

Richard's credential is for **ATTACH**, not ordinary direct login. Attached
SAVE or a qualifying QUIT can replace it with the originating persona's password;
the provisioner detects that change on rerun. See the
[provisioning guide](docs/archwizard-provisioning.md) and
[native password audit](docs/archwizard-password-audit.md).

### Restoration boundaries

- `source/` remains the supplied archive. Its hashes are recorded in
  `docs/provenance.json` and were verified before checkpointing.
- `build/mud86/` is a generated source tree. Archive delimiters were removed,
  embedded source files recovered, and missing build/auxiliary files supplied
  from a pinned restoration repository. The game rules were not rewritten.
- The **original DBASE program** generated the world and action records.
  Its successful run reported **420 rooms, 482 object instances, 207 classes,
  253 object vocabulary entries and 16 motion words**. These are different
  kinds of counts, not interchangeable totals.
- The engine and database compiler assembled/compiled and linked successfully.
  Two ordinary guest sessions passed shared `WHO` and shout tests. Two real
  Chromium tabs passed the same checks through the browser interface.
- These smoke tests establish a working original engine and transport. They are
  not an exhaustive playthrough of every trap, combat branch, daemon or puzzle.
- The upstream `.DBA` books/help/writings are supplemental historical assets;
  their exact provenance relative to the supplied MUD86 snapshot is not proven.
  The original wizard metadata file `MUD.WIZ` has not been recovered. Wizard
  promotion and all persistence paths still need dedicated acceptance tests.

### Opening hours and disconnects

The installed development executable has the **24/7 availability fix**. It
bypasses the opening-hours check while preserving the historical `HOURS` output,
load checks and other game rules. `tools/prepare.py --always-open` reproduces
the patch in generated code; default preparation remains historical and the
supplied archive stays intact. See the build and out-of-hours test evidence in
[the restoration record](docs/restoration.md#local-247-availability-build).

The normal boot script still starts the **guest clock at Friday 18 September
2026, 03:00**. Guest time advances normally afterward; `--date` and `--time`
control the boot clock. The earlier `first-playable` checkpoint predates the
24/7 patch and is not a packaged 24/7 deployment image.

The gateway treats an established browser disconnect as a request to `quit`,
then issues TOPS-10 `KJOB`. It keeps the terminal connection until that cleanup
finishes. Incomplete persona entry is interrupted instead. This is an explicit
hosting policy; the original engine still decides whether a quit is allowed.
Cleanup during combat or other multi-step interactions is not fully verified.
A failed cleanup is logged and may require an operator to clear the guest job.
New connections must reach the original persona prompt before game output is
forwarded, so a stale terminal is not handed to a different browser.

## Files

| Path | Purpose |
|---|---|
| `source/` | Supplied historical archive, preserved |
| `tools/prepare.py` | Source extraction, include validation, hashes and upstream diff |
| `tools/source_tape.py` | 7-bit PDP-10 source transfer tape, **not** a game interpreter |
| `config/pdp10.ini` | Verified emulator boot configuration |
| `tools/boot.py`, `tools/console.py` | Boot driver and local operator console |
| `server/gateway.py` | WebSocket/Telnet transport and terminal lifecycle |
| `web/` | Browser terminal; no gameplay implementation |
| `docs/restoration.md` | Build procedure, dependencies and actual restoration findings |
| `docs/provenance.json` | Source hashes, origins and checkpoint disk hash |
| `runtime/disks/tops10-704.dsk` | Mutable guest disk: OS, compiler, sources and compiled game |
| `runtime/checkpoints/first-playable/` | Stopped-machine baseline disk and manifest |
| `runtime/console.log`, `runtime/web.log` | Operator and gateway diagnostics |

Generated images, dependencies, test transcripts and browser screenshots are
ignored by version control. They are local artifacts, not automatically
reconstructed by checking out the application files.

## Host setup

Tested with macOS arm64 and Python 3.9. The standalone legacy Telnet smoke test
uses standard-library `telnetlib` and needs Python 3.9–3.12. The gateway uses
`telnetlib3` instead.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
python3 tools/fetch_terminal.py
```

For a fresh machine, follow [the restoration procedure](docs/restoration.md)
to obtain/build SIMH and create the guest disk. The source-preparation step does
not by itself install TOPS-10.

## Small-server hosting

The [idle/hosting investigation](docs/hosting.md) measured roughly 17–18% of
one Apple M5 core with idle handling and faster terminal transport, including
eight paced WebSocket players. A 1-vCPU/2-GB Linux VPS is a sensible trial size.
The new idle profile remains **experimental** because startup and pause/resume
verification also stalled; it has not replaced the current live configuration.
The report contains the measurements, limitations and reproduction commands.

## Verification

```sh
# Host-side tests: source preservation, tape encoding, gateway isolation/lifecycle
.venv/bin/python -m unittest discover -s tests -v

# Original engine must already be running
python3 tests/integration_multiplayer.py
.venv/bin/python -m tests.integration_web

# Real browser test; also requires the gateway on :8080
.venv/bin/python -m pip install -r requirements-dev.txt
PLAYWRIGHT_BROWSERS_PATH="$PWD/runtime/browsers" .venv/bin/python -m playwright install chromium
.venv/bin/python tests/browser_smoke.py
```

The integration tests create disposable zero-score personas and quit them.
Original MUD may report `Not updating persona` for such personas: this is its
own behavior. The Chromium test writes `runtime/browser.png`.

## Operator console and shutdown

Read pending console output:

```sh
python3 tools/console.py
```

Send terminal input (`\r` is Return, `\x03` is Control-C, `\x05` is SIMH's
Control-E escape):

```sh
python3 tools/console.py --send 'exit\r'  # OPR> to the TOPS-10 monitor
python3 tools/console.py --send 'systat\r'
```

For shutdown, first stop accepting browser sessions (stop the gateway process
whose PID is in `runtime/web.pid`). At the TOPS-10 monitor run `r opr`, then
`set ksys now` and wait for `KSYS processing completed`. Exit OPR and `kjob`.
Finally stop SIMH:

```sh
python3 tools/console.py --send '\x05'
python3 tools/console.py --send 'quit\r'
```

Back up a disk only with SIMH stopped. The baseline checkpoint can be copied to
`runtime/disks/tops10-704.dsk` to return to the initial restoration, but doing so
replaces any later personas and guest-file changes. Keep those changes first.

## Attribution

MUD: Roy Trubshaw and Richard Bartle, Essex University, with additional authors
credited in individual source files. Preserve those notices. The pinned
restoration repository records Bartle's not-for-profit release terms. SIMH,
xterm.js, TOPS-10 and the compiler retain their respective notices/terms.

The [upstream README](https://github.com/PDP-10/MUD1/blob/8d2ce6ee5ca1ae3d835538de20aeb87acaae3df1/README.md)
records Richard Bartle's release terms of 18 May 2020:

> This means you can do pretty well what you want with it except make money,
> and if you give it to other people they have to follow the same restrictions.
