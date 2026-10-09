# Local MariaDB-backed browser game

Start the foreground loopback lab from the repository root:

```sh
.venv/bin/python -m tools.serve_external
```

Open **http://127.0.0.1:8081** after the URL appears. Keep the terminal open;
Ctrl-C performs clean browser/guest/database shutdown. The ordinary local disk,
system MariaDB service and port 8080 are not selected by this launcher.

## Requirements and state

Use the existing Python 3.9 `.venv`, pinned SIMH, original boot tape and frontend
assets. Install optional storage dependencies if necessary:

```sh
.venv/bin/python -m pip install --require-hashes -r requirements-storage.txt
```

`mariadbd`, `mariadb-install-db` and `lsof` must be on PATH. No system database
service is needed: the launcher owns a private Unix-socket-only MariaDB process.

On first launch, the stopped verified always-open lifecycle image
`runtime/external-always-open-green/compiled/guest.dsk` is copied into
`runtime/external-local/machine/guest.dsk`. Later starts retain the copied disk
and MariaDB records. The source must be stopped and is never overwritten.

For another independent test world/store:

```sh
.venv/bin/python -m tools.serve_external \
  --prepared-runtime runtime/external-always-open-green/compiled \
  --state-dir runtime/my-external-lab --port 8082
```

The parent directory must exist. New state directories are 0700; existing ones
must be owner-only. Use short paths for macOS Unix sockets. Only one launcher can
own a state directory. An interrupted first database setup stops for inspection,
rather than replacing an existing database directory.

This is a development-workspace launcher, reusing the verified disposable helpers
under `tests/`. It does not compile a new external image or install a production
service. The prepared runtime needs the external lifecycle game and ROSEED under
`[2011,2776]`; per-session marker checks reject an unapproved game image.

## Interactive checks

New local stores use [readable persona columns](persona-columns.md). The existing
default lab has also been upgraded with a private backup. TablePlus can directly
read `name`, `score`, `strength`, etc.; refresh its schema if it still shows `words`.
An older custom state directory is not automatically migrated at startup.

The current schema is [format 3](persona-timestamps.md): last_saved_at, nullable
state markers such as invisible_at, and created_at/updated_at metadata. Both prior
array and v2 column stores remain supported until an explicit offline upgrade.

1. Choose an unused letter-only name of at most nine characters, sex and password.
2. Enter `SAVE` and verify the saved message.
3. Enter `PASSWORD`, supply the old password and replacement twice.
4. Enter `QUIT`; the browser reconnects to the name prompt.
5. Log in again using the same name and replacement password.
6. Stop/restart the launcher with the same state directory and repeat login.

Native rules remain: admission alone does not persist a persona; unsaved zero-score
first-game QUIT may discard it; repeated ordinary SAVE requires changed score.
PASSWORD changes session state and persists at eligible SAVE/QUIT, not immediately.

For administration, create and SAVE **Roy** with a password you choose. The original
archwizard rules grant its in-game capabilities. Use `PURGE THAT` to enumerate,
or `PURGE <name>` for a target; the menu's Save means keep, Delete removes, Finish
ends traversal. Purge an ordinary disposable target, not your active administrator.
Richard retains its historical direct-login exception, so Roy is the simpler test.

The external store starts empty. Native fixture personas on the copied disk are
not imported or consulted; no historical fixture passwords are needed. Migration
is a separate explicit action. The default now bypasses only the opening-hours
gate; historical HOURS output and overload checks remain. It starts Friday at 03:00.
The older lifecycle-green image retains opening restrictions if explicitly selected.
The image includes
the approved MUD/Valley-clone handover setup described in `external-persona-lifecycle.md`.

## Bootstrap and shutdown

The optional gateway bootstrap intercepts MUDGUEST's initial name question before
player input, interrupts to the monitor, GETs/checks ROBOOT, provisions a fresh
72-bit seed through ROSEED, GETs/checks again and STARTs the image. Only the new
intro reaches the browser. Each reconnect gets a new seed. Setup is bounded at
30 seconds; an early monitor return or EOF is detected immediately rather than
waiting for a name question that will never arrive. The preamble is bounded at
16 KiB. The local lab formerly used a historical-hours image, which refused
MUDGUEST at Friday 15:21 and caused repeated bootstrap timeouts/Connecting waits.
The always-open image fixes that availability gate without using DEMO mode.

For an existing stopped local lab with the older image, install only the schedule
patch (this does not replace its database or disk):

```sh
.venv/bin/python -m tools.install_external_availability
```

It holds the lab lock, backs up the stopped disk to `before-always-open.dsk`,
preserves the old executable as `XHRS.EXE`, creates/verifies `X24LIB.BCL` with
only the timeok change, compiles/relinks through native tools, initializes from
the existing MUD.DMP, and restores MUD.EXE protection <055>. DBADAT stays at
520000, so original world files do not need DBASE regeneration. It refuses to
overwrite an existing availability backup; inspect an interrupted install before
retrying. `always-open.json` records completed installation. Never restore the
disk backup to roll back the executable and thereby discard later disk changes.

The out-of-hours fixture is reproducible with:

```sh
.venv/bin/python -m tests.integration_external_availability \
  --output runtime/external-always-open-example
```

`runtime/external-always-open-green/` passed Chromium creation/SAVE/PASSWORD with
the guest booted Friday at 15:19, source preservation and clean shutdown. The
compiled source checkpoint was copied only after a clean stop. Earlier
`external-always-open-verified` passed browser operation but hit a final native
BATCON/KSYS timeout; it is not the final acceptance. The default local lab was
patched in place with saved MariaDB data retained. A further 48 relevant host
bootstrap/gateway/preparation tests passed.

Setup does not log seeds/monitor payloads. Failures still run normal interrupt/
KJOB cleanup. Native gateway startup remains the default elsewhere.

Two private bridge listeners handle reads/writes/admin. Idle protocol timeouts
retire the old owner and permit fresh H1, without disabling the listener. An
unexpected worker exit stops the lab. Startup monitor/slave stalls get at most
three retries; failed game/storage operations are not retried as startup failures.

The copied lab disk now disables the optional `STOMP` entry in `SYS:TTY.INI`.
The original detached `STOMPR` initializer was observed claiming both reserved
TTY6/TTY7 devices in INIT, leaving them assigned to job 1 and making MUD's OPEN
fail even though MariaDB records were valid. The launcher preserves all other
terminal settings, saves the original configuration as `XTTY.INI` in the operator
directory, verifies the edit and cleanly reboots before HTTP readiness. Later
starts are idempotent and verify STOMPR is absent. The gateway already explicitly
sets browser terminal type/width; LOGIN and normal guest operation still work.
This change is confined to the private copied lab disk. Native/default/systemd
configurations and the stopped source image are not rewritten.

Ctrl-C/SIGTERM after readiness cleans browser sessions while the bridge/database
are still running, then completes guest KSYS and stops MariaDB. Startup interruptions
also stop child processes and release the state lock. Forced kills are not clean
shutdowns. `ready.json` is removed on normal shutdown.

The private state includes generated runtime `database.json` credentials, `db/`
data/logs, copied `machine/` disk/console/config, `launcher.lock`, and `ready.json`
with URL/PID while ready. Readiness means the listener started, not an end-to-end
health probe. Keep this directory private; it contains chosen password words.
Do not delete it to reconcile UNKNOWN saves. Use the game's recovery and the
procedures in `persona-migration.md`. Runtime credentials do not grant all operator
dump/restore privileges. Migration stays one-way native -> external.

## Validation

```sh
.venv/bin/python -m unittest \
  tests.test_external_local tests.test_external_bootstrap \
  tests.test_gateway tests.test_persona_bootstrap -v
.venv/bin/python -m tests.integration_external_local
```

Chromium evidence `runtime/external-local-password/` passed creation/SAVE, PASSWORD,
masking and changed-password re-entry after a full launcher/database/guest restart.
SQL confirmed the saved row; live SCORE showed GAMES=2. The 35 relevant host tests
passed. Earlier boot/test failures remain: a first native OPR stall, and a test
that incorrectly expected stored GAMES to update at login (it updates at SAVE/QUIT).

Public hosting, automatic native import, external-aware SSH inspectors, systemd
deployment and production database provisioning remain separate work.

The initializer fix passed Chromium SAVE/PASSWORD/restart/PURGE at
`runtime/external-local-stomper-verified/`, and lookup after 75 seconds idle plus
the same browser matrix at `runtime/external-local-idle-verified/`. Earlier
`external-local-no-stomper` passed browser operations but hit an existing native
KSYS completion timeout on shutdown; its report is not a completed acceptance.
Disposable operator experiments are retained under `bridge-init-check-*`.
