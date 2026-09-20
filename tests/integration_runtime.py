"""Boot, stop and reboot a fresh extraction of the pinned release image."""
import argparse
import json
from pathlib import Path
import socket
import subprocess
import sys
import time

from tools.deploy import install_image

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--image', type=Path, default=ROOT / 'runtime/release-v1/mud86-runtime.tar.gz')
    parser.add_argument('--simh', type=Path, default=ROOT / 'upstream/simh/BIN/pdp10')
    args = parser.parse_args()
    args.state.mkdir(mode=0o700)
    install_image(args.image, json.loads((ROOT / 'deploy/runtime.json').read_text()), args.state / 'game')
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    for number in range(2):
        with (args.state / f'boot-{number}.log').open('w') as log:
            process = subprocess.Popen([sys.executable, '-u', '-m', 'server.runtime', '--state', str(args.state),
                                        '--simh', str(args.simh), '--port', str(port)], cwd=ROOT,
                                       stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 360
                while not (args.state / 'ready').exists():
                    if process.poll() is not None or time.monotonic() > deadline:
                        raise AssertionError(f'Boot {number} did not become ready; see {log.name}')
                    time.sleep(1)
                print(f'Boot {number}: original game ready', flush=True)
            finally:
                process.terminate()
                try:
                    process.wait(timeout=180)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            if not json.loads((args.state / 'shutdown.json').read_text())['clean']:
                raise AssertionError('Shutdown was not clean')
            print(f'Boot {number}: KSYS shutdown completed', flush=True)


if __name__ == '__main__':
    main()
