# MUD86 Browser Edition 1.1.0 — release candidate

**Status: preparation, not published.** This application release follows the
`runtime-v1` clean-starter release. It retains that checksum-pinned disk/tape
dependency; no replacement historical binary is included.

## Intended changes since runtime-v1

- Browser Settings/About/Licences/Links, paced Chat input and Firefox autofill
  fixes; gateway heartbeat, password dispatch, redraw and disconnect cleanup fixes.
- Optional MariaDB persona persistence, one-way migration, schema upgrades,
  backup/recovery tooling and restricted SSH-tunnel SQL editing.
- Maintenance controls, read-only inspection, original browser RESET support and
  external solo-wizard handover correction.
- Pinned SIMH timer correction, updated Python/browser dependencies, deployment
  pip pin and certificate-account reuse on setup reruns.
- This candidate adds opt-in monitor/batch guards to deployment and private
  cutover, guarded managed restart/stop, final CI shutdown verification and
  banner-before-wakeup ordering. It corrects a smoke assertion for a witnessed
  native redraw without changing browser rendering or game output.

The original BCPL/MACRO-10 game remains authoritative. Native persona storage is
the default; MariaDB remains explicit and external-to-native conversion is not
supported. Independently authored restoration software remains GPL-3.0-only;
historical and vendor terms remain separate. Historical runtime redistribution
permissions remain under review as documented in [licensing.md](licensing.md).

## Recommended configuration to qualify

```sh
sudo ./setup.sh --domain your.mud.example --monitor-scope --batch-preflight
```

Both flags are **explicit opt-ins**. Omitting them on a fresh installation keeps
the historical/default startup path; omission on a rerun preserves recorded
choices. Batch preflight requires monitor scope. Selecting the guarded profile
does not select MariaDB. Add `--persona-storage mariadb` separately if desired.

The monitor wrapper is verified against the pinned live layout, allocated in
guest RAM, and reapplied each boot; it does not replace SYSTEM.EXE. The batch
check requires actual current-boot DAYTIME execution and logout before admission.
Guarded shutdown requires a semantic queue response before one KSYS request.
Failed/uncertain bootstrap blocks admission and automatic retry. Existing mutable
game disks and persona records are preserved. See [deployment.md](deployment.md).

## Consolidation scope

The release-preparation branch starts at merged main `50092ed` (PR16), rather
than merging an investigation branch wholesale. It retains the guarded runtime,
installer selection/cutover plumbing, managed lifecycle gates, carrier-ordering
fix and their regression tests. Native and external acceptance log failed
commands before raising, with credential redaction.

Excluded: memory/instruction-history capture, KSYS/private-response diagnostics,
experimental workflow modes, initializer changes, research images and outputs.
Companion source-transfer and full maintenance-logout changes remain on their
separate branch; they have not been silently incorporated into this candidate.

## Evidence and limits

- Follow-up consolidation from main `1a858df` brings in four production-file
  changes from diagnostic revision `50f47ce`: complete KJOB accounting/prompt
  verification, payload-free admission/logout facts, native midnight BIGBEN
  and DAYTIME parsing, and child-owned shutdown-marker publication. Existing
  deadlines, single dispatch, startup marker invalidation and failure gates
  remain. Childless cleanup returns false and preserves prior evidence.
  Ten additional host regressions bring the local host/Chromium suite to
  **531 passing tests**. Diagnostic fixtures and workflow modes are excluded.
- The retained [diagnostic chronology](https://github.com/irongulp/mud1/blob/50f47ce/docs/terminal-lifecycle.md)
  records both failures and controls. Corrected passive-only run
  [45233742866](https://github.com/irongulp/mud1/actions/runs/45233742866)
  completed four normal logouts, backup/restart and five clean service stops.
  It did not exercise failed-logout observation, midnight output or failed-boot
  double cleanup, and does not establish a fix for intermittent native stalls.
  Full acceptance must use the merged consolidation, not that diagnostic run.
- Consolidated local suite: **521 host tests passed**, including Chromium.
  The workflow passed actionlint1.7.12. Original source-tree diff is empty.
- Earlier candidate run [42380468514](https://github.com/irongulp/mud1/actions/runs/42380468514)
  passed fresh external setup/rerun/backup/restart/editor checks with six monitor
  and six batch proofs, and clean final shutdown.
- Comparison [42499025178](https://github.com/irongulp/mud1/actions/runs/42499025178)
  passed HTTP/HTTPS native browser tests with the initializer both enabled and
  disabled. It did not establish the initializer as the earlier failure's cause;
  this candidate leaves the native configuration unchanged.
- Earlier full runs had intermittent native admission and shutdown failures.
  Those failures remain relevant. Component passes are not a complete release
  pass and do not prove every failure is repaired.
- This exact consolidated commit still needs full native-x86 acceptance after
  review. The public ACME, enforcing SELinux and real VPS reboot checks remain
  target-host checks, distinct from container acceptance.

## Publication gate

### Full acceptance on merged lifecycle fixes: blocked

PR18 merged as `d0effa83aec6a9f035e180ac07e69ba18b65a0c7`, with the same
tree as the locally tested531-test candidate and successful PR CI45376505342.
Full guarded [run45377035352](https://github.com/irongulp/mud1/actions/runs/45377035352)
on24-Nov-2026 failed both jobs:

- **Native-upgrade:** initial install/rerun/backup and HTTP multiplayer passed.
  HTTPS smoke timed out waiting for the initial name prompt. At10:49:47 UTC,
  gateway connection `9731f6e…` reported `stage=monitor`,
  `admission_stage=monitor-response`, line0, `wakeup_submitted=True`,
  `monitor_seen=False`, one buffered response byte and `eof=False`.
  This localizes the failure to guest monitor admission; it does not establish
  a TLS fault or explain the byte. Cleanup queued KSYS, waited for BATCON
  at10:49:53, then timed out at10:51:22. Goodbye followed at10:51:24,
  without a final native KSYS completion. Reboot and cutover were not reached.
- **Fresh-MariaDB:** install, editor check, rerun, backup and three browser
  logouts completed (`recovered=False`). The next explicit `mud86ctl restart`
  failed its shutdown gate: BATCON wait at11:06:47, KSYS timeout at11:08:15,
  Goodbye at11:08:16. The guard refused reboot; the fourth admission and
  later editor/recovery matrix were not reached. This is a restart shutdown
  failure, not backup refusal or failed logout.

Both final markers retain `clean:false` and
`failure:{"phase":"ksys","error_type":"TIMEOUT"}`. Both services ended
inactive/dead with process exit0; that does not supersede native shutdown
evidence. Both final verification steps correctly failed. The two clean native
stops and three clean external service stops earlier in the respective journals
do not cover either failed final stop. No failure-only census or memory capture
was installed in this full acceptance.

Artifacts: native14913275408 (163,119 bytes), SHA256
`51134032a1a1f054e97cbba33e89a85480263121e5acbf94027cf5424ce2f0ce`;
external14914830356 (41,670 bytes), SHA256
`17dc56682b509f28a3db912c9a3c3b433c3c0b5a260f7bcc93197d335edb1dfc`.
Extracted reports, service journals and workflow log are retained privately at
`runtime/release-1.1-acceptance-20261124/`.

No tag/release or unchanged rerun follows this result. Next investigation should
use the existing admission boundary and separately qualified KSYS state capture
to choose a bounded, decisive experiment. The wait message alone does not prove
BATCON absence, and the two symptoms have no established common cause. Current
evidence is insufficient to select a new production fix.

### Required before publication

1. Review and merge the intended implementation; retain previous failed evidence.
2. Run both independent deployment scenarios on the exact intended release
   commit with `guarded_profile=true`. Native-upgrade retains the end-to-end
   native/HTTP/HTTPS/reboot/populated-cutover sequence; fresh-MariaDB runs
   independently. Both require final clean shutdown. No retries-until-green.
3. Investigate any remaining genuine failure. A green focused test or another
   scenario passing does not waive a failed release check.
4. Finalize these notes and upgrade guidance, tag the validated pushed-main
   commit as `v1.1.0`, and publish. Until then, do not mark this candidate released.

Passing guarded acceptance makes claims only about that explicit configuration;
it does not automatically validate the unguarded installer default. To test the
default separately, dispatch with `guarded_profile=false`.
