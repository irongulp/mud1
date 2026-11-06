# Companion source-transfer qualification

Base: merged PR16 (`50092ed`). The failed comparison baseline stopped uploading
PMSNAP source, waiting for a newline under SnapshotInspector's 600-second bound.
Its later KSYS stream began but did not complete; these are distinct failures.

Companion installation now checks each complete ASCII/tab-expanded line echo,
retains line/phase/count/submission facts without raw terminal buffers, and uses
a ten-second echo/completion bound rather than the snapshot-data timeout. It
never resends an uncertain line. Complete rendered source read-back uses the
existing source-suffix-aware verifier before compilation. This is a validation
improvement, not proof of the original timeout's cause. Persona records remain
outside diagnostics. Shared external-engine transfer is unchanged.

Focused `companion_transfer=true` CI uses a fresh pinned runtime copy, deployed
timer-corrected SIMH and native-x86 AlmaLinux. It only uploads, reads back and
compiles PMSNAP, never executes it or reads persona records. No external engine
build or MariaDB is involved. One boot/transfer/shutdown attempt, no retries.

Run 42289501018 (`0b2c7d0`) passed native PMSNAP transfer/read-back/compilation,
then timed out waiting for KSYS completion after BATCON started stream32. Native
Goodbye/exit occurred, shutdown remained unconfirmed. This qualifies the transfer
in that run, not a clean lifecycle or repaired original intermittent timeout.
The fixture initially lacked host `ps`; include deployment's procps-ng package
for parity. The follow-up adds one read-only SYSTAT after maintenance cleanup
before KSYS to check whether the maintenance job is actually gone. Neither
change claims a native shutdown fix or replays prior input.

Run 42290347736 (`4ce8418`) passed upload/read-back/compile and clean KSYS. Its
immediate post-maintenance census still showed RICHARD job12 in LOGIN after the
inspector returned: `Logged-off` is only the beginning of logout, not completion.
The earlier reliability commit9347897 had a complete accounting/prompt predicate
which was not present in merged main. The maintenance inspector now waits for
the final monitor prompt and requires the ordered Logged-off/accounting tail.
Red/green tests reject a prefix or bare prompt and preserve connection closure.
This is a concrete host cleanup correction, not proof of the original transfer
timeout or a universal BATCON fix. Native census follow-up checks actual removal.

Run 42291004125 (`73c714d`) passed verified upload/read-back/compilation, the
complete logout predicate and native KSYS/Goodbye. Immediate SYSTAT still showed
RICHARD12/LOGIN, so complete logout output does not imply immediate job removal.
Do not attribute the original shutdown failure to this residual job on that
evidence. No persona records were read by either focused fixture.

Full deployment run 42291522591 at the same commit passed host/Chromium tests,
native installation/rerun/read-only inspection, saved-persona re-entry, native
backup/restart and HTTP multiplayer. Native sleep/wake measurements were
5.979/6.022/5.977 seconds. It then failed initial HTTPS browser admission at
`stage=monitor`, before native-to-MariaDB cutover. HTTPS/static content reached
the browser, but the gateway's initial guest-monitor wait timed out.

The service journal recorded STOMPR starting at21:00:02, a TTY0 quieting failure
at21:01:02, then the gateway monitor timeout at21:01:25. Shutdown completed
normally at21:01:32. This correlation supports a focused native terminal-reuse/
initializer investigation, not a demonstrated TLS failure or proven STOMPR cause.
No unchanged full-matrix rerun was launched. Original failures remain retained.

Current scope: companion transfer validation and complete maintenance logout
have focused native acceptance and 57 relevant host tests. Full release
acceptance remains failed; external deployment on this exact patch is not yet
qualified. Neither batch warmup nor experimental monitor/sampling code is included.
The next targeted check is repeated native terminal admission/cleanup across
the STOMPR interval, capturing terminal assignment/state before any intervention.
