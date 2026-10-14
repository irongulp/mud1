"""Best-effort evidence from both disposable CI containers, before teardown."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
CONTAINERS = ('mud86-external-fresh', 'mud86-install-test')
HOST_TIMEOUT = 30
# The guest helper gets 110 seconds plus 100 seconds for interrupted cleanup.
GUEST_TIMEOUT = 240


def decode_output(value):
    return value.decode('utf-8', errors='replace') if isinstance(value, bytes) else value or ''


def collect_all(output, *, containers=None, guest=True):
    for container in CONTAINERS if containers is None else containers:
        directory = output / container
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        prefix = ['docker', 'exec', '-w', '/checkout', container]
        commands = (
            ('services', ['journalctl', '-u', 'mud86-runtime', '-u', 'mud86-gateway',
                          '-u', 'mud86-database', '--no-pager'], HOST_TIMEOUT),
            ('status', ['systemctl', 'status', 'mud86-runtime', 'mud86-gateway',
                        'mud86-database', 'nginx', '--no-pager', '--full'], HOST_TIMEOUT),
            ('nginx', ['nginx', '-T'], HOST_TIMEOUT),
            ('guest-systat', ['timeout', '--signal=INT', '--kill-after=100s', '110s',
                              '/opt/mud86/current/.venv/bin/python', '-m',
                              'tests.deployment_guest_status'], GUEST_TIMEOUT),
        )
        for name, command, timeout in commands:
            if name == 'guest-systat' and not guest:
                continue
            try:
                result = subprocess.run(prefix + command, capture_output=True, text=True, timeout=timeout)
                evidence = decode_output(result.stdout) + decode_output(result.stderr)
                evidence += f'\n[diagnostic exit status: {result.returncode}]\n'
            except subprocess.TimeoutExpired as error:
                evidence = decode_output(error.stdout) + decode_output(error.stderr)
                evidence += f'\n[diagnostic timed out after {timeout} seconds]\n'
            except OSError as error:
                evidence = f'[diagnostic unavailable: {type(error).__name__}: {error}]\n'
            (directory / (name + '.log')).write_text(evidence)


if __name__ == '__main__':
    collect_all(ROOT / 'runtime/deployment-ci')
