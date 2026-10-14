"""Shared fresh-container acceptance sequence for GitHub and local Docker hosts.

Requires the host test environment and pinned runtime archive already installed.
Containers and their failed disks are retained. All network checks use loopback.
"""
import argparse
import json
from pathlib import Path
import platform
import subprocess
import sys
import time

from tests.integration_external_deployment import redacted_output

ROOT = Path(__file__).resolve().parents[1]
START_TIMEOUT = 60
STAGE_TIMEOUT = 3600
STOP_TIMEOUT = 240


class Lifecycle:
    def __init__(self, output, *, native_only=False, prefix='mud86', assets=None,
                 guest_diagnostics=True):
        self.output = Path(output)
        self.native_only = native_only
        self.prefix = prefix
        self.assets = Path(assets or ROOT / 'runtime/release-v1').resolve()
        self.guest_diagnostics = guest_diagnostics
        self.containers = []
        self.report = {'complete': False, 'host': platform.platform(),
                       'host_architecture': platform.machine(), 'stages': [], 'shutdowns': {}}

    def execute(self, command, *, timeout=STAGE_TIMEOUT):
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        text = redacted_output(result.stdout, result.stderr)
        if result.returncode:
            raise RuntimeError(text or f'Command failed: {command[0]}')
        return text

    def stage(self, name, command, *, timeout=STAGE_TIMEOUT):
        print('Lifecycle: ' + name, flush=True)
        try:
            text = self.execute(command, timeout=timeout)
        except subprocess.TimeoutExpired as error:
            text = redacted_output(error.stdout, error.stderr)
            text += '\n[stage timed out]\n'
            (self.output / (name + '.log')).write_text(text)
            raise
        except RuntimeError as error:
            (self.output / (name + '.log')).write_text(str(error))
            raise
        (self.output / (name + '.log')).write_text(text)
        self.report['stages'].append(name)
        self.save_report()
        return text

    def save_report(self):
        (self.output / 'report.json').write_text(json.dumps(self.report, indent=2) + '\n')

    def prepare(self):
        self.report['commit'] = self.execute(['git', 'rev-parse', 'HEAD']).strip()
        self.report['working_tree'] = self.execute(['git', 'status', '--short'])
        self.report['python'] = sys.version
        self.report['docker'] = self.execute(['docker', 'version', '--format', '{{json .Server}}']).strip()
        self.report['runtime_sha256'] = self.execute(
            [sys.executable, '-c', 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())',
             str(self.assets / 'mud86-runtime.tar.gz')]).strip()
        self.stage('build', ['docker', 'build', '-t', self.prefix + '-alma9', '-f',
                             'deploy/Dockerfile.alma9', '.'])
        self.report['image'] = self.execute(['docker', 'image', 'inspect', self.prefix + '-alma9',
                                            '--format', '{{.Id}} {{.Architecture}}']).strip()

    def start(self, name, ports):
        command = ['docker', 'run', '-d', '--name', name, '--privileged', '--cgroupns=host',
                   '--cpus=1', '--memory=2g', '--tmpfs', '/run', '--tmpfs', '/tmp',
                   '-v', '/sys/fs/cgroup:/sys/fs/cgroup:rw', '-v', str(ROOT) + ':/checkout:ro',
                   '-v', str(self.assets) + ':/artifacts:ro']
        for port in ports:
            command.extend(['-p', port])
        command.append(self.prefix + '-alma9')
        self.stage('start-' + name, command)
        self.containers.append(name)
        self.wait_systemd(name)

    def wait_systemd(self, name):
        deadline = time.monotonic() + START_TIMEOUT
        while time.monotonic() < deadline:
            try:
                self.execute(['docker', 'exec', name, 'systemctl', 'show-environment'], timeout=10)
                return
            except RuntimeError:
                time.sleep(1)
        raise RuntimeError('Systemd did not become ready: ' + name)

    def browser(self, name, tls=False):
        url = ('https://mud.etimbo.com:38443' if tls else 'http://mud.etimbo.com:38080')
        screenshot = self.output.resolve() / (name + '.png')
        expression = ('import asyncio; from pathlib import Path; from tests.browser_smoke import main; asyncio.run(main('
                      + repr(url) + ', screenshot=Path(' + repr(str(screenshot)) + '), '
                      + 'launch_args=["--host-resolver-rules=MAP mud.etimbo.com 127.0.0.1"], '
                      + f'ignore_https_errors={tls}))')
        self.stage(name, [sys.executable, '-c', expression])

    def stages(self):
        native = self.prefix + '-install-test'
        self.start(native, ['127.0.0.1:38080:80', '127.0.0.1:38443:443'])
        self.stage('native-install', [sys.executable, '-m', 'tests.integration_deployment', '--container', native])
        if self.native_only:
            return
        self.browser('browser-http')
        self.stage('tls', ['docker', 'exec', '-w', '/checkout', native,
                          '/opt/mud86/current/.venv/bin/python', '-m', 'tests.deployment_tls_fixture'])
        self.browser('browser-https', tls=True)
        self.stop_guest(native)
        self.stage('reboot', ['docker', 'restart', '--timeout', '180', native])
        self.wait_systemd(native)
        self.stage('start-after-reboot', ['docker', 'exec', native, 'systemctl', 'start',
                                        'mud86-runtime.service', 'mud86-gateway.service', 'nginx'])
        self.browser('browser-after-reboot', tls=True)
        self.stage('cutover', [sys.executable, '-m', 'tests.integration_external_deployment',
                              '--container', native, '--native-url', 'https://127.0.0.1:38443'])
        external = self.prefix + '-external-fresh'
        self.start(external, ['127.0.0.1:48080:80'])
        self.stage('fresh-external', [sys.executable, '-m', 'tests.integration_external_deployment',
                                     '--fresh', '--container', external, '--url', 'http://127.0.0.1:48080'])
        self.stage('editor', ['docker', 'exec', '-w', '/checkout', native, 'runuser', '-u', 'mud86', '--',
                             '/opt/mud86/current/.venv/bin/python', '-m', 'tests.integration_database_access',
                             '--output', '/var/lib/mud86/editor-acceptance'])
        self.stage('editor-report', ['docker', 'cp', native + ':/var/lib/mud86/editor-acceptance/report.json',
                                    str(self.output / 'editor-report.json')])

    def stop_guest(self, container):
        for service in ('mud86-gateway.service', 'mud86-runtime.service'):
            self.execute(['docker', 'exec', container, 'systemctl', 'stop', service], timeout=STOP_TIMEOUT)
        marker = self.execute(['docker', 'exec', container, '/usr/bin/python3.12', '-c',
                               'from pathlib import Path; print(Path("/var/lib/mud86/shutdown.json").read_text())'],
                              timeout=10)
        clean = json.loads(marker).get('clean') is True
        self.report['shutdowns'][container] = clean
        if not clean:
            raise RuntimeError('Final guest shutdown was not confirmed clean: ' + container)

    def finish(self):
        errors = []
        for container in self.containers:
            try:
                self.stop_guest(container)
            except Exception as error:
                errors.append(str(error))
        if errors:
            raise RuntimeError('\n'.join(errors))
        self.report['complete'] = True

    def diagnostics(self):
        from tests.deployment_diagnostics import collect_all
        collect_all(self.output / 'diagnostics', containers=self.containers,
                    guest=self.guest_diagnostics)

    def run(self):
        self.output.mkdir(mode=0o700, parents=True, exist_ok=False)
        failed = False
        try:
            self.prepare()
            self.stages()
        except BaseException:
            failed = True
            raise
        finally:
            try:
                try:
                    self.diagnostics()
                finally:
                    self.finish()
            except Exception as error:
                self.report['complete'] = False
                self.report['cleanup_error'] = str(error)
                if not failed:
                    raise
            finally:
                # Capture shutdown-time evidence too; do not enter a stopped guest.
                from tests.deployment_diagnostics import collect_all
                collect_all(self.output / 'after-shutdown', containers=self.containers, guest=False)
                self.report['complete'] = self.report['complete'] and not failed
                self.save_report()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--assets', type=Path)
    parser.add_argument('--prefix', default='mud86')
    parser.add_argument('--native-only', action='store_true')
    parser.add_argument('--no-guest-diagnostics', action='store_true')
    args = parser.parse_args()
    if not args.prefix or any(char not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for char in args.prefix):
        parser.error('prefix must be a lowercase Docker name')
    Lifecycle(args.output, native_only=args.native_only, prefix=args.prefix, assets=args.assets,
              guest_diagnostics=not args.no_guest_diagnostics).run()
