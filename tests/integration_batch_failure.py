"""Withhold BATCON on a disposable image and prove readiness/backup stay blocked."""
import argparse
from contextlib import redirect_stdout
import json
from pathlib import Path
import re
import socket

from server.runtime import Runtime
from tools.batch_readiness import BatchReadinessError, ensure_batch_ready, missing_file
from tools.deploy import install_image
from tests.integration_provisioning import require, source_hashes

ROOT = Path(__file__).resolve().parents[1]


def run(output, assets, simh=None):
    output.mkdir(mode=0o700)
    state = output / 'machine'
    state.mkdir(mode=0o700)
    install_image(assets / 'runtime/release-v1/mud86-runtime.tar.gz',
                  json.loads((ROOT / 'deploy/runtime.json').read_text()), state / 'game')
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0)); port = probe.getsockname()[1]
    report = {'complete': False}
    original = source_hashes()

    class FaultRuntime(Runtime):
        def verify_batch(self):
            status = self.command('systat')
            require(not re.search(r'(?m)^\s*\d+ .*\bBATCON\b', status), 'BATCON already running')
            require(missing_file(self.command('directory sys:batbad.exe'), 'sys:batbad.exe'),
                    'Fault fixture filename is occupied')
            self.command('rename sys:batbad.exe=sys:batcon.exe')
            try:
                require(missing_file(self.command('directory sys:batcon.exe'), 'sys:batcon.exe'),
                        'BATCON was not withheld')
                ensure_batch_ready(self.port)
            except BatchReadinessError as error:
                report['probe_phase'] = error.phase
                report['probe_rejected'] = error.phase == 'completion' and error.request is not None
                raise
            finally:
                self.command('rename sys:batcon.exe=sys:batbad.exe')
                report['binary_restored'] = 'BATCON' in self.command('directory sys:batcon.exe')

    machine = FaultRuntime(state, simh or assets / 'upstream/simh/BIN/pdp10', port=port)
    with (output / 'console.log').open('w') as console, redirect_stdout(console):
        try:
            try:
                machine.boot()
            except BatchReadinessError:
                report['readiness_blocked'] = not machine.batch_ready
            require(report.get('readiness_blocked'), 'Failed batch service was admitted')
        finally:
            report['clean_marker'] = machine.stop()
            report['source_unchanged'] = original == source_hashes()
            report['complete'] = bool(report.get('probe_rejected') and report.get('binary_restored')
                                      and report.get('readiness_blocked') and not report['clean_marker']
                                      and report['source_unchanged'])
            (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    require(report['complete'], 'Failure-gate acceptance incomplete')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--assets', type=Path, default=ROOT)
    parser.add_argument('--simh', type=Path, help='Explicit diagnostic emulator on the host architecture')
    args = parser.parse_args()
    run(args.output.resolve(), args.assets.resolve(), args.simh)
