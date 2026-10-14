"""Repeat pre-persona admission on a disposable native disk; retain failure evidence."""
import argparse
import asyncio
import json
import logging
from pathlib import Path
import ssl
import subprocess
import time
from unittest.mock import patch

from aiohttp import ClientSession, WSMsgType
from aiohttp.test_utils import TestServer

from server.gateway import SimhClient, create_app, LOG
from tests.integration_gateway_cleanup import Capture, deployment_emulator
from tests.integration_provisioning import require, source_hashes
from tools import benchmark_idle
from tools.deploy import install_image

ROOT = Path(__file__).resolve().parents[1]
WIRE_LIMIT = 8192
ADMISSION_TIMEOUT = 20


async def exercise(machine, output, attempts, interval):
    # No persona/password is submitted in this probe. Capture only this private
    # test's bounded upstream bytes, never a live player's terminal transcript.
    wires = []

    class CaptureClient(SimhClient):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.wire = bytearray()
            wires.append(self.wire)

        def data_received(self, data):
            self.wire.extend(data[:max(0, WIRE_LIMIT - len(self.wire))])
            super().data_received(data)

    cases = []
    with patch('server.gateway.SimhClient', CaptureClient):
        async with TestServer(create_app(upstream_port=machine.port)) as server, ClientSession() as client:
            for attempt in range(attempts):
                start = time.monotonic()
                received = ''
                case = {'attempt': attempt + 1, 'success': False}
                try:
                    async with client.ws_connect(server.make_url('/terminal')) as socket:
                        async with asyncio.timeout(ADMISSION_TIMEOUT):
                            while 'By what name shall I call you?' not in received:
                                message = await socket.receive()
                                require(message.type == WSMsgType.TEXT, 'Socket closed before admission')
                                received += message.data
                            case['success'] = True
                except Exception as error:
                    case['error'] = type(error).__name__ + ': ' + str(error)
                case.update(elapsed=time.monotonic() - start, browser_output=received)
                case['systat'] = await asyncio.to_thread(machine.command, 'systat')
                cases.append(case)
                (output / 'admissions.json').write_text(json.dumps(cases, indent=2) + '\n')
                (output / 'prelogin-wire.json').write_text(json.dumps(
                    [bytes(wire).hex() for wire in wires], indent=2) + '\n')
                print('Admission', attempt + 1, case['success'], round(case['elapsed'], 3), flush=True)
                await asyncio.sleep(interval)
    return cases


async def exercise_browsers(machine, output, rounds, interval, tls=False):
    from tests.browser_smoke import main
    cases = []
    context = None
    if tls:
        cert, key = output / 'test-cert.pem', output / 'test-key.pem'
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                        '-keyout', str(key), '-out', str(cert), '-days', '1',
                        '-subj', '/CN=localhost'], check=True, capture_output=True, timeout=30)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
    server = TestServer(create_app(upstream_port=machine.port))
    try:
        await server.start_server(ssl=context)
        for index in range(rounds):
            case = {'round': index + 1, 'success': False}
            try:
                await main(str(server.make_url('/')), screenshot=output / f'browser-{index + 1}.png',
                           ignore_https_errors=tls)
                case['success'] = True
            except Exception as error:
                case['error'] = type(error).__name__ + ': ' + str(error)
            case['systat'] = await asyncio.to_thread(machine.command, 'systat')
            cases.append(case)
            (output / 'browser-rounds.json').write_text(json.dumps(cases, indent=2) + '\n')
            print('Browser round', index + 1, case['success'], flush=True)
            await asyncio.sleep(interval)
    finally:
        await server.close()
    return cases


def run(output, assets, attempts, interval, archive=None, browser_rounds=0, tls=False):
    output.mkdir(mode=0o700)
    original = source_hashes()
    report = {'complete': False}
    machine = None
    capture = Capture()
    old_level = LOG.level
    LOG.setLevel(logging.INFO)
    LOG.addHandler(capture)
    try:
        if archive:
            install_image(archive, json.loads((ROOT / 'deploy/runtime.json').read_text()), output / 'machine')
        with patch.object(benchmark_idle, 'ROOT', assets):
            machine = deployment_emulator(output / 'machine', reuse=archive is not None)
        machine.boot()
        (output / 'initial-systat.txt').write_text(machine.command('systat'))
        cases = asyncio.run(exercise_browsers(machine, output, browser_rounds, interval, tls)
                            if browser_rounds else exercise(machine, output, attempts, interval))
        report['passed'] = sum(case['success'] for case in cases)
        report['attempts'] = len(cases)
        report['source_unchanged'] = original == source_hashes()
        machine.command('r opr', 'OPR>')
        machine.child.send('set ksys now\r')
        machine.child.expect_exact('KSYS processing completed', timeout=120)
        report['clean_shutdown'] = True
        require(report['source_unchanged'], 'Original source changed')
        require(report['passed'] == len(cases), 'Admission failure; see private evidence')
        report['complete'] = True
    finally:
        LOG.removeHandler(capture)
        LOG.setLevel(old_level)
        (output / 'gateway-log.json').write_text(json.dumps(capture.messages, indent=2) + '\n')
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        if machine is not None:
            machine.stop()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--assets', type=Path, default=ROOT,
                        help='Checkout containing stopped baseline runtime and SIMH')
    parser.add_argument('--attempts', type=int, default=24)
    parser.add_argument('--interval', type=float, default=3)
    parser.add_argument('--archive', type=Path, help='Use the pinned deployment runtime archive')
    parser.add_argument('--browser-rounds', type=int, default=0, help='Run two-tab Chromium smoke rounds instead')
    parser.add_argument('--tls', action='store_true', help='Use private test-certificate HTTPS/WSS for browser rounds')
    args = parser.parse_args()
    if args.attempts < 1 or args.interval < 0 or args.browser_rounds < 0:
        parser.error('Use positive attempts and nonnegative interval/browser rounds')
    if args.tls and not args.browser_rounds:
        parser.error('--tls requires --browser-rounds')
    run(args.output.resolve(), args.assets.resolve(), args.attempts, args.interval, args.archive, args.browser_rounds,
        args.tls)
