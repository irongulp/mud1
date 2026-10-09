# Opt-in MariaDB persona deployment on AlmaLinux

For the step-by-step maintenance and SQL-editor rollout, see
[the deployment runbook](maintenance-editor-deployment.md).

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

- `mud86-database.service`: private MariaDB in
  `/var/lib/mud86/external/database`, running as mud86, with events off. Game
  storage uses its private Unix socket; setup additionally enables the SQL editor
  listener on **127.0.0.1:3307**, with name resolution disabled.
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
the empty-password local root account remains confined to the socket. Before
enabling TCP, setup locks non-socket root/game-account identities and adds locked
loopback identities for root, the game account and anonymous access. The editor
has its own authenticated account. Do not substitute these files with local
development configs or open a database port in the public firewall.

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
sudo mud86ctl database-access
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

## SQL editing over an SSH tunnel

MariaDB setup now provisions `mud86_editor` and an updatable `persona_editor`
view. For an existing external installation, rerun the updated installer during
maintenance; it stops game writers, configures the SQL objects and restarts the
database before restarting the game. Native installations do not enable this
listener. The local development launcher remains socket-only.

Retrieve connection details on the VPS:

```sh
sudo mud86ctl database-access
sudo mud86ctl database-access --show-credentials
```

Only the second command displays the password. The root-private credential file
is `/etc/mud86/database-editor.json`; setup reruns preserve its password and
verify its account, view, trigger and exact grants. Credential drift, a locked
editor, or unexpected objects/privileges require reconciliation rather than a
silent password reset or privilege replacement. Configuration is retained with
the existing paired configuration/database backups. After SQL restore to a fresh
recovery instance, reprovision server users/grants using that preserved configuration
before admission; users/grants are not included in the SQL archive.

On your Mac, keep this tunnel running:

```sh
ssh -N -o ExitOnForwardFailure=yes \
  -L 127.0.0.1:13307:127.0.0.1:3307 \
  YOUR_SSH_USER@mud.etimbo.com
```

Connect your SQL client to `127.0.0.1:13307`, database `mud86_personas`, user
`mud86_editor`, using the retrieved password. SSH carries the encrypted remote
connection. The database listener is IPv4 loopback only; port 3307 is not exposed
publicly. Port conflicts fail rather than choosing a different/public listener.

Browse and edit **`persona_editor`**, not `personas`. The view exposes identity
and revision information plus score, attributes, sex, games played, programmer
number, asleep, last-save time and the nine nullable state timestamps. Password
words, unknown state bits and opaque words are omitted. UPDATE privileges cover
gameplay fields only: identity keys, name, generation, revision, creation/update
metadata, base tables, journals, INSERT/DELETE and DDL are not editable through
this account. Use in-game PASSWORD and PURGE for those persona operations.

For clients that require a key to edit a view, configure `(namespace, name)` as
its virtual unique key. Alternatively, use the client's SQL editor. Use UTC for
the SQL session:

```sql
SET time_zone = '+00:00';

SELECT name, score, strength, stamina, wizard_eligible_at, revision
FROM persona_editor
WHERE namespace = 'mud' AND name = 'grobble';

-- Substitute the revision returned by SELECT. Check that one row was affected.
UPDATE persona_editor
SET score = 1500
WHERE namespace = 'mud' AND name = 'grobble' AND revision = 7;
```

An editor-specific BEFORE UPDATE trigger increments revision automatically,
including timestamp-only or no-op updates. Do not assign revision yourself.
Game writes retain their existing single revision increment, and pending SAVE/
PURGE transactions conflict when an editor changes their captured snapshot.
`NULL` state timestamps mean off; `UTC_TIMESTAMP()` means on.
SQL edits are direct database transactions, not W1 game-operation journal entries;
the whole-database backup includes their results.

**Edit while the affected player is logged out.** SQL changes do not alter a live
BCPL profile. The trigger fences already-started snapshot transactions; a later
SAVE from a stale live profile may still overwrite an edit. For simultaneous SQL
editors, use the revision predicate above rather than relying on a GUI's last-write
behavior. GUI clients were not independently tested; equivalent SQL updates and
a real SSH forward were verified with MariaDB 10.5.29 on disposable AlmaLinux ARM.

## Acceptance

The native x86 AlmaLinux workflow checks existing native install/rerun/backup/TLS/
browser behavior before testing populated native-to-MariaDB cutover. It then tests
a fresh external container, external reruns, saved login, backend-aware inspection,
backup and restart. The workflow keeps native mode in its regression matrix and
does not upload private snapshots, credential journals or database dumps.
The matrix also checks the installed TCP editor after setup/restart and exercises
isolated editor permissions, journal conflicts, revision handling and whole-DB
view/trigger recovery (`tests.integration_database_access`).

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
