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
