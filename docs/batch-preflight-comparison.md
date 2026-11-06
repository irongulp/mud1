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

## Result: stop boundary reached, comparison inconclusive

Single native-x86 dispatch [42280761217](https://github.com/irongulp/mud1/actions/runs/42280761217)
at `6f5b0a4` completed both arms. No rerun was launched.

- Baseline stopped in setup: `capture_personas` timed out during PMSNAP source
  transfer (`install_source` waiting for a newline), followed by unconfirmed
  cutover shutdown. Its report is `complete:false, phase:setup`; it never reached
  the intended external saved-login/idle/shutdown workload. This is not the target
  shutdown reproduction and cannot establish a preflight benefit.
- Candidate completed external installation, ordinary SAVE/QUIT, 660-second idle,
  saved re-entry/QUIT and clean shutdown. The final journal contains native
  `20:03:30 -- BATCON logging out --` / `All streams have been idle for 10 minutes`,
  then `20:05:00 -- Event KSYS queued --`, waiting for BATCON, and
  `20:05:01 -- KSYS processing completed --`, followed by Goodbye/service exit.
  Thus actual idle logout and later successful demand startup were observed.
- OPR delivered the queued idle-logout notice only when shutdown opened OPR;
  the report's pre-stop `idle_messages` list contains only CPU-idle accounting.
  The post-stop native journal, not that list or host elapsed time, is the
  authoritative idle-logout evidence. Native timestamps are observations, not
  performance guarantees or clock calibration.

Artifacts: `batch-result-baseline`/`batch-result-candidate` contain reports;
`batch-comparison-baseline`/`batch-comparison-candidate` retain journals and
installer output. Host validation passed 39 focused tests and workflow lint
(excluding pre-existing unused loop-variable warnings). No full release
acceptance was run, and the candidate is still opt-in on this research branch.

Conclusion: one positive native candidate result, no matched causal result.
Per the stopping rule, leave production/main unchanged and report the blocker;
do not adopt the candidate or publish v1.1.0 on this evidence alone.
