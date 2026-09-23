"""Verify inspection against real AlmaLinux systemd journals in a disposable container."""
import argparse
import json
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]


def run(image):
    name = f'mud86-log-check-{time.time_ns()}'
    def docker(*args, **kwargs):
        return subprocess.run(['docker', *args], check=True, capture_output=True, text=True, **kwargs).stdout
    try:
        docker('run', '-d', '--name', name, '--privileged', '--cgroupns=host',
               '--tmpfs', '/run', '--tmpfs', '/tmp', '-v', '/sys/fs/cgroup:/sys/fs/cgroup:rw',
               '-v', f'{ROOT}:/checkout:ro', image)
        for _ in range(60):
            if subprocess.run(['docker', 'exec', name, 'test', '-S', '/run/dbus/system_bus_socket'],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
                break
            time.sleep(1)
        for unit, messages in (
                ('mud86-runtime', ['KSYS processing completed', '0 errors detected',
                                   'Retrying guest boot (2/3)', 'Emulator exited unexpectedly']),
                ('mud86-gateway', ['INFO:server.gateway:ready',
                                   'WARNING:server.gateway:Terminal logout did not complete; check the guest job'])):
            script = 'print(' + repr('\n'.join(messages)) + ')'
            docker('exec', name, 'systemd-run', '--wait', '--unit', unit,
                   '/usr/bin/python3.12', '-c', script)
        docker('exec', name, 'journalctl', '--sync')
        base = ('exec', name, '/usr/bin/python3.12', '/checkout/tools/deploy.py')
        report = json.loads(docker(*base, 'errors', '--json'))
        codes = {row['code'] for row in report['findings']}
        assert {'boot-retry', 'emulator-exit', 'logout-incomplete'} <= codes, report
        assert report['entries_scanned'] >= 6, report
        assert set(report['coverage']['requested_sources']) <= set(report['sources_observed']), report
        text = docker(*base, 'logs', 'gateway', '--lines', '20')
        assert 'Terminal logout did not complete' in text, text
        assert 'Emulator exited unexpectedly' not in text, text
        empty = json.loads(docker(*base, 'errors', '--since', '2100-01-01', '--json'))
        assert empty['entries_scanned'] == 0 and not empty['findings'], empty
        print(json.dumps({'complete': True, 'image': image, 'codes': sorted(codes),
                          'entries_scanned': report['entries_scanned'], 'source_filter': True,
                          'time_filter': True}, indent=2))
    finally:
        subprocess.run(['docker', 'rm', '-f', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', default='mud86-alma9-arm:latest')
    run(parser.parse_args().image)
