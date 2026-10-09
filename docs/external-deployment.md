# Opt-in MariaDB persona deployment on AlmaLinux

The installer supports native persona storage (fresh-install default) and an
explicit one-way MariaDB cutover:

```sh
sudo ./setup.sh --domain mud.etimbo.com --persona-storage native
sudo ./setup.sh --domain mud.etimbo.com --persona-storage mariadb
```

The first command is a normal native installation, with the original file backend
and availability-only starter image. It has no MariaDB dependency. The second
command supports both a fresh installation and a populated native installation.
On a fresh external install, setup first provisions the seven original archwizard
personas using native tooling, then imports them into a new private external store.
Ordinary players are subsequently created by original BCPL through external storage.

**Run cutover in a maintenance window.** Setup stops admission and the runtime,
requires confirmed KSYS shutdown, archives the native disk and captures its full
persona file under native ENQ. It compiles the generated external lifecycle engine
using the installed original BCPL/MACRO/DBASE tools, imports into a fresh namespace,
verifies every record, then enables the production bridge and per-browser bootstrap.
The existing mutable disk is never replaced with a local lab/test image. The
world-data addresses must match the external executable, so original DBASE is
relinked/regenerates the supplied MUD definitions with DBADAT at 520000.

This builder currently verifies the installed world against the supplied original
MUD.TXT; custom definitions require an explicit prepared-source adaptation. It
does not silently overwrite a custom world. Standalone POWER remains native;
MUD.WIZ remains the original fallback authorisation file. Main world persistence
is not externalized by selecting MariaDB personas.

## Services and configuration

- `mud86-database.service`: private Unix-socket-only MariaDB in
  `/var/lib/mud86/external/database`, running as mud86, with events/networking off.
  It does not use, replace or configure a system MariaDB datadir/service.
- `mud86-runtime.service`: existing foreground SIMH supervisor; in external mode
  it owns the reserved DZ6/7 raw bridge listeners and bounded writer workers.
- `mud86-gateway.service`: production gateway selects ExternalBootstrap only when
  an external persona config is explicitly configured.

External-only systemd drop-ins order database readiness before runtime, and runtime
before gateway. Gateway stops first, so QUIT/KJOB cleanup retains storage access;
the runtime completes KSYS with bridge/database alive. A dead bridge worker causes
runtime failure rather than native fallback. HTTP listener readiness alone is not
admission: runtime readiness validates actual database and in-game lookup/bootstrap.

Native installation does not create a database dependency. Omitting the backend
option on a rerun preserves the recorded choice. External-to-native conversion is
rejected. An interrupted cutover records a private phase and disables ordinary
native admission until explicit external setup/reconciliation resumes.

`/etc/mud86/personas.json` is a private mud86-owned runtime account config. The
runtime account gets SELECT/INSERT/DELETE and column-scoped UPDATE plus revision;
it can SELECT/INSERT/UPDATE the operation journal. Operator credentials are in
root-private `/etc/mud86/persona-admin.json`. The private socket directory is 0700;
the lab's empty-password private root account convention does not create a public
TCP root login. Do not substitute these files with the local development configs.

Original source in installed application snapshots remains unchanged. Generated
sources/provenance live under `/var/lib/mud86/external/build`; missing DBASE assets
are fetched at the pinned PDP-10/MUD1 revision. No new historical binary is published
as a runtime release by this source PR. The optional requirements-storage.txt is
installed only for MariaDB deployments (development CI also installs it).

## Cutover and reruns

Private recovery assets are under `/var/lib/mud86/external/`:

- `native-before-cutover.dsk`: stopped pre-cutover guest disk.
- `native-personas.json`: checked capture, including encoded passwords.
- `cutover.json`: preparation/import phase and snapshot identity.
- `build/`: generated guest source and provenance.

Imports use the durable receipt contract in `persona-migration.md`: identical
retries never resurrect personas after gameplay. Existing passwords and the
archwizard credential journal are preserved. Rerunning an admitted external setup
verifies external archwizard records rather than consulting a stale native file
or regenerating player passwords.

A failed DDL/build/cutover stays stopped for reconciliation. Do not delete the
phase, generated credentials, DB or snapshot to force a new import. Restore from
the historical native snapshot is possible before external admission, but is not
a reverse conversion preserving later progress. Once external play starts, use
whole-database external backups.

## Operations

```sh
sudo mud86ctl status
sudo mud86ctl restart
sudo mud86ctl personas --json
sudo mud86ctl persona Grobble --json
sudo mud86ctl backup
```

Persona inspection is backend-aware and excludes encoded password values. Files,
guest logs and host error scans retain their existing readers. Native `inspection-install`
is not rerun as an external persona reader. The in-game PASSWORD/PURGE logic remains
in BCPL and is separate from operator inspection.

Backup stops the game/gateway, confirms shutdown and holds the runtime lock. In
external mode it additionally captures a whole-database archive while the private
database service remains available; the backup output identifies both private
archives. Keep game/configuration/credential assets and the database recovery point
paired. Schema/row verification and fencing of unfinished operations are described
in `persona-migration.md`. Restore only to an isolated recovery DB with events off,
then boot fresh guests. Server users/grants are provisioned separately from SQL dumps.

The service runtime has no imports of test runtime/database helpers or references
to ignored local lab fixtures. The local `tools.serve_external` launcher remains
development-only. Optional compatible-image chaining requires separately prepared
targets; setup does not deploy the synthetic Valley lab world.

## Acceptance

The native x86 AlmaLinux workflow checks existing native install/rerun/backup/TLS/
browser behavior before testing populated native-to-MariaDB cutover. It then tests
a fresh external container, external reruns, saved login, backend-aware inspection,
backup and restart. The workflow keeps native mode in its regression matrix and
does not upload private snapshots, credential journals or database dumps.

Acceptance clients reject redirects, including WebSocket upgrades, and require
loopback endpoints. After the TLS fixture is installed, the native precheck uses
`--native-url https://127.0.0.1:38443` to reach the container's mapped HTTPS port.
The explicit HTTP-only cutover setup restores the mapped HTTP endpoint for later
checks. The imported player identity comes from the completed native acceptance
report and is rechecked with an exact greeting and backend-aware inspection.
Earlier redirected fixture calls are not evidence of local cutover or persistence.

Local production-service acceptance is available as:

```sh
.venv/bin/python -m tests.integration_external_service \
  --output runtime/external-service-check
```

This uses a stopped verified guest copy to exercise the production supervisor,
private DB, bridge, bootstrap, browser SAVE/PASSWORD and clean shutdown. It is not
by itself Linux installer/cutover acceptance. Check the PR's native x86 CI status
before deploying; real IONOS ACME/SELinux/host behavior remains a target-host check,
as for the existing native installer. No actual VPS cutover is part of this PR.
