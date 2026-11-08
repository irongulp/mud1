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
GitHub workflow execution supplies native validation. Results pending.
