"""Suppress an actual boot OPR reply on disposable guests; never replay the body.

This is a transport-fault control, not a reproduction of OPR's underlying stall.
All native boot/cleanup commands use production Runtime. No clean marker is faked.
"""
import argparse
from contextlib import redirect_stdout
import json
from pathlib import Path
import socket
from unittest.mock import patch

import pexpect
from server.runtime import BOOT_ATTEMPTS, OPERATOR_PROMPT, Runtime
from tools.deploy import install_image
from tests.integration_provisioning import require, source_hashes

ROOT = Path(__file__).resolve().parents[1]


def exercise(output, assets, executable, *, exhaust=False):
    output.mkdir(mode=0o700)
    state = output / 'machine'
    state.mkdir(mode=0o700)
    install_image(assets / 'runtime/release-v1/mud86-runtime.tar.gz',
                  json.loads((ROOT / 'deploy/runtime.json').read_text()), state / 'game')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    original = source_hashes()
    report = {'complete': False, 'suppressed_replies': 0, 'body_runs': 0,
              'exhaustion_control': exhaust}
    runtime = Runtime(state, executable, port=port, browser_terminals=True)
    real_spawn = pexpect.spawn

    def spawn(*args, **kwargs):
        child = real_spawn(*args, **kwargs)
        real_expect = child.expect_exact
        def expect(marker, *arguments, **options):
            result = real_expect(marker, *arguments, **options)
            if marker == OPERATOR_PROMPT and (exhaust or not report['suppressed_replies']):
                report['suppressed_replies'] += 1
                # The guest really reached OPR, but the controller did not receive
                # its acknowledgement. Do not claim this is a native OPR hang.
                child.before += '[test harness withheld actual OPR acknowledgement]'
                raise pexpect.TIMEOUT('Injected missing OPR acknowledgement')
            return result
        child.expect_exact = expect
        return child

    with (output / 'console.log').open('w') as console, redirect_stdout(console), \
            patch('pexpect.spawn', side_effect=spawn):
        try:
            with runtime.session():
                report['body_runs'] += 1
                report['ready'] = runtime.batch_ready
            require(not exhaust, 'Exhausted startup entered controller body')
            report['clean'] = json.loads((state / 'shutdown.json').read_text())['clean']
            require(report['clean'], 'Recovered guest did not confirm clean shutdown')
            require(report['body_runs'] == 1, 'Controller body was replayed')
        except pexpect.TIMEOUT as error:
            require(exhaust, 'Unexpected actual guest boot timeout: ' + type(error).__name__)
            require(str(error) == 'Injected missing OPR acknowledgement',
                    'Underlying guest stalled before the injection; retain this failed control')
            require(report['suppressed_replies'] == BOOT_ATTEMPTS, 'Startup attempt bound differed')
            require(report['body_runs'] == 0, 'Exhausted startup entered controller body')
            report['clean'] = json.loads((state / 'shutdown.json').read_text())['clean']
            require(not report['clean'], 'Exhausted startup published a clean marker')
        finally:
            if runtime.child is not None:
                runtime.stop()
            report['guest_reaped'] = runtime.child is None
            report['source_unchanged'] = original == source_hashes()
            report['diagnostics'] = len(list((state / 'boot-diagnostics').glob('*.json')))
            (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    require(report['guest_reaped'] and report['source_unchanged'], 'Guest/source preservation failed')
    report['complete'] = True
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--assets', type=Path, default=ROOT)
    parser.add_argument('--simh', type=Path, required=True)
    parser.add_argument('--exhaust', action='store_true')
    args = parser.parse_args()
    exercise(args.output.resolve(), args.assets.resolve(), args.simh.resolve(), exhaust=args.exhaust)
