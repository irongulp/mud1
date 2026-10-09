"""Verify a bounded secondary-TTY pool under MUDGUEST on a disposable disk."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import json
from pathlib import Path
import re
import socket
import sys
import threading
import time

from tools.audit_archwizards import Guest, MAX_BOOT_ATTEMPTS
from tools.inspect_game import NativeInspector
from tools.storage_bridge import respond
from tests.integration_provisioning import source_hashes, require
from tests.integration_storage_bridge import (
    ROOT, BRIDGE_LINES, HOST_TIMEOUT, GUEST_TIMEOUT_BOUND, TEST_WORDS,
    private_emulator, connect_slave,
)

AUTO = 8
HOLD = 9
ACCESS = 10
GUEST_PPN = (0o2653 << 18) | 0o2653
PROGRAM = 'dskb:brgp[2011,2776]'


class GuestMonitor(NativeInspector):
    def __init__(self, port, transcript):
        super().__init__(port)
        self.transcript = transcript

    def __enter__(self):
        try:
            guest = Guest(self.port, 'mudguest', [])
            self.connection = guest.connection
            original_read = self.connection.read_until
            def recorded_read(marker, timeout=None):
                data = original_read(marker, timeout)
                with self.transcript.open('a') as stream:
                    stream.write(data.decode('ascii', errors='replace'))
                return data
            self.connection.read_until = recorded_read
            # Stop at the first name question; do not create or save a persona.
            self.connection.write(b'\x03\x03')
            self.receive(b'\n.')
            self.at_monitor = True
            return self
        except BaseException:
            self.__exit__(*sys.exc_info())
            raise

    def start(self, mode, session, marker=b'\n.'):
        self.command('run ' + PROGRAM, b'BRGP READY\r\n')
        return self.command(f'{mode} {session}', marker)


def lease(text):
    match = re.search(r'BRGP LEASE (\d+) ([0-7]+) (\d+)', text)
    require(match is not None, 'Missing native lease: ' + text)
    job, ppn, line = int(match[1]), int(match[2], 8), int(match[3])
    require(ppn == GUEST_PPN, 'Probe did not execute under MUDGUEST')
    require(line in BRIDGE_LINES, 'Guest claimed a non-pool line')
    return {'job': job, 'ppn': f'{ppn >> 18:o},{ppn & 0o777777:o}', 'line': line}


def hold(guest, barrier=None):
    guest.command('run ' + PROGRAM, b'BRGP READY\r\n')
    if barrier:
        barrier.wait(HOST_TIMEOUT)
    return lease(guest.command(f'{HOLD} 1', b'BRGP HOLD\r\n'))


def release(guest, line):
    text = guest.command('')
    require(f'BRGP RELEASED {line}' in text, 'Guest did not release its lease: ' + text)


def exchange(machine, ports, guest, session, silent=False):
    frames = {line: [] for line in BRIDGE_LINES}
    with ExitStack() as stack:
        channels = {line: stack.enter_context(connect_slave(machine, line, ports[line]))
                    for line in BRIDGE_LINES}
        with ThreadPoolExecutor(max_workers=len(channels)) as executor:
            futures = []
            if not silent:
                for line, channel in channels.items():
                    futures.append(executor.submit(respond, channel, timeout=HOST_TIMEOUT,
                        on_request=lambda frame, line=line: frames[line].append(frame)))
            started = time.monotonic()
            try:
                text = guest.start(AUTO, session)
            finally:
                for channel in channels.values():
                    try:
                        channel.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
            for future in futures:
                future.result()
        seconds = time.monotonic() - started
    result = lease(text)
    require(f'BRGP RELEASED {result["line"]}' in text, 'Lease survived a normal/error exit')
    if silent:
        require(f'BRGP TIMEOUT {session} 1' in text, 'Missing bounded transport failure')
        require(seconds < GUEST_TIMEOUT_BOUND, 'Transport timeout exceeded host bound')
    else:
        require(f'BRGP DONE {session} {len(TEST_WORDS)}' in text, 'Guest transport failed: ' + text)
        require([frame.word for frame in frames[result['line']]] == TEST_WORDS,
                'Guest word vector differs')
        require(not frames[next(line for line in BRIDGE_LINES if line != result['line'])],
                'Guest transmitted on an unowned channel')
    result.update(seconds=round(seconds, 3), transcript=text)
    return result


def run(output):
    output.mkdir(mode=0o700)
    original = source_hashes()
    machine = None
    report = {'complete': False, 'cases': {}}
    try:
        with ExitStack() as stack:
            reservations = [stack.enter_context(socket.socket()) for _ in BRIDGE_LINES]
            ports = {}
            for line, reservation in zip(BRIDGE_LINES, reservations):
                reservation.bind(('127.0.0.1', 0))
                ports[line] = reservation.getsockname()[1]
        for attempt in range(MAX_BOOT_ATTEMPTS):
            print('MUDGUEST channel boot:', attempt + 1, flush=True)
            machine = private_emulator(output / f'machine-{attempt + 1}', ports)
            try:
                machine.boot()
                machine.command('daytime')
                for line in BRIDGE_LINES:
                    text = machine.command(f'set tty tty{line:o}: slave')
                    require('?' not in text, 'Cannot configure slave: ' + text)
                break
            except Exception as error:
                report.setdefault('boot_failures', []).append(type(error).__name__)
                machine.stop()
                machine = None
                if attempt + 1 == MAX_BOOT_ATTEMPTS:
                    raise
        with NativeInspector(machine.port) as installer:
            installer.command('assign dsk: bcl:')
            installer.command('set tty no altmode')
            installer.install_source('brgp', (ROOT / 'tools/fixtures/BRGP.BCL').read_text())
            installer.command('protect brgp.exe<055>')
            installer.command('copy chbef.pm=mud.?pm')
            with GuestMonitor(machine.port, output / 'a.txt') as a, \
                    GuestMonitor(machine.port, output / 'b.txt') as b, \
                    GuestMonitor(machine.port, output / 'c.txt') as c:
                print('MUDGUEST automatic claim and word exchange', flush=True)
                report['cases']['automatic'] = exchange(machine, ports, a, 101)
                print('Automatic exchange passed; checking ownership', flush=True)
                first = hold(a)
                report['cases']['first_owner'] = first
                denied = b.start(ACCESS, first['line'])
                for operation in ('SET', 'OUTPUT', 'INPUT'):
                    require(f'BRGP DENIED {operation} 1' in denied,
                            'Same-account foreign terminal access was not denied: ' + denied)
                report['cases']['foreign_access'] = 'TRMOP SET/OUTPUT/INPUT protection error 1'
                report['cases']['fallback'] = exchange(machine, ports, b, 102)
                require(report['cases']['fallback']['line'] != first['line'], 'Claim bypassed existing owner')
                second = hold(b)
                require(first['job'] != second['job'] and first['line'] != second['line'],
                        'Different jobs shared one native lease')
                started = time.monotonic()
                unavailable = c.start(AUTO, 103)
                require('BRGP NO_CHANNEL' in unavailable, 'Exhaustion did not return NO_CHANNEL: ' + unavailable)
                require(time.monotonic() - started < GUEST_TIMEOUT_BOUND, 'Pool exhaustion blocked')
                report['cases']['exhaustion'] = 'NO_CHANNEL without waiting or protocol traffic'
                release(a, first['line'])
                replacement = hold(c)
                require(replacement['line'] == first['line'], 'Explicit release was not reusable')
                release(c, replacement['line'])
                # Ctrl-C stops the program; KJOB is the authoritative job cleanup.
                b.connection.write(b'\x03\x03')
                b.receive(b'\n.')
                b.command('kjob', b'Logged-off')
                b.connection.close()
                b.connection = None
                first = hold(a)
                second = hold(c)
                require(first['line'] != second['line'], 'KJOB did not recover the second slot')
                report['cases']['job_death_recovery'] = [first, second]
                release(a, first['line'])
                release(c, second['line'])
                report['cases']['timeout'] = exchange(machine, ports, a, 104, silent=True)
                report['cases']['after_timeout'] = exchange(machine, ports, c, 105)
                barrier = threading.Barrier(2)
                with ThreadPoolExecutor(max_workers=2) as executor:
                    futures = [executor.submit(hold, guest, barrier) for guest in (a, c)]
                    claims = [future.result() for future in futures]
                require({row['line'] for row in claims} == set(BRIDGE_LINES), 'Concurrent claim collision')
                report['cases']['concurrent_claims'] = claims
                for guest, row in zip((a, c), claims):
                    release(guest, row['line'])
            installer.command('copy chaft.pm=mud.?pm')
            installer.command('r filcom', b'\n*')
            text = installer.command('tty:=chbef.pm,chaft.pm/b', b'\n*')
            require('No differences encountered' in text, 'Channel experiments changed persona bytes')
            installer.connection.write(b'\x1a')
            installer.receive(b'\n.')
            installer.at_monitor = True
        require(original == source_hashes(), 'Original source changed')
        report.update(complete=True, source_unchanged=True, persona_file_byte_identical=True)
        print('MUDGUEST channel checks complete:', output, flush=True)
    except BaseException as error:
        report['error'] = repr(error)
        raise
    finally:
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        if machine is not None:
            machine.stop()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path,
                        default=ROOT / 'runtime' / f'storage-channels-{time.time_ns()}')
    run(parser.parse_args().output.resolve())
