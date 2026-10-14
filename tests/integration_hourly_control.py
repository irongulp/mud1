"""Witness hourly CTY output and genuine shutdown on a fresh private disk copy."""
import argparse
from contextlib import redirect_stdout
from datetime import datetime, timezone
import json
from pathlib import Path
import socket
import shutil
import time
from unittest.mock import patch

from server.runtime import Runtime, OPERATOR_PROMPT
from tools.deploy import install_image
from tools.terminal_config import protect_bridge_terminals
from tests.integration_provisioning import require, source_hashes

ROOT = Path(__file__).resolve().parents[1]
HOUR_OBSERVATION_SECONDS = 65


def run(output, assets, simh, stopped_disk=None):
    output.mkdir(mode=0o700)
    state = output / 'machine'
    state.mkdir(mode=0o700)
    install_image(assets / 'runtime/release-v1/mud86-runtime.tar.gz',
                  json.loads((ROOT / 'deploy/runtime.json').read_text()), state / 'game')
    if stopped_disk:
        marker = stopped_disk.parent.parent / 'shutdown.json'
        require(json.loads(marker.read_text()).get('clean') is True,
                'Supplied disposable disk needs its adjacent verified clean shutdown marker')
        shutil.copyfile(stopped_disk, state / 'game/guest.dsk')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    original = source_hashes()
    machine = Runtime(state, simh, port=port)
    report = {'complete': False}
    with (output / 'console.log').open('w') as console, redirect_stdout(console):
        try:
            # Isolate the hourly announcement from the independent initializer.
            machine.boot()
            protect_bridge_terminals(machine)
            require(machine.stop(), 'Terminal preparation shutdown was not clean')
            report['preparation_clean'] = True
            with patch('server.runtime.datetime') as clock:
                clock.now.return_value = datetime.now(timezone.utc).replace(hour=12, minute=59, second=5)
                machine.boot()
            time.sleep(HOUR_OBSERVATION_SECONDS)
            machine.command('r opr', OPERATOR_PROMPT)
            console.flush()
            transcript = (output / 'console.log').read_text()
            require('Current date/time ' in transcript and '13:00:00' in transcript,
                    'Hourly console announcement was not witnessed')
            report['command_ok'] = True
            require(machine.stop(), 'Hourly control shutdown was not clean')
            report['shutdown_clean'] = True
            require(original == source_hashes(), 'Original source changed')
            report.update(complete=True, source_unchanged=True)
        finally:
            if machine.child is not None:
                report['failure_shutdown_clean'] = machine.stop()
            (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--assets', type=Path, default=ROOT)
    parser.add_argument('--simh', type=Path, required=True)
    parser.add_argument('--stopped-disk', type=Path, help='Optional verified-stopped disposable control disk')
    args = parser.parse_args()
    run(args.output.resolve(), args.assets.resolve(), args.simh.resolve(), args.stopped_disk)
