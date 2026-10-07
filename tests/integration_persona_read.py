"""Native H1/R1 synthetic record acceptance on a disposable TOPS-10 runtime."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import json
from pathlib import Path
import re
import socket
import threading
import time

from tools.audit_archwizards import MAX_BOOT_ATTEMPTS
from tools.inspect_game import NativeInspector
from tools.persona_protocol import WORD_MASK, pack_name
from tools.persona_session import serve_reads, new_token
from tests.integration_provisioning import source_hashes, require
from tests.integration_storage_bridge import ROOT, BRIDGE_LINES, HOST_TIMEOUT, private_emulator
from tests.integration_storage_channels import GuestMonitor, GUEST_PPN

PROGRAM = 'dskb:prread[2011,2776]'
NATIVE_BOUND = 12
RECONNECT_BOUND = 3
ALLOCATION_SETTLE = 1


def connect_slave(machine, line, port):
    # SIMH may not have reaped the previous socket at the instant it accepts a
    # replacement. Retry only its explicit busy/unavailable rejection, bounded.
    for setting in ('slave', 'echo'):
        text = machine.command(f'set tty tty{line:o}: {setting}')
        require('?' not in text, 'Cannot configure secondary terminal')
    deadline = time.monotonic() + RECONNECT_BOUND
    while True:
        remaining = deadline - time.monotonic()
        require(remaining > 0, 'Slave reconnect deadline expired')
        channel = socket.create_connection(('127.0.0.1', port), remaining)
        try:
            channel.settimeout(remaining)
            channel.sendall(b'\r')
            response = b''
            while not response.endswith(b'\r\n'):
                remaining = deadline - time.monotonic()
                require(remaining > 0, 'Slave bootstrap deadline expired')
                channel.settimeout(remaining)
                block = channel.recv(1)
                require(block and len(response) < 79, 'Invalid slave bootstrap')
                response += block
            if response in (b'Line connection busy\r\n', b'Line connection not available\r\n'):
                channel.close()
                require(time.monotonic() < deadline, 'Slave reconnect deadline expired')
                time.sleep(0.05)
                continue
            require(response == b'\r\n', 'Unexpected slave bootstrap: ' + repr(response))
            text = machine.command(f'set tty tty{line:o}: no echo')
            require('?' not in text, 'Cannot suppress slave echo')
            return channel
        except BaseException:
            channel.close()
            raise


def fixture(name):
    return ((0o2653 << 18) | 7, name[0] | 1, name[1] | 1, 1 << 35, WORD_MASK,
            0o123456701234, (1 << 35) - 1, 0o400000000123, 0, 1 << 35, WORD_MASK)


class Hub:
    """Persistent socket per pool member; mutations here are fault injection only."""
    def __init__(self, machine, ports):
        self.machine, self.ports = machine, ports
        self.mode = 'found'
        self.offers, self.events, self.errors = [], [], []
        self.held = threading.Event()
        self.pending_word = None
        self.stopping = False

    def __enter__(self):
        self.stack = ExitStack()
        try:
            self.channels = {line: self.stack.enter_context(connect_slave(self.machine, line, self.ports[line]))
                             for line in BRIDGE_LINES}
            self.executor = ThreadPoolExecutor(max_workers=len(self.channels))
            self.futures = [self.executor.submit(self.worker, line, channel)
                            for line, channel in self.channels.items()]
            return self
        except BaseException:
            self.stack.close()
            raise

    def fetch(self, name):
        if self.mode == 'not_found':
            return None
        if self.mode == 'unavailable':
            raise OSError('synthetic unavailable fixture')
        if self.mode == 'invalid_record':
            return (0,)
        return fixture(name)

    def worker(self, line, channel):
        hub = self
        class FaultSocket:
            checksum_delta = 0
            def settimeout(self, timeout):
                channel.settimeout(timeout)
            def recv(self, size):
                return channel.recv(size)
            def sendall(self, data):
                mode = hub.mode
                if data.startswith(b'H1 OFFER '):
                    self.checksum_delta = 0
                    previous = hub.offers[-1] if hub.offers else None
                    parts = data.split()
                    current = {'challenge': int(parts[2], 8), 'epoch': int(parts[3], 8), 'line': line}
                    if mode == 'late_handover' and previous:
                        for tag in ('OFFER', 'READY'):
                            channel.sendall(f'H1 {tag} {previous["challenge"]:024o} {previous["epoch"]:024o}\r'.encode())
                            time.sleep(0.05)
                        if hub.pending_word:
                            channel.sendall(hub.pending_word)
                            time.sleep(0.05)
                    hub.offers.append(current)
                if mode == 'restart' and data.startswith(b'H1 READY '):
                    channel.shutdown(socket.SHUT_RDWR)
                    return
                if b' FOUND ' in data:
                    if mode == 'silence':
                        return
                    if mode == 'partial':
                        channel.sendall(data[:10])
                        return
                    if mode == 'disconnect':
                        channel.shutdown(socket.SHUT_RDWR)
                        return
                if data.startswith(b'R1 WORD '):
                    parts = data.split()
                    index = int(parts[4], 8)
                    if mode == 'hold' and index == 2:
                        hub.pending_word = data
                        hub.held.set()
                        return
                    if mode == 'wrong_epoch' and index == 2:
                        parts[2] = f'{int(parts[2], 8) ^ 1:024o}'.encode()
                    if mode == 'wrong_sequence' and index == 2:
                        parts[3] = b'000000000002'
                    if mode == 'wrong_index' and index == 2:
                        parts[4] = b'01'
                    if mode == 'malformed' and index == 2:
                        parts[5] = b'000000000008'
                    if mode == 'wrong_name' and index in (2, 3):
                        replacement = pack_name('other')[index - 2] | 1
                        self.checksum_delta ^= int(parts[5], 8) ^ replacement
                        parts[5] = f'{replacement:012o}'.encode()
                    data = b' '.join(parts) + b'\r'
                if mode == 'checksum' and data.startswith(b'R1 END '):
                    parts = data.split()
                    parts[-1] = f'{int(parts[-1], 8) ^ 1:012o}'.encode()
                    data = b' '.join(parts) + b'\r'
                if mode == 'wrong_name' and data.startswith(b'R1 END '):
                    parts = data.split()
                    parts[-1] = f'{int(parts[-1], 8) ^ self.checksum_delta:012o}'.encode()
                    data = b' '.join(parts) + b'\r'
                if mode == 'fragmented' and data.startswith(b'R1 '):
                    for byte in data:
                        channel.sendall(bytes([byte]))
                        time.sleep(0.001)
                else:
                    channel.sendall(data)
        try:
            serve_reads(FaultSocket(), self.fetch,
                        on_event=lambda state: self.events.append({'line': line, 'state': state}))
        except (OSError, ValueError, TimeoutError) as error:
            if not self.stopping:
                self.errors.append({'line': line, 'type': type(error).__name__})

    def __exit__(self, *exc):
        self.stopping = True
        for channel in self.channels.values():
            try:
                channel.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self.executor.shutdown(wait=True)
        self.stack.close()


def begin(guest, challenge, name):
    guest.command('run ' + PROGRAM, b'R1RD READY\r\n')
    words = pack_name(name)
    return f'{challenge:024o} {words[0]:012o} {words[1]:012o}'


def probe(guest, hub, name='fred', expected='FOUND', barrier=None):
    started = time.monotonic()
    attempts = 0
    while True:
        challenge = new_token()
        command = begin(guest, challenge, name)
        if barrier and not attempts:
            barrier.wait(HOST_TIMEOUT)
        attempts += 1
        text = guest.command(command)
        if 'R1RD NO_CHANNEL UNPUBLISHED' not in text:
            break
        # Reconnecting raw sockets may still be undergoing monitor cleanup.
        # Retry only this pre-protocol outcome; never retry a failed read here.
        require('R1RD LEASE' not in text, 'NO_CHANNEL after a successful claim')
        if time.monotonic() - started >= ALLOCATION_SETTLE:
            status = guest.command('systat')
            raise AssertionError('Pool remained unavailable after reconnect: ' + status)
        time.sleep(0.05)
    elapsed = time.monotonic() - started
    owner = re.search(r'R1RD LEASE (\d+) ([0-7]+) (\d+)', text)
    require(owner is not None and int(owner[2], 8) == GUEST_PPN, 'Reader did not run as MUDGUEST: ' + text)
    require(f'R1RD RELEASED {owner[3]}' in text, 'Reader retained its channel: ' + text)
    require(elapsed < NATIVE_BOUND, 'Native response exceeded wall-clock bound')
    require('R1RD PARTIAL_COMMIT' not in text, 'A failed read modified committed storage')
    if expected == 'FOUND':
        require('R1RD FOUND 11 VERIFIED' in text, 'Native record did not match fixture: ' + text)
    else:
        require(f'R1RD {expected} UNPUBLISHED' in text, 'Unexpected native outcome: ' + text)
        require('R1RD FOUND' not in text, 'Failed response was published')
    offer = next((row for row in hub.offers if row['challenge'] == challenge), None)
    return {'outcome': expected, 'seconds': round(elapsed, 3), 'job': int(owner[1]),
            'line': int(owner[3]), 'epoch': offer['epoch'] if offer else None,
            'challenge': challenge, 'allocation_attempts': attempts, 'transcript': text}


def verify_persona_file(installer):
    installer.command('copy r1aft.pm=mud.?pm')
    installer.command('r filcom', b'\n*')
    comparison = installer.command('tty:=r1bef.pm,r1aft.pm/b', b'\n*')
    require('No differences encountered' in comparison, 'Persona file changed')
    installer.connection.write(b'\x1a')
    installer.receive(b'\n.')
    installer.at_monitor = True


def run(output):
    output.mkdir(mode=0o700)
    original = source_hashes()
    report = {'complete': False, 'cases': {}}
    machine = None
    try:
        with ExitStack() as stack:
            sockets = [stack.enter_context(socket.socket()) for _ in BRIDGE_LINES]
            ports = {}
            for line, sock in zip(BRIDGE_LINES, sockets):
                sock.bind(('127.0.0.1', 0))
                ports[line] = sock.getsockname()[1]
        for attempt in range(MAX_BOOT_ATTEMPTS):
            print('R1 private boot:', attempt + 1, flush=True)
            machine = private_emulator(output / f'machine-{attempt+1}', ports)
            try:
                machine.boot()
                machine.command('daytime')
                for line in BRIDGE_LINES:
                    text = machine.command(f'set tty tty{line:o}: slave')
                    require('?' not in text, 'Cannot configure SLAVE terminal')
                break
            except Exception:
                machine.stop()
                machine = None
                if attempt + 1 == MAX_BOOT_ATTEMPTS:
                    raise
        class Installer(NativeInspector):
            def receive(self, marker):
                text = super().receive(marker)
                with (output / 'installation.txt').open('a') as stream:
                    stream.write(text)
                return text
        with Installer(machine.port) as installer:
            installer.command('assign dsk: bcl:')
            installer.command('set tty no altmode')
            installer.install_source('prread', (ROOT / 'tools/fixtures/PRREAD.BCL').read_text())
            installer.command('protect prread.exe<055>')
            installer.command('copy r1bef.pm=mud.?pm')
            with GuestMonitor(machine.port, output / 'a.txt') as a, GuestMonitor(machine.port, output / 'b.txt') as b:
                with Hub(machine, ports) as hub:
                    for name in ('fred', 'abcdefghi', 'test1'):
                        print('Native R1 record:', name, flush=True)
                        report['cases'][name] = probe(a, hub, name)
                    hub.mode = 'late_handover'
                    report['cases']['handover'] = probe(b, hub)
                    require(report['cases']['handover']['epoch'] != report['cases']['fred']['epoch'], 'Epoch reused')
                    for mode in ('not_found', 'unavailable', 'invalid_record', 'fragmented'):
                        hub.mode = mode
                        report['cases'][mode] = probe(a, hub, expected='FOUND' if mode == 'fragmented' else mode.upper())
                    # Abandon a read after one word, without closing the host
                    # sockets. The replacement must retire pending old data.
                    hub.mode = 'hold'
                    command = begin(a, new_token(), 'fred')
                    a.send(command)
                    require(hub.held.wait(HOST_TIMEOUT), 'Old owner did not reach the partial-record barrier')
                    a.connection.write(b'\x03\x03')
                    interrupted = a.receive(b'\n.')
                    require('R1RD FOUND' not in interrupted, 'Partial read was published before interruption')
                    old_line = int(re.search(r'R1RD LEASE \d+ [0-7]+ (\d+)', interrupted)[1])
                    a.command('kjob', b'Logged-off')
                    a.connection.close()
                    a.connection = None
                    hub.mode = 'late_handover'
                    handover = probe(b, hub)
                    require(handover['line'] == old_line, 'Handover did not reuse the old channel')
                    report['cases']['abandoned_handover'] = handover
                    a.__enter__()
                    require(not hub.errors, 'Host rejected a healthy exchange: ' + repr(hub.errors))
                for mode, outcome in (('wrong_epoch', 'PROTOCOL'), ('wrong_sequence', 'PROTOCOL'),
                                      ('wrong_index', 'PROTOCOL'), ('malformed', 'PROTOCOL'),
                                      ('wrong_name', 'PROTOCOL'),
                                      ('checksum', 'PROTOCOL'), ('partial', 'TIMEOUT'),
                                      ('silence', 'TIMEOUT'), ('disconnect', 'TIMEOUT'), ('restart', 'TIMEOUT')):
                    print('Native R1 fault:', mode, flush=True)
                    with Hub(machine, ports) as hub:
                        hub.mode = mode
                        report['cases'][mode] = probe(a, hub, expected=outcome)
                with Hub(machine, ports) as hub:
                    previous = report['cases']['restart']
                    hub.offers.append({key: previous[key] for key in ('challenge', 'epoch', 'line')})
                    hub.mode = 'late_handover'
                    report['cases']['after_restart'] = probe(b, hub)
                    require(report['cases']['after_restart']['epoch'] != previous['epoch'], 'Epoch reused after host restart')
                    hub.mode = 'found'
                    barrier = threading.Barrier(2)
                    with ThreadPoolExecutor(max_workers=2) as executor:
                        futures = [executor.submit(probe, guest, hub, 'fred', 'FOUND', barrier) for guest in (a, b)]
                        pair = [future.result() for future in futures]
                    require(len({row['line'] for row in pair}) == 2, 'Concurrent records shared a channel')
                    require(len({row['epoch'] for row in pair}) == 2, 'Concurrent records shared an epoch')
                    report['cases']['parallel'] = pair
                    prior_boot_offer = dict(hub.offers[-1])
                    require(not hub.errors, 'Host failed after reconnect')
            verify_persona_file(installer)
        # Cleanly restart this very same disposable disk, then replay old boot
        # handshake frames against a fresh controller challenge.
        machine.command('r opr', 'OPR>')
        machine.child.send('set ksys now\r')
        machine.child.expect_exact('KSYS processing completed', timeout=120)
        directory = machine.directory
        machine.stop()
        machine = None
        report['clean_restart'] = True
        for attempt in range(MAX_BOOT_ATTEMPTS):
            print('R1 same-disk reboot:', attempt + 1, flush=True)
            machine = private_emulator(directory, ports, reuse=True)
            try:
                machine.boot()
                machine.command('daytime')
                break
            except Exception:
                machine.stop()
                machine = None
                if attempt + 1 == MAX_BOOT_ATTEMPTS:
                    raise
        with GuestMonitor(machine.port, output / 'reboot.txt') as guest, Hub(machine, ports) as hub:
            hub.offers.append(prior_boot_offer)
            hub.mode = 'late_handover'
            rebooted = probe(guest, hub)
            require(rebooted['epoch'] != prior_boot_offer['epoch'], 'Epoch survived emulator restart')
            require(rebooted['challenge'] != prior_boot_offer['challenge'], 'Challenge reused after restart')
            report['cases']['emulator_restart'] = rebooted
        with Installer(machine.port) as installer:
            verify_persona_file(installer)
        report['persona_file_verified_after_restart'] = True
        require(original == source_hashes(), 'Original source changed')
        report.update(complete=True, persona_file_byte_identical=True, source_unchanged=True)
        print('Native R1 checks complete:', output, flush=True)
    except BaseException as error:
        report['error'] = repr(error)
        raise
    finally:
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        if machine is not None:
            machine.stop()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'runtime' / f'persona-read-{time.time_ns()}')
    run(parser.parse_args().output.resolve())
