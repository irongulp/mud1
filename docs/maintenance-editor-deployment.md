# Deploy scheduled maintenance and SSH-tunnel persona editing

This runbook deploys the maintenance controls and SQL editor on an existing
AlmaLinux 9 MUD86 server. Wait for the PR's deployment checks and merge it first.
If the server still uses native personas, the MariaDB setup command below also
performs the **one-way native-to-MariaDB cutover** described in
[external-deployment.md](external-deployment.md). Plan approximately an hour for
that first cutover; an already-external update does not rebuild/import the game.

## 1. Prepare the checkout and maintenance window

SSH to the VPS and enter the clean deployment checkout:

```sh
ssh YOUR_SSH_USER@mud.etimbo.com
cd /path/to/mud-server
git status --short
git fetch origin
git switch main
git pull --ff-only
git rev-parse HEAD
```

Record the revision. Announce maintenance, ask players to SAVE and QUIT, and close
SQL editor connections. Keep working SSH/sudo access and current persona credentials.
The wait-mode count covers browser sessions, not independent operator/Telnet jobs
or SQL clients. Native cutover requires the supplied original MUD.TXT; custom world
definitions need separate preparation.

For the first upgrade, temporarily restrict provider-firewall HTTPS admission to
your operator IP, retaining SSH and the necessary HTTP ACME challenge access.
Keep that restriction through the private browser validation below. It protects
admission before the old Nginx/gateway understands the new maintenance flag, and
lets you test privately after removing that flag. Setup can restart Nginx, so
stopping Nginx is not an admission barrier for an installer run.

## 2. Enable maintenance and stop the game

### Server already has the maintenance commands

Choose **one**:

```sh
# Let connected browser players finish; stop after they leave:
sudo mud86ctl maintenance on --wait

# Or close sessions through normal QUIT/KJOB cleanup and stop immediately:
sudo mud86ctl maintenance on --graceful
```

Graceful cleanup obeys ordinary QUIT persistence rules; it does not force SAVE.
Wait mode holds the management lock. Ctrl-C leaves the flag enabled and players
running; resume wait mode or switch to graceful mode. An unavailable session count
is an error, not a count of zero.

### First upgrade from a version without maintenance commands

With the external admission restriction in place, use the merged checkout's
management code to set the persistent flag and stop the old installed services:

```sh
sudo python3.12 tools/deploy.py maintenance on --graceful
```

The old proxy cannot serve the new notice yet; the new setup installs that support.
Do not use wait mode against an old gateway lacking the session-count endpoint.

## 3. Back up the stopped installation

```sh
sudo /usr/local/bin/mud86ctl backup
```

Retain the printed archive paths and copy them securely off-host. Keep a VPS
snapshot or equivalent recovery set including `/etc/mud86`, the installed
application revision, game disk/boot media and private credential journal. For an
already-external installation, retain both the game/configuration archive and its
whole-database archive. These contain secrets. Because maintenance stopped the
runtime first, this backup leaves it stopped. A failed clean-shutdown check is a
reason to investigate before proceeding.

## 4. Install MariaDB mode and the new controls

```sh
sudo bash setup.sh \
  --domain mud.etimbo.com \
  --email YOUR_CERTIFICATE_EMAIL \
  --persona-storage mariadb
```

Use normal HTTPS setup, not `--http-only`. Setup preserves the maintenance flag,
starts/readiness-checks the services, and leaves public game admission blocked.
It provisions/verifies the SQL editor before restarting the database and game.
On an existing external installation, passwords/data are retained and no native
reimport occurs. On a native installation, this also captures, builds and imports
the external persona engine/store before admission.

Do not record setup's archwizard credential output in public/shared logs.

## 5. Verify the maintenance page, services and editor

```sh
sudo mud86ctl maintenance status
sudo systemctl is-active mud86-database mud86-runtime mud86-gateway nginx
sudo mud86ctl persona Grobble --json
sudo mud86ctl database-access

curl --silent --show-error --resolve mud.etimbo.com:443:127.0.0.1 \
  --dump-header - https://mud.etimbo.com/maintenance-status
```

Expect maintenance enabled, services active, persona backend `mariadb`, editor host
`127.0.0.1` and port `3307`. The HTTPS response must be 503 with
`{"maintenance":true}`, `Retry-After: 900` and `Cache-Control: no-store`.
The site root also returns the scheduled-maintenance page. Do not use curl's
`--fail` for these deliberately-503 checks, or follow redirects with `-L`.

Review recent service logs:

```sh
sudo journalctl -u mud86-database -u mud86-runtime -u mud86-gateway \
  --since "1 hour ago" --no-pager
```

Retrieve the editor password explicitly on the VPS:

```sh
sudo mud86ctl database-access --show-credentials
```

On your Mac, keep this tunnel running:

```sh
ssh -N -o ExitOnForwardFailure=yes \
  -L 127.0.0.1:13307:127.0.0.1:3307 \
  YOUR_SSH_USER@mud.etimbo.com
```

Use SQL client host `127.0.0.1`, port `13307`, database `mud86_personas`, user
`mud86_editor`, and the displayed password. Read/edit `persona_editor`; use
`(namespace, name)` as a virtual unique key if your client needs one for view
editing. Set the SQL session to UTC. The game uses its Unix socket, and no public
database firewall opening is needed.

## 6. Reopen privately, verify gameplay, then reopen publicly

Keep the operator-only external admission restriction while running:

```sh
sudo mud86ctl maintenance off
```

This starts/checks runtime and gateway readiness before removing the flag. It
cannot selectively exempt an operator browser while the flag exists. With the
external restriction still in place, refresh your browser and test:

- A known saved persona's unchanged password, identity and score.
- A unique disposable letters-only persona (at most nine characters): SAVE,
  QUIT and password re-entry.
- An editor update while that disposable player is logged out; confirm it on
  their next login. Revisions increment automatically. Identity/password/journal
  fields are not editable through the account.

After validation, take a paired external backup:

```sh
sudo mud86ctl backup
sudo mud86ctl status
```

This backup briefly stops and then restarts services if they were running. Retain
both printed archives privately/off-host. Remove the temporary external admission
restriction and announce reopening. Older terminal pages may wait for their
15-minute retry; a manual refresh reconnects sooner.

## Future updates and maintenance

```sh
sudo mud86ctl maintenance on --wait
sudo mud86ctl backup
# Update the clean checkout to the approved merged revision.
sudo bash setup.sh --domain mud.etimbo.com --email YOUR_CERTIFICATE_EMAIL
sudo mud86ctl maintenance status
sudo mud86ctl maintenance off
```

Omitting the storage option preserves the recorded backend. Use graceful mode
instead of wait when immediate logout is required or the gateway is already
stopped. Maintenance survives setup, restart and reboot until readiness-checked
`maintenance off`; Nginx serves the notice independently of the game/gateway.

## Failure and recovery

Keep maintenance/admission restrictions enabled after any failure. A failed
`maintenance off` retains the flag. If admission was already reopened, use
`maintenance on --graceful` before investigation. Preserve logs and recovery
assets; do not delete cutover phases, credential intents or SQL objects to force
setup through a reconciliation error.

Before the first external writes, native recovery requires a controlled restoration
of the stopped pre-cutover installation. After external play, use paired external
backups and an isolated, verified recovery database with fresh guest sessions;
there is no reverse conversion preserving external progress. SQL archives retain
the editor view/trigger, while paired configuration is needed to reprovision
server users/grants. See [persona-migration.md](persona-migration.md).

The editor was verified with real MariaDB on macOS and AlmaLinux ARM, including
an actual SSH forward and production-game SQL-edit re-entry. Maintenance has host,
browser and independent AlmaLinux Nginx acceptance. The updated native-x86 CI
matrix and target-host enforcing SELinux/public ACME checks remain authoritative
deployment gates; this document does not claim a live VPS deployment was performed.
