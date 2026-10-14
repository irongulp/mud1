"""Capture a private, coherently locked native persona image for one-way import."""
import argparse
from pathlib import Path
import re
import time

from tools.inspect_game import NativeInspector, InspectionError, sixbit
from tools.persona_snapshot import MigrationError, parse_native_dump, write_snapshot, MAX_SNAPSHOT_BYTES

ROOT = Path(__file__).resolve().parents[1]
CAPTURE_TIMEOUT = 600


class SnapshotInspector(NativeInspector):
    def receive(self, marker):
        deadline, data = time.monotonic() + CAPTURE_TIMEOUT, bytearray()
        while time.monotonic() < deadline:
            data.extend(self.connection.read_until(marker, 1))
            if len(data) > MAX_SNAPSHOT_BYTES: raise InspectionError('Native snapshot exceeded size bound')
            if data.endswith(marker): return data.decode('ascii', errors='strict')
        raise InspectionError('Native snapshot timed out')


def capture(native, *, persona_name='mud', device='dskb', ppn=(0o2011 << 18) | 0o2776, install=False):
    if (not re.fullmatch(r'[a-zA-Z0-9]{1,6}', persona_name)
            or not re.fullmatch(r'[a-zA-Z0-9]{1,6}', device)
            or type(ppn) is not int or not 0 <= ppn < (1 << 36)):
        raise MigrationError('Invalid native snapshot file selection')
    native.command('set tty width 255')
    if install:
        native.command('assign dsk: bcl:'); native.command('set tty no altmode')
        command = native.command
        def checked(text, *args):
            result = command(text, *args)
            if re.search(r'\([WE]\d+-\d+\)', result):
                raise InspectionError('Migration companion compilation failed')
            return result
        native.command = checked
        try: native.install_source('pmsnap', (ROOT / 'tools/fixtures/PMSNAP.BCL').read_text())
        finally: native.command = command
    native.command('run pmsnap', b'PMSNAP READY\r\n')
    # Never route this response through a terminal transcript or public inspector.
    output = native.command(f'{sixbit(device):012o} {sixbit(persona_name):012o} {ppn:012o}')
    return parse_native_dump(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, required=True, help='Explicit private loopback TOPS-10 terminal port')
    parser.add_argument('--persona-name', default='mud')
    parser.add_argument('--device', default='dskb')
    parser.add_argument('--ppn', default='2011,2776', help='Octal project,programmer number')
    parser.add_argument('--install', action='store_true', help='Compile the independent PMSNAP companion first')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 0 < args.port < 65536: parser.error('Invalid private port')
    if not re.fullmatch(r'[0-7]{1,6},[0-7]{1,6}', args.ppn): parser.error('PPN must be two octal halfwords')
    high, low = (int(part, 8) for part in args.ppn.split(','))
    try:
        with SnapshotInspector(args.port) as native:
            snapshot = capture(native, persona_name=args.persona_name, device=args.device,
                               ppn=(high << 18) | low, install=args.install)
        write_snapshot(args.output, snapshot)
        import json
        print(json.dumps(snapshot.report(), sort_keys=True))
    except (InspectionError, MigrationError, OSError, UnicodeError):
        parser.exit(1, 'Native capture failed; no partial snapshot or record transcript was published\n')


if __name__ == '__main__': main()
