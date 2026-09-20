# AlmaLinux 9 / IONOS deployment

Target: a fresh AlmaLinux 9 VPS with 1 vCore and 2 GB RAM, serving
`https://mud.etimbo.com`. The installer downloads a pinned, persona-free runtime
release and creates each installation's archwizard credentials locally.

## Install

Point `mud.etimbo.com`'s DNS A record at the VPS's IPv4 address. Allow inbound TCP
80 and 443 in the IONOS firewall; keep SSH access enabled. Only add an AAAA record
if IPv6 routing to this VPS works. These provider/DNS settings are outside the
host installer's control.

```sh
# If Git is not already installed:
sudo dnf install -y git

git clone https://github.com/irongulp/mud1.git mud-server
cd mud-server
sudo ./setup.sh --domain mud.etimbo.com
```

Setup asks for the certificate account email. For unattended installation, pass
`--email you@example.com`. It uses Let's Encrypt, accepts the ACME terms for that
account, enables the renewal timer, and reloads Nginx after renewed certificates.
HTTP serves only the ACME challenge until HTTPS is configured. Afterward HTTP
redirects to HTTPS. `--http-only` is an explicit private-test option, not the
recommended public installation mode.

The command installs Python 3.12, the pinned Python dependencies in a venv,
compiler/build tools, Nginx and Certbot (from EPEL with CRB enabled). Python 3.12
is available in current AlmaLinux 9 repositories (introduced in the 9.4 family).
SIMH is built from its pinned revision with automatic package installation
disabled and a single build job. Docker and Chromium are test tools, not VPS
runtime dependencies.

## Installed layout and startup

| Path | Purpose |
|---|---|
| `/opt/mud86/releases/<content-hash>/` | Application snapshot and its Python environment |
| `/opt/mud86/current` | Active application symlink |
| `/opt/mud86/simh/<revision>/BIN/pdp10` | Pinned, host-native emulator |
| `/etc/mud86/` | Runtime configuration and provisioning completion marker |
| `/var/lib/mud86/game/guest.dsk` | Mutable TOPS-10 and game disk |
| `/var/lib/mud86/game/t10boot.tap` | Original boot tape |
| `/var/lib/mud86/private/` | Owner-only initial archwizard credential journal |
| `/var/backups/mud86/` | Private, stopped-runtime backups |

Services run as the unprivileged `mud86` system account. The supervisor uses the
original tape boot with `/tm02`, a UTC host-derived boot clock, and bounded boot
retries. Readiness requires reaching the original game's persona prompt and
cleaning up the probe's guest job. The gateway has a separate HTTP readiness
check. systemd starts the services on host boot and orders gateway shutdown before
the emulator's orderly TOPS-10 KSYS shutdown.

The deployment profile currently uses **NOIDLE, a 5M instruction-rate throttle,
and DZ `SPEED=*8`**. This is separate from the development configuration. The
throttle caps emulated CPU throughput; it is not a multiplier for game time.
Acceptance checks include the original sleep/wake timer. The experimental IDLE
profile is not automatically enabled.

The emulator listens on `127.0.0.1:2020`; the gateway listens on
`127.0.0.1:8080`. Nginx exposes the browser terminal on 80/443. Setup keeps SELinux
enabled, sets the standard HTTP reverse-proxy network-connect boolean when
SELinux is active, and restores the Nginx/ACME file contexts. It adds HTTP/HTTPS
services to an active firewalld configuration without resetting existing rules.

## Archwizard credentials

Before browser access is enabled, setup creates and SAVEs all seven missing
archwizard personas. It displays known matching credentials in the operator's
terminal with a password-manager reminder. Do not redirect setup's credential
output into public installation logs.

The journal is `/var/lib/mud86/private/archwizard-credentials.json` (`0600` inside
a `0700` directory). Reruns preserve existing persona passwords and reuse that
journal. Existing unknown credentials are reported rather than reset. Ambiguous
interrupted SAVEs and existing zero-password records stop for reconciliation.

Richard's credential is for **ATTACH**, not verified direct login. Attached SAVE
or a qualifying QUIT can replace it with the originating persona's password.
Reruns report this drift and do not present the stale initial credential as
current. Details: [archwizard provisioning](archwizard-provisioning.md).

To inspect/reveal current known credentials during an exclusive maintenance window:

```sh
sudo systemctl stop mud86-gateway
sudo -u mud86 sh -c 'cd /opt/mud86/current && .venv/bin/python -m tools.provision_archwizards --port 2020 --state-dir /var/lib/mud86/private --show-credentials'
# After successful verification:
sudo systemctl start mud86-gateway
```

The runtime must be running for this check. A setup rerun also verifies and reveals
credentials. The initial journal remains available to the server administrator;
its entries are explicitly labelled *initial* values.

## Operations and updates

Setup installs `/usr/local/bin/mud86ctl` and a compatibility symlink at
`/usr/bin/mud86ctl`, which is on AlmaLinux's default sudo search path.
For an existing installation created before this fix, add the symlink once:

```sh
sudo ln -s /usr/local/bin/mud86ctl /usr/bin/mud86ctl
sudo mud86ctl status
```

This path-only repair requires no game restart or setup rerun. The full
`sudo /usr/local/bin/mud86ctl status` command also remains valid.

```sh
sudo mud86ctl status
sudo mud86ctl restart
sudo mud86ctl stop
sudo mud86ctl start
sudo journalctl -u mud86-runtime -u mud86-gateway -f
```

Update from the Git checkout:

```sh
git pull --ff-only
sudo ./setup.sh --domain mud.etimbo.com
```

Rerunning setup installs/activates the application snapshot and restarts the game;
plan a maintenance window. The existing game disk and credential journal are
preserved. A newer downloadable starter image does **not** replace a running
installation's mutable disk. Interrupted asset extraction uses a temporary
directory and only becomes an installation after all pinned checksums pass.
An unrecognized existing game directory is rejected rather than overwritten.

If certificate issuance fails, fix DNS/provider firewall reachability and rerun
the command. If runtime boot fails, inspect `journalctl -u mud86-runtime`; setup
does not claim success merely because the emulator opened its Telnet port.

## Backups

```sh
sudo mud86ctl backup
```

This stops the gateway and runtime, requires a confirmed KSYS shutdown, locks the
disk against another supervisor, and archives the game and private credential
journal. It restarts the services if they were running. The archive is `0600` and
contains secrets: keep it in private off-host storage. Backup causes a maintenance
interruption; no unattended backup schedule is installed by default.

Restore only while the services are stopped, from a trusted backup. Preserve the
current game/private directories first; restore the archived `game/` and `private/`
directories under `/var/lib/mud86`, with `mud86:mud86` ownership and private journal
permissions. Keep the restored game disk and credential journal paired. Restart
the services and verify an existing saved login before reopening access.

## Release and validation

Native x86 acceptance passed in
[GitHub Actions run 35499541986](https://github.com/irongulp/mud1/actions/runs/35499541986):
93 host tests, installation/rerun, saved-persona re-entry, private backup/restart,
Chromium multiplayer over HTTP and HTTPS/WSS, and container reboot. The three
measured original sleep/wake intervals were **5.980, 5.982 and 6.010 seconds**.
HTTPS used a local test certificate; public ACME issuance and IONOS-specific
network/SELinux behavior still require the target-host check described below.

`deploy/runtime.json` pins the release archive URL, compressed checksum, each
member's size/checksum, the SIMH revision and baseline provenance. The release
builder accepts only the pinned stopped checkpoint, preserves original source
hashes, rebuilds the availability-only variant with original DBASE, verifies zero
personas and completes KSYS before packaging. Installation tests use extracted
copies; the published starter never contains test-created credentials.

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m tools.package_runtime --output runtime/new-release --tag runtime-v1
.venv/bin/python -m tests.integration_runtime --state runtime/new-boot-check
```

The `AlmaLinux deployment` workflow runs native x86 tests on a Linux GitHub runner:
an AlmaLinux 9 systemd container limited to one CPU and 2 GB, real setup/rerun,
saved-persona re-entry, original sleep timing, stopped backups, Chromium multiplayer
through Nginx and container restart. Logs redact generated credential lines.
Public ACME issuance, SELinux enforcing-kernel behavior and the actual IONOS host
reboot need verification on the target VPS; a container is not evidence of those.

Local Docker reproduction (requires a Docker host capable of privileged systemd):

```sh
docker build -t mud86-alma9 -f deploy/Dockerfile.alma9 .
docker run -d --name mud86-install-test --privileged --cgroupns=host \
  --cpus=1 --memory=2g --tmpfs /run --tmpfs /tmp \
  -v /sys/fs/cgroup:/sys/fs/cgroup:rw \
  -v "$PWD:/checkout:ro" -v "$PWD/runtime/release-v1:/artifacts:ro" \
  -p 127.0.0.1:38080:80 mud86-alma9
.venv/bin/python -m tests.integration_deployment
```

Docker x86 translation on the development Apple Silicon host exhibited boot
stalls; do not equate those emulated-host runs with native x86 acceptance. Native
ARM AlmaLinux and macOS release-image boot/reboot checks provide additional controls.
