"""Verify controller input/staging on a fresh private deployment-image copy."""
import argparse
from contextlib import redirect_stdout
import json
from pathlib import Path
import socket

from server.runtime import Runtime
from tools.deploy import install_image
from tools.inspect_game import NativeInspector
from tools.terminal_config import protect_bridge_terminals
from tests.integration_provisioning import require, source_hashes

ROOT = Path(__file__).resolve().parents[1]


def preserved_personas(native):
    native.command('copy ctrnow.pm=mud.?pm')
    native.command('r filcom', b'\n*')
    native.send('tty:=ctrlpm.pm,ctrnow.pm/b')
    result = native.receive(b'\n*')
    require('No differences encountered' in result, 'Native persona comparison failed: ' + result)
    native.connection.write(b'\x1a')
    native.receive(b'\n.')
    native.at_monitor = True


def run(output, assets, rounds, executable=None):
    output.mkdir(mode=0o700)
    state = output / 'machine'
    state.mkdir(mode=0o700)
    install_image(assets / 'runtime/release-v1/mud86-runtime.tar.gz',
                  json.loads((ROOT / 'deploy/runtime.json').read_text()), state / 'game')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    original = source_hashes()
    report = {'complete': False, 'rounds': 0}
    runtime = Runtime(state, executable or assets / 'upstream/simh/BIN/pdp10', port=port)
    try:
        with (output / 'console.log').open('w') as console, redirect_stdout(console):
            runtime.boot()
            with NativeInspector(port) as native:
                native.command('copy ctrlpm.pm=mud.?pm')
            for index in range(rounds):
                # One fixture-owned scratch file; never reuse a live config file.
                runtime.copy_text('ctest.tmp', 'verified control\n')
                require('verified control' in runtime.command('type ctest.tmp'), 'COPY read-back failed')
                report['rounds'] = index + 1
            require(protect_bridge_terminals(runtime), 'Terminal initializer was not disabled')
            require(not protect_bridge_terminals(runtime), 'Configuration rerun was not idempotent')
            report['staged_config'] = True
            with NativeInspector(port) as native:
                preserved_personas(native)
            require(runtime.stop(), 'First shutdown was not clean')
            report['first_shutdown'] = True
            runtime.boot()
            require('STOMPR' not in runtime.command('systat'), 'Initializer remained after reboot')
            require(not protect_bridge_terminals(runtime), 'Configuration did not survive reboot')
            with NativeInspector(port) as native:
                preserved_personas(native)
            require(runtime.stop(), 'Second shutdown was not clean')
            report['second_shutdown'] = True
        require(original == source_hashes(), 'Original source changed')
        report.update(complete=True, personas_unchanged=True, source_unchanged=True)
    finally:
        if runtime.child is not None:
            with (output / 'console.log').open('a') as console, redirect_stdout(console):
                runtime.child.logfile_read = console
                report['failure_shutdown_clean'] = runtime.stop()
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--assets', type=Path, default=ROOT)
    parser.add_argument('--simh', type=Path, help='Explicit emulator; guest image is still copied fresh')
    parser.add_argument('--rounds', type=int, default=200)
    args = parser.parse_args()
    if args.rounds < 1:
        parser.error('--rounds must be positive')
    run(args.output.resolve(), args.assets.resolve(), args.rounds, args.simh)
