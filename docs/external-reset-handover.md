# External solo-wizard RESET handover

## Fix on current main

Review branch `fix/external-reset-handover-review` starts at main `c22828f` (PR #11's
SIMH timer merge). PR #6's reset permissions are already present in that base.

The original ordinary-wizard RESET path performs `resetgame()` then
`quit(mud6, !room)` (`source/MUD5.BCL:716–732`). `mud6` is a packed SIXBIT
filename; ordinary CHAIN and portal targets can instead be BCPL strings.
`chain.allowed()` used `seq(target,"mud")`, dereferencing the packed value as
a string pointer. The world reset succeeded but the player's transfer failed,
even with no pending SAVE.

`tools/prepare_chaining.py` now generates:

```bcpl
and chain.allowed(target)=sixbit(target)=$6"mud" \/ sixbit(target)=$6"valley"
```

This is the same native filename conversion used by `chain.out()` and RUN.
Only explicit `--chain-target` values are allowed; a `valley`-only configuration
does not silently permit `mud`. The original `source/`, RESET authorization,
native-only build, persona schema and handover packet remain unchanged. Existing
lifetime, pending SAVE/PURGE resolution, seed budget and confirmed-checkpoint
guards remain in place.

## Executable updates

This changes the **generated external adapter**, so existing installations need
an executable rebuilt from corrected preparation. A Python update or gateway
restart alone does not change the loaded guest executable. Retain PR #6's
`MUD.EXE<051>` permission. Rebuild each compatible image that needs the corrected
allowlist. Do not replace a mutable game disk with a test disk.

No running local game or VPS was changed during this work. The narrow test
builder below is an isolated fixture builder, not an installer, and no replacement
historical binary was published.

## Tests and reproduction

The two new host regressions fail with the old generator and pass with the fix.
They cover the original packed RESET call, filename-based target checks, explicit
allowlist scope, and retention of persistence guards. Native-only preparation
continues to pass its existing independence test.

Run host checks with the current Python 3.12 dependencies:

```sh
python -m unittest tests.test_prepare_lifecycle -v
```

The opt-in integration harness requires an explicit stopped external always-open
fixture and a separately built `active-tick-v1` SIMH binary. It verifies the timer
source checksum and records the selected binary hash. It copies the disk to a
new output directory and owns its private MariaDB, player names and ports. Keep
output paths short enough for macOS's Unix-socket limit.

```sh
# RED: against the old executable, fails with the user's exact message.
python -m tests.integration_reset_handover \
  --output /path/to/runtime/xrm-red \
  --source /path/to/stopped-external/guest.dsk \
  --simulator /path/to/active-tick-v1/BIN/pdp10

# Build the corrected adapter in the copied guest, then test it.
PLAYWRIGHT_BROWSERS_PATH=/path/to/current-playwright-browsers \
python -m tests.integration_reset_handover --build \
  --output /path/to/runtime/xrm-check \
  --source /path/to/stopped-external/guest.dsk \
  --simulator /path/to/active-tick-v1/BIN/pdp10
```

The builder expects the verified fixture's `X24LIB.BCL`, original REL modules
and retained `PMHOLD.PM`. It changes only the generated allowlist line, verifies
the complete rendered guest source, compiles with original BCPL, and relinks
without rerunning DBASE. It checks the **current**, not initial, LINK high counter
against DBADAT `520000`, preserves ROBOOT at `140`, and uses FILCOM on retained
native persona bytes. A separate compiled BCPL probe accepts string/packed MUD
and VALLEY, upper-case MUD, rejects string/packed OTHER, and verifies packed
SWAMP1 conversion.

The harness creates an ordinary wizard through a private `MUD.WIZ`, SAVEs it,
and resets at SWAMP1. It checks room, WHO, password preservation and absence of
superseded output. Chromium terminal and Chat additionally require the same
WebSocket and unchanged GAMES. Subsequent scenarios cover dropped committed
SAVE/PURGE replies, recovery without replay, failure of an exit checkpoint,
normal string-target portal chaining and saved login after a cold reboot.
Completion is reported only if all checks and both KSYS shutdowns pass.

## Current-main evidence and limits

Private evidence is under `/Users/etimbo/code/mud-server/runtime/`:

- `xrm-red`: reproduced the exact handover error with a confirmed saved ordinary
  wizard. No pending SAVE was needed to trigger it.
- `xrm-green2`, `xrm-green3`, `xrm-verify`: original BCPL allowlist probe passed;
  allowlist-only library build/link and retained-native-persona FILCOM passed.
  Code ended at `507776`, below unchanged DBADAT `520000`.
- `xrm-green3` and `xrm-verify`: solo ordinary-wizard native handover and Chromium
  terminal/Chat passed on the current-main host code, Python 3.12.15, pinned
  Playwright 1.63.0 / Chromium 153.0.8010.12 and the verified active-tick-v1 SIMH.
  Both browser modes kept one WebSocket and unchanged GAMES, and arrived at SWAMP1.
  The native saved password comparison passed.
- `xrm-green3` then timed out waiting for BATCON after one KSYS submission. It is
  behavior evidence, not a clean recovery image. `xrm-verify` reached fault-test
  setup but hit a test prompt expectation when leaving wizard mode; the harness
  now expects the mortal prompt at that transition.
- Subsequent `xrm-verify2/3`, `xrm-final`, `xrm-seq` and `xrm-control` attempts
  encountered startup/admission failures before the extended checks could run.
  Preserve them; their causes have not been established. A different simulator
  candidate was rejected by the exact source-checksum gate before boot.

**The extended pending-operation, portal and restart sequence has not completed
on current main in this session.** Earlier research on the prior branch passed
those controls (`xreset-faults-verified`, `xreset-browser`, `xreset-arch`), but
those reports are not substituted for current-main acceptance. No failed disk
was promoted, no uncertain shutdown input was replayed, and all owned test
emulators exited.

The current-main focused preparation/persistence/permissions/bootstrap/local
launcher/gateway/terminal suite reported **165 tests passed**. Its outer command
deadline fired just after the unittest OK summary; the relevant host/browser
results are complete, but this is distinct from native fixture shutdown.
Original source files remain unchanged. Full clean current-main native acceptance
and installed-systemd/VPS deployment remain follow-ups.
