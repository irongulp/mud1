"""Focused private native COPY/TYPE lab; production transfer/framing is unchanged.

Use a verified-stopped disposable image, never a live or public game. A shorter
observation deadline is diagnostic only, not a production timeout adjustment.
"""
import argparse
from contextlib import redirect_stdout
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import time

from server.runtime import Runtime
from tools.build_external_guest import compile_bcpl, read_back, rendered, transfer
from tools.capture_personas import CAPTURE_TIMEOUT, SnapshotInspector

TRACE_LIMIT = 1024 * 1024
OBSERVATION_TIMEOUT = 60


def private_file(path, mode):
    stream = path.open(mode)
    os.fchmod(stream.fileno(), 0o600)
    return stream


class TraceConnection:
    """Observe bounded private copies; never alter returned transport data."""
    def __init__(self, connection, directory, limit=TRACE_LIMIT):
        self.connection = connection
        self.limit = limit
        self.received_bytes = self.recorded_bytes = 0
        self.truncated = False
        self.started = time.monotonic()
        self.stage = 'setup'
        self.events = private_file(directory / 'events.jsonl', 'w')
        self.received = private_file(directory / 'received.bin', 'wb')
        self.observation = bytearray()

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def reset_observation(self, stage):
        self.stage = stage
        self.observation.clear()

    def read_until(self, marker, timeout):
        data = self.connection.read_until(marker, timeout)
        self.received_bytes += len(data)
        room = max(0, self.limit - self.recorded_bytes)
        self.received.write(data[:room])
        self.received.flush()
        self.recorded_bytes += min(room, len(data))
        self.truncated |= len(data) > room
        remaining = max(0, self.limit - len(self.observation))
        self.observation.extend(data[:remaining])
        self.events.write(json.dumps({'elapsed': time.monotonic() - self.started,
                                     'stage': self.stage, 'size': len(data),
                                     'marker_size': len(marker),
                                     'ends_with_marker': data.endswith(marker),
                                     'sha256': hashlib.sha256(data).hexdigest()}) + '\n')
        self.events.flush()
        return data

    def close_trace(self):
        self.events.close()
        self.received.close()


def end_marker(expected):
    lines = [line.expandtabs(8).rstrip() for line in expected.splitlines()]
    while lines and not lines[-1]:
        lines.pop()
    if not lines:
        raise ValueError('Empty expected source')
    source = '\n'.join(lines)
    for count in range(1, len(lines) + 1):
        suffix = '\n'.join(lines[-count:])
        if source.count(suffix) == 1:
            return (suffix.replace('\n', '\r\n') + '\r\n').encode('ascii')
    raise ValueError('No unique source suffix')


def evidence_summary(received, expected, marker):
    text = received.decode('ascii', errors='replace').replace('\r', '')
    body = text.split('\n', 1)[1] if text.startswith('type ') else text.lstrip('\n')
    if '\n.' in body:
        body = body.rsplit('\n.', 1)[0]
    return {'received_bytes': len(received), 'expected_marker_seen': marker in received,
            'monitor_boundary_seen': b'\n.' in received,
            'normalized_source_matches': rendered(body) == rendered(expected),
            'crlf_count': received.count(b'\r\n'), 'tab_count': received.count(b'\t'),
            'nul_count': received.count(b'\0')}


class LabInspector(SnapshotInspector):
    def __init__(self, port, timeout):
        super().__init__(port)
        self.observation_timeout = timeout

    def command_timeout(self):
        return self.observation_timeout

    def send_control(self, text):
        if text.startswith('type ') and isinstance(self.connection, TraceConnection):
            self.connection.reset_observation('type-readback')
        return super().send_control(text)


def run(output, checkpoint, source, executable, *, rounds=1, timeout=OBSERVATION_TIMEOUT,
        read_existing=False, compiler_state=False):
    marker_path = checkpoint / 'shutdown.json'
    if json.loads(marker_path.read_text()).get('clean') is not True:
        raise RuntimeError('Checkpoint must have a verified clean shutdown marker')
    output.mkdir(mode=0o700)
    state = output / 'machine'
    state.mkdir(mode=0o700)
    (state / 'game').mkdir(mode=0o700)
    for name in ('guest.dsk', 't10boot.tap'):
        shutil.copyfile(checkpoint / 'game' / name, state / 'game' / name)
        (state / 'game' / name).chmod(0o600)
    expected = source.read_text()
    if not expected.isascii():
        raise ValueError('Expected source must be ASCII')
    suffix = end_marker(expected)
    report = {'complete': False, 'rounds': [], 'observation_timeout': timeout,
              'production_snapshot_timeout': CAPTURE_TIMEOUT, 'read_existing': read_existing,
              'compiler_state': compiler_state,
              'source_sha256': hashlib.sha256(expected.encode('ascii')).hexdigest(),
              'checkpoint_shutdown_sha256': hashlib.sha256(marker_path.read_bytes()).hexdigest()}
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    runtime = Runtime(state, executable, port=port)
    trace = None
    failure = None
    with private_file(output / 'console.log', 'w') as console, redirect_stdout(console):
        try:
            runtime.boot()
            with LabInspector(port, timeout) as native:
                trace = TraceConnection(native.connection, output)
                native.connection = trace
                native.command('assign dsk: bcl:')
                native.command('set tty no altmode')
                # Existing-failed-file mode is read-only; transfers use a separate
                # six-character fixture name, never the active MUD source/exe.
                filename = 'mud5.bcl' if read_existing else 'rdtest.bcl'
                for index in range(rounds):
                    if compiler_state:
                        compile_bcpl(native, 'mud7')
                    trace.reset_observation('readback' if read_existing else 'transfer-readback')
                    started = time.monotonic()
                    entry = {'round': index + 1, 'filename': filename}
                    try:
                        if read_existing:
                            actual = read_back(native, filename, expected)
                            if rendered(actual) != rendered(expected):
                                raise RuntimeError('Existing source differs')
                        else:
                            transfer(native, filename, expected)
                        entry['success'] = True
                    except Exception as error:
                        entry.update(success=False, error=type(error).__name__)
                        # Capture while the failed TTY/program is still untouched.
                        with private_file(output / 'failed-response.bin', 'wb') as failed:
                            failed.write(trace.observation)
                        try:
                            status = runtime.command('systat', timeout=5)
                            with private_file(output / 'failed-systat.txt', 'w') as snapshot:
                                snapshot.write(status)
                            entry['systat_captured'] = True
                        except Exception as diagnostic:
                            entry['systat_error'] = type(diagnostic).__name__
                        entry.update(evidence_summary(bytes(trace.observation), expected, suffix))
                        entry['elapsed'] = time.monotonic() - started
                        report['rounds'].append(entry)
                        raise
                    entry['elapsed'] = time.monotonic() - started
                    report['rounds'].append(entry)
            report['complete'] = True
        except BaseException as error:
            failure = error
            raise
        finally:
            try:
                report['clean_shutdown'] = runtime.stop()
            except Exception as cleanup:
                report['cleanup_error'] = type(cleanup).__name__
                report['clean_shutdown'] = False
                if failure is None:
                    raise
            finally:
                report['complete'] = report['complete'] and report.get('clean_shutdown', False)
                if trace is not None:
                    trace.close_trace()
                    report['trace_truncated'] = trace.truncated
                with private_file(output / 'report.json', 'w') as summary:
                    json.dump(report, summary, indent=2)
                    summary.write('\n')
    print(json.dumps(report, indent=2))
    if not report['complete']:
        raise RuntimeError('Source observation finished without confirmed clean shutdown')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--checkpoint', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--simh', type=Path, required=True)
    parser.add_argument('--rounds', type=int, default=1)
    parser.add_argument('--observation-timeout', type=float, default=OBSERVATION_TIMEOUT)
    parser.add_argument('--read-existing', action='store_true')
    parser.add_argument('--compiler-state', action='store_true')
    args = parser.parse_args()
    if args.rounds < 1 or not 0 < args.observation_timeout <= CAPTURE_TIMEOUT:
        parser.error('Use positive rounds and an observation timeout no greater than the production bound')
    run(args.output.resolve(), args.checkpoint.resolve(), args.source.resolve(), args.simh.resolve(),
        rounds=args.rounds, timeout=args.observation_timeout,
        read_existing=args.read_existing, compiler_state=args.compiler_state)
