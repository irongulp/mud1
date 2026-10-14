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
`workflow_dispatch`. The full existing sequence is retained: native x86 AlmaLinux
systemd setup/rerun, persona re-entry/timing, stopped backup/restart, Chromium
multiplayer over HTTP/HTTPS, container reboot, populated native-to-MariaDB cutover,
fresh external installation and SQL editor checks. Shutdown/backup checks and
failure artifact upload retain their existing behavior. Nothing is made successful
with `continue-on-error` or automatic test retries.

Before a release or deployment, deliberately run this workflow for the candidate:

```sh
gh workflow run deployment.yml --ref <candidate-branch-or-tag>
gh run list --workflow deployment.yml
```

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
