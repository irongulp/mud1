# SIMH active-interval timer correction

Deployment builds pinned SIMH revision
`47b7ddabbe5b548cfc32f2fd45f7bed238ff7921` with the host-side
`active-tick-v1` correction. The correction is extracted from the independent
reliability work in commit `447f945`.

## Defect and correction

The pinned PDP-10 timer interpolates RDTIM between interrupts using:

```
elapsed = tick_in_usecs - remaining_time_of_scheduled_tick
```

WRINT changes `tick_in_usecs` for the **next** scheduled interval. If it changes
while the current interval is active, the calculation subtracts the old
remaining time from the new duration. A shorter next interval can therefore
make RDTIM go backwards; a longer one can jump it forwards without elapsed time.
Native TOPS-10 observations included impossible CPU accounting, and one private
unpatched trace contained eight backwards readings among 5,887 complete RDTIM
records, excluding explicit WRTIM resets.

`tools.simh_timer` preserves the duration of the active scheduled interval in
`tim_active_tick_in_usecs`. Reset initializes it; timer service updates it when
scheduling the next interrupt. WRINT still controls the next interval. The
correction does not change the throttle, guest schedule, or historical engine
and disk bytes.

## Build and cache selection

`tools.deploy.build_simh()` applies the correction before compiling and selects:

```
/opt/mud86/simh/<revision>-active-tick-v1/BIN/pdp10
```

Existing `<revision>` caches are retained. A setup rerun selects the new path
through the normal installer/service configuration; running processes are not
changed merely by adding this code. Existing game disks are not replaced.

Both original and corrected timer source SHA-256 values are pinned. Cache reuse
requires the pinned Git revision and corrected timer bytes. Changed cached
source is rejected without modification; these checks are not binary attestation.
The installer retains its existing single-build-job policy and disables SIMH's
automatic package installation.

For a separate local SIMH checkout at the pinned revision:

```sh
python -m tools.simh_timer /path/to/independent/pinned-simh
make -C /path/to/independent/pinned-simh pdp10 USEFUL_PACKAGES= OPTIONAL_PACKAGES=
```

Local launchers using another executable must explicitly select the resulting
binary. Do not patch/rebuild the source tree supplying an active emulator.

## Validation and limits

- The compiled deterministic regression uses pinned scheduling/interpolation
  statements and a fake scheduler to exercise WRINT between ticks. It verifies
  failure of the original calculation and success with the correction, including
  shorter and longer next intervals.
- Unit tests cover exact source checksums, idempotence, unsupported revisions,
  separate-cache selection, patch-before-build ordering, reuse, and rejection of
  changed cached source without modifying it.
- A disposable native-ARM AlmaLinux 9.8/Python 3.12.15 container exercised the
  actual deployment build function from a fresh fetch, cached rerun and executable
  startup. SIMH's internal register sanity check passed. Its generated binary
  passed `tests.integration_guest_control --rounds 3`: native COPY/read-back,
  terminal-config idempotence, reboot, two confirmed KSYS shutdowns, unchanged
  personas and source hashes. This is not native-x86 or full systemd acceptance.
- Earlier private macOS research with the same correction passed a continuous
  600.9-second two-browser workload and confirmed native shutdown. Unpatched
  comparison runs also passed. Other corrected attempts retained startup and
  browser failures.

**This fixes the timer interpolation defect, not an established cause of the
intermittent R50 missing-KSYS-acknowledgement failure.** It does not change console
readiness, command retry, shutdown deadlines, batch draining or native monitor
memory handling.
