"""Install a self-signed HTTPS fixture ONLY inside the disposable CI container.

This checks Nginx/WSS and the AlmaLinux Certbot package/timer, not public ACME
issuance. The real installer still uses Certbot and normal certificate validation.
"""
from pathlib import Path
import subprocess

from tools.deploy import nginx_config, run


def main():
    if not Path('/.dockerenv').exists():
        raise RuntimeError('This test fixture must run in the disposable Docker container')
    run('dnf', 'install', '-y', 'dnf-plugins-core', 'epel-release')
    run('dnf', 'config-manager', '--set-enabled', 'crb')
    run('dnf', 'install', '-y', 'certbot')
    run('certbot', '--version')
    if not Path('/usr/lib/systemd/system/certbot-renew.timer').is_file():
        raise AssertionError('Expected AlmaLinux certificate renewal timer is missing')
    directory = Path('/etc/letsencrypt/live/mud.etimbo.com')
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    run('openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
        '-subj', '/CN=mud.etimbo.com', '-addext', 'subjectAltName=DNS:mud.etimbo.com',
        '-keyout', directory / 'privkey.pem', '-out', directory / 'fullchain.pem',
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    (directory / 'privkey.pem').chmod(0o600)
    Path('/etc/nginx/conf.d/mud86.conf').write_text(nginx_config('mud.etimbo.com', tls=True))
    run('nginx', '-t')
    run('systemctl', 'reload', 'nginx')


if __name__ == '__main__':
    main()
