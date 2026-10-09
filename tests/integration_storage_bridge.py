"""Secondary-terminal bridge experiment on a disposable historical TOPS-10 disk."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import socket
import threading
import time
from unittest.mock import patch

import pexpect

from tools.audit_archwizards import MAX_BOOT_ATTEMPTS
from tools.benchmark_idle import Emulator
from tools.inspect_game import NativeInspector
from tools.storage_bridge import Frame, WORD_MASK, respond
from tests.integration_provisioning import source_hashes, require

ROOT = Path(__file__).resolve().parents[1]
BRIDGE_LINES = (6, 7)
DZ_LINE_COUNT = 32  # Pinned pdp10_defs.h: four eight-line DZ multiplexers.
HOST_TIMEOUT = 15
GUEST_TIMEOUT_BOUND = 10
TEST_WORDS = [0, WORD_MASK, 1 << 35, (1 << 35) - 1] + [1 << bit for bit in range(36)]


def verify_reserved_lines(port):
    import telnetlib
    connections, lines = [], []
    try:
        # Exhaust only this disposable instance's ordinary pool without LOGIN.
        ordinary = set(range(DZ_LINE_COUNT)) - set(BRIDGE_LINES)
        for _ in ordinary:
            client = telnetlib.Telnet('127.0.0.1', port, HOST_TIMEOUT)
            connections.append(client)
            banner = client.read_until(b'device, line ', HOST_TIMEOUT)
            require(b'device, line ' in banner, 'Missing ordinary-line banner')
            lines.append(int(client.read_until(b'\n', HOST_TIMEOUT).strip()))
        require(set(lines) == ordinary, 'Reserved bridge line entered ordinary pool')
        with telnetlib.Telnet('127.0.0.1', port, HOST_TIMEOUT) as overflow:
            text = overflow.read_until(b'All connections busy\r\n', HOST_TIMEOUT)
            require(b'All connections busy\r\n' in text, 'Ordinary pool reached a reserved line')
        return lines
    finally:
        for client in connections:
            client.close()


def private_emulator(directory, ports, *, reuse=False):
    # Finalize the configuration before SIMH opens its DO script.
    spawn = pexpect.spawn
    def start(executable, args, **kwargs):
        config = Path(args[0])
        attachments = ''.join(f'attach dz Line={line},127.0.0.1:{port};notelnet\n'
                               for line, port in ports.items())
        text = config.read_text().replace('boot tu0\n', attachments + 'set throttle 5M\nboot tu0\n')
        config.write_text(text)
        return spawn(executable, args, **kwargs)
    with patch('pexpect.spawn', start):
        return Emulator(directory, 'noidle', reuse=reuse, speed_factor=8)


def connect_slave(machine, line, port):
    # The first CR activates this SLAVE line; it cannot start a monitor job.
    for setting in ('slave', 'echo'):
        text = machine.command(f'set tty tty{line:o}: {setting}')
        require('?' not in text, 'Slave setup failed: ' + text)
    channel = socket.create_connection(('127.0.0.1', port), HOST_TIMEOUT)
    try:
        channel.settimeout(HOST_TIMEOUT)
        channel.sendall(b'\r')
        bootstrap = b''
        while len(bootstrap) < 2:
            data = channel.recv(2 - len(bootstrap))
            require(data, 'Slave bootstrap disconnected')
            bootstrap += data
        require(bootstrap == b'\r\n', 'Unexpected slave bootstrap: ' + repr(bootstrap))
        text = machine.command(f'set tty tty{line:o}: no echo')
        require('?' not in text, 'Cannot disable slave echo: ' + text)
        return channel
    except BaseException:
        channel.close()
        raise


def exercise(native, channel, output, name, line, session, mode='normal', barrier=None):
    frames, wire = [], []
    result = {'session': session, 'line': line, 'mode': mode, 'passed': False}
    class ExperimentSocket:
        first = True
        def settimeout(self, timeout):
            channel.settimeout(timeout)
        def recv(self, size):
            data = channel.recv(size)
            wire.append({'receive': data.hex()})
            return data
        def sendall(self, data):
            action = mode if self.first else 'normal'
            self.first = False
            if action in ('stale-session', 'stale-request', 'wrong-word'):
                # All fault injection stays in this disposable integration test.
                original = frames[-1]
                data = Frame('PONG', session + (action == 'stale-session'),
                             original['request'] + (action == 'stale-request'),
                             original['word'] ^ (action == 'wrong-word')).encode()
            elif action == 'malformed':
                data = data[:10] + b'\n' + data[10:]
            elif action == 'partial':
                data = data[:8]
            elif action == 'silence':
                return
            elif action == 'disconnect':
                channel.shutdown(socket.SHUT_RDWR)
                return
            wire.append({'send': data.hex()})
            if action == 'fragmented':
                for byte in data:
                    channel.sendall(bytes([byte]))
                    time.sleep(0.01)
            else:
                channel.sendall(data)

    def host():
        try:
            respond(ExperimentSocket(), timeout=HOST_TIMEOUT,
                    on_request=lambda frame: frames.append(frame.__dict__))
        except Exception as error:
            result['host_error'] = repr(error)
            raise

    try:
        native.command('run brgp', b'BRGP READY\r\n')
        if barrier:
            barrier.wait(HOST_TIMEOUT)
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(host)
            started = time.monotonic()
            try:
                text = native.command(f'{line} {session}')
            finally:
                try:
                    channel.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            future.result()
        elapsed = time.monotonic() - started
        result.update(seconds=round(elapsed, 3), transcript=text, requests=len(frames))
        if mode in ('normal', 'fragmented'):
            require(f'BRGP DONE {session} 40' in text, 'Guest probe failed: ' + text)
            require([frame['word'] for frame in frames] == TEST_WORDS, 'Native word vector differs')
            require([frame['request'] for frame in frames] == list(range(1, 41)), 'Native sequence differs')
            decoded = re.findall(r'BRGP OK (\d+) (\d+) ([0-7]+)\r?\n', text)
            require([(int(s), int(n), int(w, 8)) for s, n, w in decoded] ==
                    [(session, index + 1, word) for index, word in enumerate(TEST_WORDS)],
                    'Guest did not reconstruct all returned 36-bit words')
        else:
            outcome = 'TIMEOUT' if mode in ('silence', 'partial', 'disconnect') else 'BAD_REPLY'
            require(f'BRGP {outcome} {session} 1' in text, 'Unexpected failure outcome: ' + text)
            require('BRGP OK' not in text and 'BRGP DONE' not in text, 'Invalid response accepted')
            require(elapsed < GUEST_TIMEOUT_BOUND, 'Guest failure exceeded host wall-time bound')
            require(len(frames) == 1, 'Guest continued after failed request')
        require('B1 PING' not in text and 'B1 PONG' not in text, 'Bridge leaked into controlling terminal')
        result['passed'] = True
        print(f'Bridge {name}: {len(frames)} requests, {elapsed:.3f}s, passed', flush=True)
        return result
    finally:
        result['frames'] = frames
        (output / f'{name}.json').write_text(json.dumps(result, indent=2) + '\n')
        (output / f'{name}-wire.json').write_text(json.dumps(wire) + '\n')


def run(output):
    output.mkdir(mode=0o700)
    original = source_hashes()
    machine = None
    report = {'complete': False, 'cases': {}}
    try:
        reservations = [socket.socket() for _ in BRIDGE_LINES]
        ports = {}
        try:
            for line, reservation in zip(BRIDGE_LINES, reservations):
                reservation.bind(('127.0.0.1', 0))
                ports[line] = reservation.getsockname()[1]
        finally:
            for reservation in reservations:
                reservation.close()
        for attempt in range(MAX_BOOT_ATTEMPTS):
            print('Bridge private boot:', attempt + 1, flush=True)
            machine = private_emulator(output / f'machine-{attempt + 1}', ports)
            try:
                machine.boot()
                break
            except Exception:
                machine.stop()
                machine = None
                if attempt + 1 == MAX_BOOT_ATTEMPTS:
                    raise

        class ProbeInspector(NativeInspector):
            def receive(self, marker):
                text = super().receive(marker)
                with (output / 'maintenance.txt').open('a') as stream:
                    stream.write(text)
                return text

        for line in BRIDGE_LINES:
            text = machine.command(f'set tty tty{line:o}: slave')
            require('?' not in text, 'Cannot slave terminal: ' + text)
        report['ordinary_pool_lines'] = verify_reserved_lines(machine.port)
        with ProbeInspector(machine.port) as native:
            native.command('assign dsk: bcl:')
            native.command('set tty no altmode')
            native.install_source('brgp', (ROOT / 'tools/fixtures/BRGP.BCL').read_text())
            native.command('copy brbef.pm=mud.?pm')
            native.command('assign tty7: brg:')
            modes = ('normal', 'malformed', 'fragmented', 'stale-session', 'stale-request',
                     'wrong-word', 'silence', 'partial', 'disconnect', 'recovery')
            for session, mode in enumerate(modes, 1):
                with connect_slave(machine, 7, ports[7]) as channel:
                    if mode == 'normal':
                        # A slaved, assigned secondary terminal must not execute
                        # this as a monitor command. BRGP clears it before use.
                        channel.sendall(b'daytime\r')
                        channel.settimeout(0.5)
                        try:
                            unexpected = channel.recv(256)
                        except socket.timeout:
                            report['slave_has_no_monitor'] = True
                        else:
                            raise AssertionError('Slave acted as a monitor: ' + repr(unexpected))
                    report['cases'][mode] = exercise(native, channel, output, mode, 7, session,
                                                    'normal' if mode == 'recovery' else mode)
            with ProbeInspector(machine.port) as other:
                other.command('assign tty6: brg:')
                with connect_slave(machine, 7, ports[7]) as first, connect_slave(machine, 6, ports[6]) as second:
                    barrier = threading.Barrier(2)
                    with ThreadPoolExecutor(max_workers=2) as executor:
                        jobs = [executor.submit(exercise, user, channel, output, name, line, session,
                                                'normal', barrier)
                                for user, channel, name, line, session in (
                                    (native, first, 'parallel-a', 7, 101),
                                    (other, second, 'parallel-b', 6, 202))]
                        for name, future in zip(('parallel-a', 'parallel-b'), jobs):
                            report['cases'][name] = future.result()
                other.command('deassign tty6:')
            native.command('deassign tty7:')
            native.command('copy braft.pm=mud.?pm')
            native.command('r filcom', b'\n*')
            comparison = native.command('tty:=brbef.pm,braft.pm/b', b'\n*')
            require('No differences encountered' in comparison, 'Persona file changed')
            native.connection.write(b'\x1a')
            native.receive(b'\n.')
            native.at_monitor = True
            report['persona_file_byte_identical'] = True
        require(source_hashes() == original, 'Original source changed')
        report.update(complete=True, source_unchanged=True)
        print('Bridge checks complete; evidence:', output, flush=True)
    finally:
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        if machine is not None:
            machine.stop()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path,
                        default=ROOT / 'runtime' / f'storage-bridge-{time.time_ns()}')
    run(parser.parse_args().output.resolve())
