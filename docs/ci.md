# CI and deployment acceptance

## Pull-request checks

`Fast tests / Host and Chromium tests` runs for every PR to main, pushes of code
to main/setup-almalinux9, and manual dispatch. It installs the pinned development
dependencies, fetches pinned preparation sources, and runs the unittest suite.
The real-Chromium tests use controlled/fake backends; they do not boot SIMH or
MariaDB, compile guest code, download historical runtime disks or invoke setup.
They cover gateway input/password handling, prompt fencing, reconnect/cleanup,
terminal rendering, source generation, persistence adapters and controller faults.

Pip downloads and the browser installation are cached. Chromium cache keys include
OS/architecture and the dependency manifests, ensuring a changed Playwright pin
cannot silently use an old browser. OS libraries are installed even on cache hits.
Only downloads/browser binaries are cached, not virtual environments or game state.
Superseded fast runs are canceled; a run has a 15-minute upper bound.

The performance target is under five minutes including setup, not a guarantee.
Native-x86 GitHub run38647077477 passed cold-cache in2m1s and with matching Chromium
cache restored in1m50s; tests themselves took about80s. The independent audit
run38647077411 passed in23s. No native deployment job ran for this CI-split PR.
The real-Chromium heartbeat regression observes three one-second cycles rather
than requiring a 50-ms PONG response during browser startup; production heartbeat
settings and the direct protocol regressions are unchanged.

GitHub branch protection/rulesets are independent settings. At implementation time
main had neither, so there was no existing `alma9` requirement to migrate. If a
required merge check is configured, select `Host and Chromium tests`. Do not require
the path-filtered audit job or manual acceptance job: they intentionally do not run
for every PR. Fast tests still run on documentation-only PRs to provide a consistent
check if protection is enabled later.

**Green fast CI means host/protocol/browser regression tests passed. It does not
mean native deployment, migration, original-engine timing or recovery was validated.**

## Dependency audit

`Dependency audit` runs independently on dependency-manifest/audit-workflow PRs
and pushes, weekly on Monday, and manual dispatch. It uses the existing pinned
pip-audit tool and OSV service against development/deployment requirements. An
audit failure is reported separately from regression-test failure. Changes to
dependency versions must be investigated; external-service failures remain visible.

## Manual deployment acceptance

`Manual AlmaLinux deployment acceptance` (`deployment.yml`) runs only through
`workflow_dispatch`. Two independently reported native-x86 AlmaLinux jobs retain
the acceptance requirements:

- **native-upgrade:** systemd setup/rerun, saved persona/timing, stopped backup/
  restart, Chromium HTTP/HTTPS multiplayer, container reboot, then populated
  native-to-MariaDB cutover/rerun/persistence and SQL editor checks. This preserves
  the end-to-end upgrade sequence on one installation.
- **fresh-mariadb:** a separate fresh external installation, persistence, rerun,
  backup/restart and SQL editor checks. It runs even if the native-upgrade job
  fails, instead of losing all external evidence behind a browser failure.

Both use one CPU/two GiB disposable systemd containers. Matrix fail-fast is off;
an individual scenario still stops at its first failing step. Neither scenario
can substitute for the other. Both always collect lifecycle evidence and require
confirmed final native shutdown, independently of systemd's exit status. Nothing
is made successful with `continue-on-error` or test retries.

The single `guarded_profile` input defaults to true in CI, explicitly passing
`--monitor-scope --batch-preflight` to first setup. Installer reruns omit the
flags and must preserve the recorded selection. Current-boot monitor and native
batch execution proofs are verified before successful scenario reporting. This
does **not** change installer defaults or validate the unguarded profile.

Before a release or deployment, deliberately run this workflow for the candidate:

```sh
gh workflow run deployment.yml --ref <candidate-branch-or-tag> -f guarded_profile=true
gh run list --workflow deployment.yml
```

Select `guarded_profile=false` for a separate check of historical/default startup.
Artifacts are named `deployment-results-native-upgrade` and
`deployment-results-fresh-mariadb`. Fast host/Chromium tests and dependency audits
remain independent workflows; publishing requires acceptance of the exact
intended release configuration and commit. See [release-1.1.0.md](release-1.1.0.md).

Manual dispatch requires the workflow to exist on the default branch; use the
Actions UI or CLI to select the candidate ref once this split is merged. Inspect
and retain failing logs. A failed acceptance run blocks describing that candidate
as deployment-validated; it does not automatically block unrelated PRs.
Installer, emulator, native persistence and migration changes require this check
before shipping. Target-host ACME/SELinux/reboot checks remain separate.

Known intermittent native startup, source-transfer and shutdown failures are not
claimed fixed by moving this workflow. They remain engineering work and must not
be hidden by unbounded reruns. The split keeps slow system acceptance useful while
giving ordinary PRs a short, independently actionable regression check.

## Shutdown failure diagnostics

The always-run cleanup collects both disposable containers' runtime/gateway
journals, selected service states and shutdown markers before and after stopping
the runtimes. Commands have bounded deadlines; missing containers and timeouts
are recorded without blocking the other container's collection. Credential
files, service environment variables and database records are excluded.
Native and external install/rerun/backup logs are written with credential redaction before
checking the exit status, retaining failed-command output.

Runtime shutdown reports the failure phase and exception type, plus verified
input/submission flags for control-echo failures. Exception buffers are excluded.
These diagnostics do not change guest commands, retry policy or deadlines.

Release-candidate run 42205728019 at `3ac3937` failed the fresh external backup's
clean-shutdown gate. Later investigation run 42243789230 demonstrated explicit
native BATCON startup failure and confirmed that the corrected setup gate stops
before activating/rebooting after unconfirmed shutdown. This establishes a
host-side continuation fix, not a BATCON repair. The native release blocker
remains open. PR16 supplied those host guards without monitor changes. The
release candidate adds separately tested opt-in monitor/batch integration, but
excludes private memory capture and experimental diagnostic modes. Previous
partial successes do not establish full acceptance of the consolidated commit.
