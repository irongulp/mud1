# Native terminal-initializer comparison

Base: pushed guarded-deployment candidate `8e6352a`; main remains separate.
The repeated native HTTPS smoke failures followed HTTP sessions and a STOMPR
TTY0 quieting error, including after the banner-before-wakeup correction. External
installations already disable STOMP through verified guest configuration. This
comparison tests the remaining configuration difference; it does not assume
STOMPR caused every prior failure.

Explicit workflow input `initializer_comparison=true` creates independent
native-x86 AlmaLinux arms named enabled and disabled. Both use the same source,
runtime and simulator pins, monitor/batch guards, one CPU/two GiB, native persona
storage, native install/rerun/backup, HTTP browser and subsequent HTTPS browser
workload. Each arm stops at its first failed operation; no test retry.

After native setup, the management command must confirm shutdown. The private
fixture takes the installed runtime lock and requires the guarded/native metadata
and clean marker before opening the disk. Both arms boot and verify original
STOMP configuration plus the running initializer. Only the candidate uses
`protect_bridge_terminals()` to stage, verify, back up and replace SYS:TTY.INI
with its STOMP line removed; all other settings are preserved. Both arms then
perform the same clean reboot, verify their expected configuration and process
state, and stop cleanly before restarting normal services. Hashes/process-state
proof and private operator console are retained. No production default or live
disk is modified. Failure of either shutdown forbids the next boot.

The browser workload is the existing HTTP multiplayer/editing/QUIT/reconnect
test followed by the existing HTTPS fixture and browser test. Final diagnostics
retain service stages and the native clean marker; unclean final shutdown fails
CI independently. Startup clocks/runners may differ, so this is source/profile-
matched functional evidence, not a controlled performance benchmark.

Unit tests cover matched reboot counts, candidate-only configuration change,
verification of original/selected state, and no reboot after failed shutdown.
23 focused tests passed locally. Docker was unavailable locally for actionlint;
GitHub workflow execution supplies the native results below.

## Result

Single native-x86 run
[42499025178](https://github.com/irongulp/mud1/actions/runs/42499025178) at
`28669d4` passed both arms. Each completed native installation/rerun/backup,
the matched configuration/reboot preparation, HTTP multiplayer/editing/reconnect,
HTTPS multiplayer/editing/reconnect and verified final native shutdown.

- Enabled arm: original/after configuration hash
  `09bb64fb6f96f7f1a275432996aebcb46c23906800107ffb78db06369fa7a70f`;
  STOMPR positively observed running after reboot.
- Disabled arm: same original hash; after hash
  `8a33d861b4cc232da7ba8a1c9bb854c184ddb082ecfee65b554d699d504ddee5`;
  STOMPR absent after reboot.
- Both configuration and final shutdown markers were clean. Retained service
  journals had no shutdown failures, retry messages, gateway warnings or TTY
  quieting errors. Artifacts are `initializer-enabled` and `initializer-disabled`.

Conclusion: configuration application and both workflows succeeded in this
comparison, but the original failure did not reproduce in the enabled control.
There is no demonstrated causal benefit from disabling STOMP and no production
default change is justified by this result alone. Additional equal reboots in
both arms, runner scheduling and world state differ from earlier full runs;
do not attribute the pass to any one of those differences without evidence.

This is not the full release matrix: populated native-to-external migration,
fresh external deployment and the broader database checks were not exercised by
this job. No unchanged rerun or additional initializer modification followed.
Main remains unchanged and v1.1.0 remains unpublished. The practical next release
gate is review of the accumulated candidate and validation of the intended
installed profile, keeping intermittent admission failures explicitly tracked
rather than claiming the initializer comparison resolved them.
