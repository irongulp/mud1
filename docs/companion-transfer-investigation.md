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
