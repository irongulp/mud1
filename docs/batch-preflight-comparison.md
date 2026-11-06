# Bounded batch preflight comparison

Base: merged PR16, `50092ed`. This branch contains no experimental admission
refactor, simulator sampling, monitor patch or BATCON replacement.

Hypothesis: requiring actual batch execution before MUD admission avoids the
observed demand-controller loading failure at shutdown. This is an opt-in
mitigation candidate, not a claimed native allocator repair.

`--batch-preflight` runs the same bounded native executor as the local launcher,
with a fresh boot ID, exact request/log identity, actual DAYTIME result and batch
logout required. Local monitor authority remains in its existing wrapper.
Production setup does not opt in. Runtime bridge ports remain local to boot and
are tested through the real external-admission path. Failed proof/publication
blocks admission and in-process boot retries. Candidate CI uses Restart=no.

One manual dispatch with `batch_comparison=true` runs two independent native-x86
AlmaLinux containers, one CPU/two GiB each, with identical starter/simulator/code
and external installation/login/SAVE/QUIT workload. Candidate alone adds the
preflight flag. Both idle 660 seconds, perform saved re-entry/QUIT and submit one
normal shutdown. Both disable automatic systemd restart. No memory capture or
command replay is used. Full journals retain actual controller idle messages;
elapsed time alone must not be described as observed idle logout.

Stop rule: each arm stops at its first setup/readiness/input failure; no repeated
installation or experimental edit/rerun cycle is authorized by this comparison.
An unrelated failure or missing idle-logout evidence makes the comparison
inconclusive. A candidate pass without a reproduced baseline failure does not
prove causal improvement. Native failures retain their original artifacts.

Only if the comparison supports the mitigation should a reviewed adoption patch
and full deployment acceptance follow. No v1.1.0 publication is implied.
