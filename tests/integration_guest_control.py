"""Verify production control drivers on a fresh, private deployment-image copy."""
import argparse
from contextlib import redirect_stdout
import json
from pathlib import Path
import socket

from server.runtime import Runtime
from tools.deploy import install_image
from tools.inspect_game import NativeInspector
from tools.reset_permissions import configure_port, protection, EXECUTABLE
from tools.terminal_config import protect_bridge_terminals
from tests.integration_provisioning import require, source_hashes

ROOT = Path(__file__).resolve().parents[1]


def run(output, assets, rounds):
    output.mkdir(mode=0o700)
    state = output / 'machine'
    state.mkdir(mode=0o700)
    install_image(assets / 'runtime/release-v1/mud86-runtime.tar.gz',
                  json.loads((ROOT / 'deploy/runtime.json').read_text()), state / 'game')
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    original = source_hashes()
    report = {'complete': False, 'rounds': 0}
    machine = Runtime(state, assets / 'upstream/simh/BIN/pdp10', port=port)
    try:
        with (output / 'console.log').open('w') as console, redirect_stdout(console):
            machine.boot()
            require(configure_port(port), 'Initial permission change was not applied')
            require(not configure_port(port), 'Permission rerun changed metadata')
            with NativeInspector(port) as native:
                require(protection(native.command('directory ' + EXECUTABLE)) == '051',
                        'Permission read-back failed')
            report['permissions'] = True
            for index in range(rounds):
                # This one fixture-owned file is deliberately reused by the
                # repeated transfer control, never a live configuration file.
                machine.copy_text('ctest.tmp', 'verified control\n')
                response = machine.command('type ctest.tmp')
                require('verified control' in response, 'COPY read-back failed')
                report['rounds'] = index + 1
                (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
            require(protect_bridge_terminals(machine), 'Terminal initializer was not disabled')
            require(not protect_bridge_terminals(machine), 'Configuration rerun was not idempotent')
            report['staged_config'] = True
            require(machine.stop(), 'First shutdown was not clean')
            report['first_shutdown'] = True
            machine.boot()
            require('STOMPR' not in machine.command('systat'), 'Initializer remained after reboot')
            require(not configure_port(port), 'Protection did not survive reboot')
            require(machine.stop(), 'Second shutdown was not clean')
            report['second_shutdown'] = True
        require(original == source_hashes(), 'Original source changed')
        report.update(complete=True, source_unchanged=True)
    finally:
        if machine.child is not None:
            with (output / 'console.log').open('a') as console, redirect_stdout(console):
                machine.child.logfile_read = console
                report['failure_shutdown_clean'] = machine.stop()
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--assets', type=Path, default=ROOT)
    parser.add_argument('--rounds', type=int, default=200)
    args = parser.parse_args()
    if args.rounds < 1:
        parser.error('--rounds must be positive')
    run(args.output.resolve(), args.assets.resolve(), args.rounds)
