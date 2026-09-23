"""Verified first-install assets and AlmaLinux deployment orchestration."""
import hashlib
import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
IMAGE_FILES = {'guest.dsk', 't10boot.tap'}
APP = Path('/opt/mud86')
STATE = Path('/var/lib/mud86')
CONFIG = Path('/etc/mud86')
ACME = Path('/var/www/mud86-acme')
CONTROL_WRAPPER = '#!/bin/sh\nexec /opt/mud86/current/.venv/bin/python /opt/mud86/current/tools/deploy.py "$@"\n'


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def validate_domain(domain):
    if len(domain) > 253 or '.' not in domain or not all(
        re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label)
        for label in domain.split('.')
    ):
        raise ValueError('Supply a DNS hostname, for example mud.etimbo.com')
    return domain


def image_files(version):
    if version == 1:
        return IMAGE_FILES
    if version == 2:
        return IMAGE_FILES | {'NOTICES.txt'}
    raise ValueError('Unsupported starter image version')


def install_image(archive, manifest, destination):
    """Install atomically once. A mutable installed disk is never replaced."""
    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        marker = destination / 'installed.json'
        if destination.is_symlink() or marker.is_symlink() or not marker.is_file():
            raise ValueError('Existing game directory is not a recognized installation; preserve it for recovery')
        installed = json.loads(marker.read_text())
        expected_files = image_files(installed.get('version'))
        if set(installed.get('files', {})) != expected_files:
            raise ValueError('Unrecognized installed image metadata')
        if not all((destination / name).is_file() and not (destination / name).is_symlink()
                   for name in expected_files):
            raise ValueError('Installed image has missing or symlinked files; preserve it for recovery')
        return False
    expected_files = image_files(manifest['version'])
    if manifest['availability'] != 'always-open':
        raise ValueError('Unsupported starter image')
    if set(manifest['files']) != expected_files or sha256(archive) != manifest['archive']['sha256']:
        raise ValueError('Starter image checksum or manifest mismatch')
    temporary = Path(tempfile.mkdtemp(prefix='.game-', dir=destination.parent))
    try:
        seen = set()
        with tarfile.open(archive, 'r|gz') as bundle:
            for member in bundle:
                if not member.isfile() or member.name not in expected_files or member.name in seen:
                    raise ValueError('Unexpected starter archive member')
                expected = manifest['files'][member.name]
                if member.size != expected['size']:
                    raise ValueError('Starter member size mismatch')
                target = temporary / member.name
                with bundle.extractfile(member) as source, target.open('xb') as output:
                    os.fchmod(output.fileno(), 0o600)
                    shutil.copyfileobj(source, output)
                    output.flush()
                    os.fsync(output.fileno())
                if sha256(target) != expected['sha256']:
                    raise ValueError('Starter member checksum mismatch')
                seen.add(member.name)
        if seen != expected_files:
            raise ValueError('Incomplete starter archive')
        (temporary / 'installed.json').write_text(json.dumps(manifest, indent=2) + '\n')
        temporary.rename(destination)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return True


def run(*command, **kwargs):
    return subprocess.run([str(part) for part in command], check=True, **kwargs)


def download(url, destination, expected):
    if destination.exists() and sha256(destination) == expected:
        return
    temporary = destination.with_suffix('.part')
    request = urllib.request.Request(url, headers={'User-Agent': 'mud86-setup/1'})
    try:
        with urllib.request.urlopen(request, timeout=60) as source, temporary.open('wb') as target:
            shutil.copyfileobj(source, target)
        if sha256(temporary) != expected:
            raise ValueError('Download checksum mismatch')
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def application_release():
    directories = ('server', 'tools', 'web', 'deploy', 'docs', 'licenses')
    files = ('requirements.lock', 'requirements-deploy.txt', 'README.md', 'setup.sh',
             'LICENSE', 'COPYING', 'NOTICE', 'THIRD_PARTY.md')
    digest = hashlib.sha256()
    paths = [ROOT / name for name in files]
    for directory in directories:
        paths.extend(path for path in (ROOT / directory).rglob('*')
                     if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc')
    for path in sorted(paths):
        digest.update(str(path.relative_to(ROOT)).encode())
        digest.update(path.read_bytes())
    release = APP / 'releases' / digest.hexdigest()[:20]
    if not release.exists():
        release.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix='.release-', dir=release.parent))
        for directory in directories:
            shutil.copytree(ROOT / directory, temporary / directory,
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        for name in files:
            shutil.copyfile(ROOT / name, temporary / name)
        for path in temporary.rglob('*'):
            path.chmod(0o755 if path.is_dir() or path.stat().st_mode & 0o111 else 0o644)
        temporary.chmod(0o755)
        temporary.rename(release)
    python = release / '.venv/bin/python'
    if not python.exists():
        run(sys.executable, '-m', 'venv', release / '.venv')
    run(python, '-m', 'pip', 'install', '-r', release / 'requirements-deploy.txt')
    return release


def build_simh(revision):
    if not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('Invalid SIMH revision')
    source = APP / 'simh' / revision
    if not source.exists():
        source.parent.mkdir(parents=True, exist_ok=True)
        run('git', 'init', source)
        run('git', '-C', source, 'remote', 'add', 'origin', 'https://github.com/simh/simh.git')
    if not (source / 'BIN/pdp10').exists():
        run('git', '-C', source, 'fetch', '--depth', '1', 'origin', revision)
        run('git', '-C', source, 'checkout', '--detach', revision)
        run('make', '-C', source, '-j1', 'pdp10', 'USEFUL_PACKAGES=', 'OPTIONAL_PACKAGES=')
    actual = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != revision:
        raise ValueError('Unexpected SIMH source revision')
    return source / 'BIN/pdp10'


def nginx_config(domain, tls=False, challenge_only=False):
    domain = validate_domain(domain)
    acme = f'location ^~ /.well-known/acme-challenge/ {{ root {ACME}; }}'
    proxy = '''location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Host $http_host;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $mud86_upgrade;
        proxy_read_timeout 3600s;
        proxy_buffering off;
    }'''
    header = 'map $http_upgrade $mud86_upgrade { default upgrade; "" close; }\n'
    if challenge_only:
        return header + f'server {{ listen 80; listen [::]:80; server_name {domain}; {acme}\nlocation / {{ return 503; }} }}\n'
    if not tls:
        return header + f'server {{ listen 80; listen [::]:80; server_name {domain}; {acme}\n{proxy}\n}}\n'
    return (header + f'server {{ listen 80; listen [::]:80; server_name {domain}; {acme}\n'
            f'location / {{ return 301 https://{domain}$request_uri; }} }}\n'
            f'server {{ listen 443 ssl; listen [::]:443 ssl; server_name {domain};\n'
            f'ssl_certificate /etc/letsencrypt/live/{domain}/fullchain.pem;\n'
            f'ssl_certificate_key /etc/letsencrypt/live/{domain}/privkey.pem;\n'
            f'ssl_protocols TLSv1.2 TLSv1.3;\n{proxy}\n}}\n')


def configure_proxy(domain, http_only, email):
    ACME.mkdir(parents=True, exist_ok=True)
    ACME.chmod(0o755)
    site = Path('/etc/nginx/conf.d/mud86.conf')
    # A rerun must not downgrade an existing HTTPS site during certificate renewal.
    existing_certificate = Path(f'/etc/letsencrypt/live/{domain}/fullchain.pem').is_file()
    site.write_text(nginx_config(domain, tls=existing_certificate and not http_only,
                                 challenge_only=not http_only and not existing_certificate))
    if shutil.which('getenforce') and subprocess.check_output(['getenforce'], text=True).strip() != 'Disabled':
        run('setsebool', '-P', 'httpd_can_network_connect', 'on')
        run('restorecon', '-RF', ACME, '/etc/nginx')
    run('nginx', '-t')
    run('systemctl', 'enable', '--now', 'nginx')
    run('systemctl', 'reload', 'nginx')
    if subprocess.run(['systemctl', 'is-active', '--quiet', 'firewalld']).returncode == 0:
        for service in ('http', 'https'):
            run('firewall-cmd', '--permanent', '--add-service=' + service)
            run('firewall-cmd', '--add-service=' + service)
    if not http_only:
        if not email:
            email = input('Email address for the HTTPS certificate account: ').strip()
        if not email or '\n' in email:
            raise ValueError('A certificate account email is required')
        run('certbot', 'certonly', '--webroot', '-w', ACME, '-d', domain,
            '--non-interactive', '--agree-tos', '--email', email, '--keep-until-expiring')
        site.write_text(nginx_config(domain, tls=True))
        run('nginx', '-t')
        run('systemctl', 'reload', 'nginx')
        hook = Path('/etc/letsencrypt/renewal-hooks/deploy/mud86-nginx')
        hook.parent.mkdir(parents=True, exist_ok=True)
        hook.write_text('#!/bin/sh\n/usr/sbin/nginx -t && /usr/bin/systemctl reload nginx\n')
        hook.chmod(0o755)
        run('systemctl', 'enable', '--now', 'certbot-renew.timer')


def install_control(control=Path('/usr/local/bin/mud86ctl'), alias=Path('/usr/bin/mud86ctl')):
    """Keep the original path and expose it on AlmaLinux's sudo secure_path."""
    if alias.is_symlink():
        if alias.readlink() != control:
            raise FileExistsError(f'Refusing to replace an unrelated command: {alias}')
    elif alias.exists():
        raise FileExistsError(f'Refusing to replace an unrelated command: {alias}')
    if control.is_symlink() or (control.exists() and
                               (not control.is_file() or control.read_text() != CONTROL_WRAPPER)):
        raise FileExistsError(f'Refusing to replace an unrelated command: {control}')
    control.parent.mkdir(parents=True, exist_ok=True)
    alias.parent.mkdir(parents=True, exist_ok=True)
    control.write_text(CONTROL_WRAPPER)
    control.chmod(0o755)
    if not alias.is_symlink():
        alias.symlink_to(control)


def install(args):
    domain = validate_domain(args.domain)
    manifest = json.loads((ROOT / 'deploy/runtime.json').read_text())
    run('dnf', 'install', '-y', 'gcc', 'make', 'git', 'nginx', 'openssl-devel', 'policycoreutils', 'procps-ng', 'tar', 'gzip')
    if not args.http_only:
        run('dnf', 'install', '-y', 'dnf-plugins-core', 'epel-release')
        run('dnf', 'config-manager', '--set-enabled', 'crb')
        run('dnf', 'install', '-y', 'certbot')
    if subprocess.run(['id', '-u', 'mud86'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        run('useradd', '--system', '--home-dir', STATE, '--shell', '/sbin/nologin', 'mud86')
    STATE.mkdir(mode=0o750, parents=True, exist_ok=True)
    shutil.chown(STATE, user='mud86', group='mud86')
    CONFIG.mkdir(mode=0o755, parents=True, exist_ok=True)
    APP.mkdir(parents=True, exist_ok=True)
    if not (STATE / 'game').exists():
        archive = args.image
        if archive is None:
            cache = APP / 'downloads'
            cache.mkdir(exist_ok=True)
            archive = cache / (manifest['archive']['sha256'] + '.tar.gz')
            download(manifest['archive']['url'], archive, manifest['archive']['sha256'])
        install_image(archive, manifest, STATE / 'game')
        for path in [STATE / 'game', *(STATE / 'game').iterdir()]:
            shutil.chown(path, user='mud86', group='mud86')
    else:
        install_image(None, manifest, STATE / 'game')
    release = application_release()
    executable = build_simh(manifest['simh_revision'])
    previous = (APP / 'current').resolve() if (APP / 'current').exists() else None
    if previous and Path('/etc/systemd/system/mud86-runtime.service').exists():
        run('systemctl', 'stop', 'mud86-runtime.service')
    link = APP / '.current-new'
    link.unlink(missing_ok=True)
    link.symlink_to(release)
    link.replace(APP / 'current')
    (CONFIG / 'runtime.env').write_text(f'SIMH_BIN={executable}\n')
    for name in ('mud86-runtime.service', 'mud86-gateway.service'):
        shutil.copyfile(release / 'deploy' / name, Path('/etc/systemd/system') / name)
    run('systemctl', 'daemon-reload')
    # reset-failed does not load newly installed units on a first installation.
    subprocess.run(['systemctl', 'reset-failed', 'mud86-runtime.service', 'mud86-gateway.service'],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    run('systemctl', 'enable', '--now', 'mud86-runtime.service')
    # This stdout is the operator's terminal, not a systemd service transcript.
    run('runuser', '-u', 'mud86', '--', release / '.venv/bin/python', '-m', 'tools.provision_archwizards',
        '--port', '2020', '--state-dir', STATE / 'private', '--show-credentials', cwd=release)
    run('runuser', '-u', 'mud86', '--', release / '.venv/bin/python', '-m', 'tools.inspect_game',
        'inspection-install', cwd=release)
    (CONFIG / 'provisioned').write_text('All seven archwizard records verified nonzero.\n')
    run('systemctl', 'start', 'mud86-gateway.service')
    configure_proxy(domain, args.http_only, args.email)
    (CONFIG / 'deployment.json').write_text(json.dumps({'domain': domain, 'release': release.name}, indent=2) + '\n')
    install_control()
    print(f'MUD ready: {"http" if args.http_only else "https"}://{domain}')
    print('Management: sudo mud86ctl status | restart | backup | personas | files | errors')


def write_backup(state, directory):
    """Caller must hold the runtime lock and have confirmed a clean shutdown."""
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)
    path = directory / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ') + '.tar.gz')
    temporary = path.with_suffix('.part')
    try:
        with temporary.open('xb') as stream:
            os.fchmod(stream.fileno(), 0o600)
            with tarfile.open(fileobj=stream, mode='w:gz') as archive:
                for name in ('game', 'private'):
                    archive.add(state / name, arcname=name)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.rename(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def backup():
    active = subprocess.run(['systemctl', 'is-active', '--quiet', 'mud86-runtime.service']).returncode == 0
    run('systemctl', 'stop', 'mud86-runtime.service')
    try:
        with (STATE / 'runtime.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if not json.loads((STATE / 'shutdown.json').read_text())['clean']:
                raise RuntimeError('Guest shutdown was not confirmed clean; recover and stop it before backing up')
            path = write_backup(STATE, Path('/var/backups/mud86'))
            print('Private backup:', path)
    finally:
        if active:
            run('systemctl', 'start', 'mud86-runtime.service', 'mud86-gateway.service')


def main():
    # The installed wrapper executes this file directly, so make sibling tools
    # importable without depending on the operator's working directory.
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from tools import inspect_game
    if len(sys.argv) > 1 and sys.argv[1] in inspect_game.ACTIONS:
        if os.geteuid() != 0:
            raise SystemExit('Run this command with sudo')
        # Journal followers must not hold the installer/guest maintenance lock.
        if sys.argv[1] == 'errors' or (sys.argv[1] == 'logs' and 'game' not in sys.argv[2:]):
            raise SystemExit(inspect_game.main(sys.argv[1:]))
        with Path('/run/mud86-setup.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise SystemExit('Another maintenance operation is running; try again shortly')
            raise SystemExit(inspect_game.main(sys.argv[1:]))
    parser = argparse.ArgumentParser(description=__doc__,
        epilog='Inspection commands: personas, persona NAME, files, file NAME, logs SOURCE, errors, inspection-install. '
               'Use mud86ctl COMMAND --help for inspection options.')
    parser.add_argument('action', nargs='?', choices=('install', 'status', 'restart', 'stop', 'start', 'backup'), default='install')
    parser.add_argument('--domain', default='mud.etimbo.com')
    parser.add_argument('--email')
    parser.add_argument('--http-only', action='store_true', help='Explicit HTTP-only mode for private acceptance testing')
    parser.add_argument('--image', type=Path, help='Use a local archive matching the pinned manifest')
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('Run this command with sudo')
    # Public application snapshots must remain readable by the service account
    # even if the operator uses a restrictive umask. Private data uses explicit modes.
    os.umask(0o022)
    if args.action == 'status':
        run('systemctl', 'status', '--no-pager', 'mud86-runtime', 'mud86-gateway', 'nginx')
        return
    with Path('/run/mud86-setup.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action == 'install':
            install(args)
        elif args.action == 'backup':
            backup()
        else:
            run('systemctl', args.action, 'mud86-runtime.service')
            if args.action in ('start', 'restart'):
                run('systemctl', 'start', 'mud86-gateway.service')


if __name__ == '__main__':
    main()
