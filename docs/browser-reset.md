# Original RESET through the browser

Browser sessions continue to use TOPS-10 `MUDGUEST [2653,2653]`. The original
engine authorizes and performs `RESET`; neither the gateway nor an operator
proxy intercepts the command. The permission change requires no game-code patch.

**External solo-wizard handover:** older external executables can reset the world
but then print “External handover unavailable; resolve pending persistence first.”
The adapter's allowed-target check incorrectly treated RESET's packed SIXBIT name
as a BCPL string. Preparation now uses native filename conversion, with core
original-engine and Chromium regression evidence on current main. See
[external reset handover](external-reset-handover.md) for the fix, remaining
acceptance limitations and executable-update requirement. PR #6's earlier external
acceptance covered a saved archwizard, which bypasses this transfer path.
Genuine unresolved persistence can still block transfer with that same message.

## Executable protection

The installed executable is `DSKB:MUD.EXE[2011,2776]`. Its old protection `<055>`
allows MUDGUEST to read/run it but not perform the same-name `RENAME` UUO used
by `resetgame()` (`source/MUDLIB.BCL:858–865,1702–1710`). The routine prints its
success message even when RENAME fails, explaining the contradictory success
message followed by “can't get at the .EXE file”.

The required standard protection is **`<051>`**. On the original TOPS-10 7.04
fixture, browser RESET failed at `<055>`, `<054>`, `<053>`, and `<052>` and
succeeded at `<051>`. Owner and project digits stay unchanged; MUDGUEST uses
the last, other-project access digit.

This is not a reset-only permission. TOPS-10's access levels are cumulative:
the other-project level also permits writing, deletion, renaming and changing
file attributes, but not changing protection. It applies to this one executable,
not the other game files. Guest Telnet/operator access must remain private;
the browser gateway continues to admit only game sessions, reject terminal
escape controls, fence queued commands and clean up at the monitor. There is no
browser maintenance-account login or new privileged reset endpoint.

For the monitor's access-level implementation, see `GETAC0`/`GTPRV` in
[FILFND.MAC](https://github.com/jguillaumes/tops10-705-sources/blob/master/10_7_mon/FILFND.MAC)
and `RENA11` in
[FILUUO.MAC](https://github.com/jguillaumes/tops10-705-sources/blob/master/10_7_mon/FILUUO.MAC).
Those are later 7.05 sources; the permission threshold above was measured on
the actual 7.04 runtime, rather than inferred from the later source alone.

## Configure an existing instance

Against the chosen **local** guest Telnet port:

```sh
.venv/bin/python -m tools.reset_permissions --port 2020
```

For `tools.serve_external`, use `upstream_port` from that instance's private
`ready.json`, not its browser HTTP port. The tool logs into the owning `RICHARD`
OS account, checks the directory entry, changes `<055>` to `<051>`, verifies
read-back, and logs off. It does not log into a persona or need a persona
password. Repeated runs at `<051>` are read-only. Unexpected protections are
preserved and reported for review. No executable or disk image is replaced.

The equivalent owning-account monitor command is:

```text
PROTECT DSKB:MUD.EXE[2011,2776]<051>
```

To restore the old file protection without restoring a disk/persona backup:

```sh
.venv/bin/python -m tools.reset_permissions --port 2020 --disable
```

AlmaLinux setup applies/verifies this setting after native provisioning or
external cutover and before gateway startup, including reruns. The local
external launcher checks it before admitting browsers. New external builds
also install MUD.EXE with `<051>`; support programs and world files retain
their existing protection. An old image rebuilt by other historical scripts
may reinstall `<055>`: rerun the permission tool afterward. Setup/launcher
reruns deliberately re-enable `<051>` after an explicit `--disable`.

The active local `runtime/external-local` instance at `http://127.0.0.1:8081`
was configured and verified idempotently on 2026-10-11. No remote deployment
was performed. The previous native `:2020` operator service was unavailable.

## Original policy and usage

- Ordinary players cannot issue RESET, including when alone. The `unlesswiz`
  action in `source/TXTBTM.GET:168–169` rejects it before the reset handler.
- An ordinary active wizard may reset when alone, but is refused when other
  players are present.
- The multiplayer exemption is exactly `maint /\ WIZARD`, as in
  `source/MUD5.BCL:716–732`. A saved archwizard authenticated under MUDGUEST
  obtains `maint` from `createprofile()`. A brand-new archwizard on its first
  admission does not: SAVE and re-enter before expecting that exemption.
- Reset is refused while the issuing player is fighting.

After an archwizard resets, existing sessions remain in the superseded world.
QUIT and reconnect to enter the fresh world. The ordinary wizard's solo path
uses the original quit-and-chain behavior; it need not print a new Hello.
World reset does not erase saved personas. Normal SAVE/QUIT persistence still
applies independently.

## Verification

```sh
.venv/bin/python -m unittest tests.test_reset_permissions -v
.venv/bin/python -m tests.integration_reset --output runtime/reset-new-check
.venv/bin/python -m tests.integration_reset_external --output runtime/reset-external-new-check
```

Both integration harnesses create isolated disks, private ports and disposable
credentials; they do not target the running game. `integration_reset` can also
reproduce the original failing test with `--protections 055`, or probe the
threshold with `--protections 055 054 053 052 051`.

Evidence:

- `runtime/reset-red`: original browser RESET failure at `<055>`.
- `reset-protection-probe` and `reset-protection-probe-2`: protection threshold.
- `reset-policy-final-2`: ordinary-player refusal, ordinary-wizard solo success
  and multiplayer refusal, archwizard multiplayer success and separate new-world
  WHO. FILCOM verified unchanged executable bytes and unchanged persona bytes
  immediately across the archwizard reset, before ordinary exit-time writes.
- `reset-browser-acceptance`: the same policy plus actual Chromium terminal and
  Chat RESET/reconnect and native fighting refusal passed. Its final KSYS timed
  out after BATCON started, so this is **behavior evidence, not a clean recovery
  image**. Earlier failed expectations and later startup/retry failures remain.
- `reset-external-verified`: external SAVE, saved Roy re-entry, multiplayer RESET,
  unchanged saved MariaDB records across RESET, separate new-world WHO, Chromium
  terminal/Chat reset/re-entry, full launcher restart, permission persistence and
  idempotence, and clean shutdown on both launches passed. Original source hashes
  remained unchanged.

Seven host tests cover directory parsing, idempotence, exact-file configuration,
unexpected protections, failed verification and reversal. Deployment and local
launcher host tests also passed: 74 focused permission/deployment/local-launcher/
gateway/keyboard-history tests in total in the original working checkout. The
three keyboard/history tests cover the user's existing arrow-key changes in both
terminal and Chat; those changes are separate from this permission patch.
The isolated PR worktree based on current main passed 82 focused permission,
deployment, external-deployment, local-launcher and gateway tests using the
existing macOS Python 3.9 environment. Installed systemd/VPS acceptance is separate.
