"""Bounded, best-effort evidence from both disposable deployment containers."""
import argparse
from pathlib import Path
import subprocess

CONTAINERS = ('mud86-install-test', 'mud86-external-fresh')
DIAGNOSTIC_TIMEOUT = 30
STOP_TIMEOUT = 180


def capture(command, log, timeout=DIAGNOSTIC_TIMEOUT):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        text = result.stdout + result.stderr + '\nexit_status=' + str(result.returncode) + '\n'
    except subprocess.TimeoutExpired as error:
        def decoded(value):
            return value.decode('utf-8', 'replace') if isinstance(value, bytes) else value or ''
        text = decoded(error.stdout) + decoded(error.stderr) + '\nDiagnostic command timed out\n'
    except OSError as error:
        text = 'Diagnostic command unavailable: ' + type(error).__name__ + '\n'
    log.write_text(text)


def collect(output):
    for container in CONTAINERS:
        directory = output / container
        directory.mkdir(parents=True, exist_ok=True)
        prefix = ['docker', 'exec', container]
        for phase in ('before-stop', 'after-stop'):
            # Deliberately exclude configs, environment variables, database rows
            # and credential files. CTY journals contain controller output only.
            capture(prefix + ['journalctl', '-u', 'mud86-runtime', '-u', 'mud86-gateway',
                              '--no-pager', '--all', '-o', 'short-iso'],
                    directory / (phase + '-services.log'))
            capture(prefix + ['cat', '/var/lib/mud86/shutdown.json'],
                    directory / (phase + '-shutdown.log'))
            capture(prefix + ['systemctl', 'show', 'mud86-runtime', 'mud86-gateway',
                              '-p', 'ActiveState', '-p', 'SubState', '-p', 'Result',
                              '-p', 'ExecMainCode', '-p', 'ExecMainStatus'],
                    directory / (phase + '-units.log'))
            if phase == 'before-stop':
                capture(prefix + ['systemctl', 'stop', 'mud86-runtime.service'],
                        directory / 'cleanup-stop.log', timeout=STOP_TIMEOUT)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('runtime/deployment-ci'))
    collect(parser.parse_args().output)
