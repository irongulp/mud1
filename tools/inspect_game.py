"""Read-only operator queries, independent of the MUD executable (Python 3.9–3.12)."""
import argparse
from collections import deque
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = 1
PORT = 2020
TIMEOUT = 90
MAX_RESPONSE = 4 * 1024 * 1024
MAX_PERSONAS = 2048
SOURCE_LINE_DELAY = 0.05
TTY_SETTLE_SECONDS = 0.25
DEFAULT_LOG_LINES = 100
MAX_CONTEXT_ENTRIES = 100
TEXT_EXTENSIONS = {'TXT', 'LOG', 'WIZ', 'BCL', 'GET', 'MAC', 'DBA', 'INI', 'MIC', 'CMD'}
SERVICES = {'runtime': 'mud86-runtime.service', 'gateway': 'mud86-gateway.service'}
AREAS = {'game': (0o2011 << 18) | 0o2776, 'logs': 0o2600002776}
ACTIONS = {'personas', 'persona', 'files', 'file', 'logs', 'errors', 'inspection-install'}


class InspectionError(RuntimeError):
    """An operator-facing error without raw maintenance transcripts."""


def parse_personas(text):
    lines = text.replace('\r', '').splitlines()
    try:
        start = lines.index('MVPER 1')
        lines = lines[start:]
        if lines[1] == 'BUSY':
            raise InspectionError('Persona file is busy; try again shortly')
        total = int(re.fullmatch(r'TOTAL (\d+)', lines[1])[1])
        if not 0 <= total <= MAX_PERSONAS or lines[total + 2] != f'END {total}':
            raise ValueError()
        rows, deleted, names = [], 0, set()
        fields = ('games', 'score', 'strength', 'dexterity', 'stamina', 'stamina_max',
                  'last_play_guest_day', 'last_play_guest_fraction', 'state_flags',
                  'password_set', 'sex_bit')
        for line in lines[2:total + 2]:
            if line == 'DELETED':
                deleted += 1
                continue
            match = re.fullmatch(r'PERSON ([A-Za-z]{1,9})' + r' (-?\d+)' * len(fields), line)
            if not match or match[1].lower() in names:
                raise ValueError()
            names.add(match[1].lower())
            row = dict(zip(fields, map(int, match.groups()[1:])))
            if row['password_set'] not in (0, 1) or row['sex_bit'] not in (0, 1):
                raise ValueError()
            if not 0 <= row['games'] < 1 << 18 or any(
                    not 0 <= row[field] < 1 << 9
                    for field in ('strength', 'dexterity', 'stamina', 'stamina_max')):
                raise ValueError()
            row.update(name=match[1], password_set=bool(row['password_set']))
            rows.append(row)
        return {'version': SCHEMA_VERSION, 'state': 'saved', 'records': total,
                'deleted': deleted, 'personas': rows}
    except (ValueError, IndexError, TypeError):
        raise InspectionError('Missing, incompatible or incomplete persona snapshot') from None


def text_filename(value):
    name = value.upper()
    if not re.fullmatch(r'[A-Z0-9]{1,6}\.[A-Z0-9]{1,3}', name) or name.split('.')[1] not in TEXT_EXTENSIONS:
        raise InspectionError('Use a single 6.3 text filename in the game directory (for example MUD.WIZ)')
    return name


def sixbit(value):
    word = 0
    for char in value.upper().ljust(6):
        word = (word << 6) | (ord(char) - 32)
    return word


def parse_text(text):
    lines = text.replace('\r', '').splitlines()
    if 'MISSING' in lines:
        raise InspectionError('Text file is missing or inaccessible')
    if 'LIMIT' in lines:
        raise InspectionError('Text file exceeds the native scan limit (4 MiB)')
    try:
        start = lines.index('MVTXT 1')
        end = lines.index('END', start)
        result = []
        for line in lines[start + 1:end]:
            if line == 'TRUNCATED':
                continue
            if line.startswith('CHAR '):
                number = int(line[5:])
                if not 0 <= number < 128:
                    raise ValueError()
                result.append(chr(number))
            else:
                match = re.fullmatch(r'DATA ([0-7]{1,12}) ([1-5])', line)
                if not match:
                    raise ValueError()
                word, count = int(match[1], 8), int(match[2])
                result.extend(chr((word >> (7 * (4 - i))) & 127) for i in range(count))
        return ''.join(result)
    except (ValueError, IndexError):
        raise InspectionError('Text file missing, unreadable, over scan limit, or incomplete response') from None


class NativeInspector:
    """Short-lived maintenance job; queries never install code or enter the game."""
    def __init__(self, port=PORT):
        self.port = port
        self.connection = None
        self.at_monitor = False

    def receive(self, marker):
        deadline = time.monotonic() + TIMEOUT
        data = bytearray()
        while time.monotonic() < deadline:
            block = self.connection.read_until(marker, min(1, max(0, deadline - time.monotonic())))
            data.extend(block)
            if len(data) > MAX_RESPONSE:
                raise InspectionError('Maintenance response exceeded its size limit')
            if data.endswith(marker):
                return data.decode('ascii', errors='replace')
        raise InspectionError('Maintenance query timed out; check runtime logs')

    def send(self, text):
        self.connection.write(text.encode('ascii') + b'\r')

    def command(self, text, marker=b'\n.'):
        self.at_monitor = False
        self.send(text)
        output = self.receive(marker)
        self.at_monitor = marker == b'\n.'
        if re.search(r'(?m)^\?|undefined global|% .*Error', output):
            raise InspectionError('Native query failed; check the file or run inspection-install after updating')
        return output

    def __enter__(self):
        import telnetlib
        try:
            self.connection = telnetlib.Telnet('127.0.0.1', self.port, TIMEOUT)
            self.receive(b'device, line ')
            self.receive(b'\n')
            time.sleep(TTY_SETTLE_SECONDS)
            self.send('')
            self.receive(b'.')
            self.command('set tty width 255')
            self.command('login richard')
            return self
        except BaseException:
            self.__exit__(*sys.exc_info())
            raise

    def __exit__(self, kind, value, traceback):
        if self.connection is None:
            return
        try:
            if not self.at_monitor:
                self.connection.write(b'\x03\x03')
                self.receive(b'\n.')
            self.send('kjob')
            self.receive(b'Logged-off')
        except Exception:
            if kind is None:
                raise InspectionError('Maintenance logout failed; inspect the guest job') from None
        finally:
            self.connection.close()
            self.connection = None

    def personas(self):
        return parse_personas(self.command('run mvper'))

    def files(self, area='game'):
        ppn = AREAS[area]
        directory = f'DSKB:[{ppn >> 18:o},{ppn & 0o777777:o}]'
        output = self.command(f'directory dskb:*.*{directory[5:]}')
        files = []
        for name, extension, blocks, protection, date in re.findall(
                r'(?m)^([A-Z0-9$%_-]{1,6})\s+([.A-Z0-9]{1,3})\s+(\d+)\s+<([0-7]{3})>\s+(\d+-[A-Za-z]+-\d+)', output):
            files.append({'name': name + '.' + extension, 'blocks': int(blocks),
                          'protection': protection, 'modified_guest_date': date})
        return {'version': SCHEMA_VERSION, 'directory': directory,
                'files': files,
                'listing': output.replace('\r', '').split('\n', 1)[-1].removesuffix('\n.')}

    def text(self, name, area='game'):
        name = text_filename(name)
        self.command('run mvtxt', b'MVTXT READY\r\n')
        base, extension = name.split('.')
        output = self.command(f'{sixbit(base):012o} {sixbit(extension):012o} {AREAS[area]:012o}')
        try:
            text = parse_text(output)
        except InspectionError as error:
            ppn = AREAS[area]
            raise InspectionError(f'DSKB:{name}[{ppn >> 18:o},{ppn & 0o777777:o}]: {error}') from None
        return {'version': SCHEMA_VERSION, 'file': name, 'area': area,
                'truncated': '\nTRUNCATED\r\n' in output, 'text': text}

    def install(self):
        self.command('assign dsk: bcl:')
        self.command('set tty no altmode')
        for program in ('mvper', 'mvtxt'):
            self.install_source(program, (ROOT / 'tools/fixtures' / (program.upper() + '.BCL')).read_text())
        self.personas()
        self.text('MVTXT.BCL')

    def install_source(self, program, source):
        """Installation-only transfer; never called by inspection queries."""
        if not re.fullmatch(r'[a-z]{1,6}', program):
            raise ValueError('Invalid companion name')
        self.at_monitor = False
        self.send(f'copy {program}.bcl=tty:')
        self.receive(f'copy {program}.bcl=tty:\r\n'.encode())
        for line in source.splitlines():
            self.send(line)
            self.receive(b'\n')
            time.sleep(SOURCE_LINE_DELAY)
        self.connection.write(b'\x1a')
        self.receive(b'\n.')
        self.command('r bcpl', b'\n*')
        self.command(f'{program}/o', b'\n*')
        self.connection.write(b'\x1a')
        self.receive(b'\n.')
        self.command('r link', b'\n*')
        self.command(f'{program}/g')
        self.command(f'save {program}')


def journal_command(source='all', since=None, lines=None, follow=False):
    if source not in {*SERVICES, 'all'}:
        raise InspectionError('Unknown journal source')
    command = ['journalctl', '--no-pager', '--output=json', '--quiet']
    for unit in SERVICES.values() if source == 'all' else (SERVICES[source],):
        command.extend(['--unit', unit])
    if since:
        command.extend(['--since', since])
    if lines is not None:
        command.extend(['--lines', str(lines)])
    if follow:
        command.append('--follow')
        if since and lines is None:
            command.append('--no-tail')
    return command


def journal_entries(source='all', since=None, lines=None, follow=False):
    try:
        # Inherit stderr: unavailable journal sources must be visible to the operator.
        process = subprocess.Popen(journal_command(source, since, lines, follow),
                                   stdout=subprocess.PIPE, text=True)
    except OSError as error:
        raise InspectionError('Cannot open system journal: ' + str(error)) from None
    try:
        for line in process.stdout:
            try:
                entry = json.loads(line)
                if not isinstance(entry, dict):
                    raise ValueError()
            except ValueError:
                raise InspectionError('Malformed journal output; scan is incomplete') from None
            yield entry
        if process.wait():
            raise InspectionError('Journal query failed; scan is incomplete')
    finally:
        process.stdout.close()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


# Specific host signatures precede journal priorities and conservative native review.
RULES = (
    ('native-memory-fault', 'error', r'(?m)^\?Illegal memory reference at user PC [0-7]+',
     'Inspect the surrounding guest console output to identify the failing program.'),
    ('emulator-exit', 'error', r'Emulator exited unexpectedly',
     'Inspect runtime context and service status before restarting.'),
    ('unclean-shutdown', 'error', r'Guest shutdown did not complete',
     'Inspect the next boot for disk recovery; do not treat this as a clean backup point.'),
    ('boot-retry', 'warning', r'Retrying guest boot \(\d+/\d+\)',
     'Inspect preceding runtime output and whether a later boot became ready.'),
    ('logout-incomplete', 'warning', r'Terminal logout did not complete; check the guest job',
     'Inspect guest jobs for a terminal session left behind.'),
    ('connection-ended', 'warning', r'Terminal connection ended:',
     'Check runtime availability and recurrence; an isolated disconnect may be transient.'),
    ('traceback', 'error', r'Traceback \(most recent call last\):',
     'Read the full traceback and adjacent journal entries.'),
    ('service-failure', 'error', r'(?:Failed with result |Main process exited,|Failed to start .*MUD)',
     'Inspect service status and the preceding runtime/gateway messages.'),
)


def message_text(entry):
    message = entry.get('MESSAGE', '')
    if isinstance(message, list):
        try:
            return bytes(message).decode('utf-8', errors='replace')
        except (ValueError, TypeError):
            return '[unreadable journal message]'
    return str(message)


def timestamp(entry):
    try:
        return datetime.fromtimestamp(int(entry['__REALTIME_TIMESTAMP']) / 1000000,
                                      timezone.utc).isoformat()
    except (KeyError, ValueError, TypeError, OverflowError, OSError):
        return None


def entry_source(entry):
    # Messages emitted by PID 1 identify the affected service in UNIT, while
    # _SYSTEMD_UNIT describes the manager itself (usually init.scope).
    return entry.get('UNIT') or entry.get('_SYSTEMD_UNIT') or 'unknown'


def context_entry(entry):
    return {'source': entry_source(entry), 'timestamp': timestamp(entry), 'message': message_text(entry)}


def classify(entry):
    message = message_text(entry)
    for code, severity, pattern, suggestion in RULES:
        if re.search(pattern, message):
            return code, severity, suggestion
    try:
        priority = int(entry.get('PRIORITY', 6))
    except (ValueError, TypeError):
        priority = 6
    if 0 <= priority <= 4:
        return 'journal-priority', 'error' if priority <= 3 else 'warning', 'Inspect adjacent journal entries.'
    if re.search(r'(?m)^(?:\?[A-Z]|%[A-Z]|(?:ERROR|CRITICAL|WARNING):)', message):
        return 'unrecognised-diagnostic', 'review', 'Review this diagnostic in context; its severity is not established.'
    return None


def diagnose(entries, context=0):
    groups, scanned, sources = {}, 0, set()
    previous = deque(maxlen=context)
    for entry in entries:
        scanned += 1
        source = entry_source(entry)
        sources.add(source)
        classified = classify(entry)
        if classified:
            code, severity, suggestion = classified
            message = message_text(entry)
            # Group known recurring conditions; retain distinct unknown messages.
            key = (source, code, message if code in ('journal-priority', 'unrecognised-diagnostic', 'traceback') else '')
            if key not in groups:
                groups[key] = dict(source=source, code=code, severity=severity, count=0,
                                   first_seen=timestamp(entry), last_seen=None, message=message,
                                   suggestion=suggestion, context=list(previous))
            groups[key]['count'] += 1
            groups[key]['last_seen'] = timestamp(entry)
        previous.append(context_entry(entry))
    return {'version': SCHEMA_VERSION, 'entries_scanned': scanned,
            'sources_observed': sorted(sources), 'findings': list(groups.values())}


def safe_terminal(text):
    """Display log/file content without executing embedded terminal controls."""
    return ''.join(char if char in '\n\t' or char.isprintable() else f'\\x{ord(char):02x}'
                   for char in text.replace('\r\n', '\n'))


def print_findings(report):
    for finding in report['findings']:
        print(f"{finding['severity'].upper()} {finding['source']} {finding['code']} x{finding['count']}")
        print(f"  {finding['first_seen']} → {finding['last_seen']}")
        for line in finding['context']:
            print('  context: ' + safe_terminal(line['message']))
        print('  ' + safe_terminal(finding['message']))
        print('  ' + finding['suggestion'])


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest='action', required=True)
    for name in sorted(ACTIONS):
        command = commands.add_parser(name)
        command.add_argument('--json', action='store_true', help='Versioned JSON (JSON lines when following)')
        if name in ('personas', 'persona', 'files', 'file', 'inspection-install'):
            command.add_argument('--port', type=int, default=PORT, help='Loopback guest port')
        if name in ('persona', 'file'):
            command.add_argument('name')
        if name in ('file', 'files'):
            command.add_argument('--area', choices=sorted(AREAS), default='game')
        if name == 'personas':
            command.add_argument('--search', default='')
        if name == 'logs':
            command.add_argument('source', choices=('game', 'runtime', 'gateway'))
        if name in ('logs', 'errors'):
            command.add_argument('--since', default='24 hours ago' if name == 'errors' else None)
            command.add_argument('--lines', type=int, default=None)
            command.add_argument('--follow', action='store_true')
        if name == 'errors':
            command.add_argument('--context', type=int, default=0, help='Preceding journal entries per finding')
    return root


def execute(args):
    if args.action in ('logs', 'errors'):
        if args.lines is not None and args.lines < 1:
            raise InspectionError('--lines must be positive')
        if args.action == 'errors':
            if not 0 <= args.context <= MAX_CONTEXT_ENTRIES:
                raise InspectionError(f'--context must be between 0 and {MAX_CONTEXT_ENTRIES}')
            entries = journal_entries(since=args.since, lines=args.lines, follow=args.follow)
            if args.follow:
                previous = deque(maxlen=args.context)
                if not args.json:
                    print('Following runtime/gateway journal; each recognised finding is emitted as it arrives.', flush=True)
                for entry in entries:
                    report = diagnose([entry])
                    if report['findings']:
                        report['findings'][0]['context'] = list(previous)
                        if args.json:
                            print(json.dumps(report), flush=True)
                        else:
                            print_findings(report)
                            sys.stdout.flush()
                    previous.append(context_entry(entry))
                return
            report = diagnose(entries, context=args.context)
            report['coverage'] = {'requested_sources': list(SERVICES.values()), 'since': args.since,
                                  'line_limit': args.lines, 'scope': 'host journal including guest console; not player transcripts'}
            if args.json:
                print(json.dumps(report, indent=2))
            else:
                print_findings(report)
                print(f"Scanned {report['entries_scanned']} entries since {args.since}; limit={args.lines or 'none'}.")
                missing = set(SERVICES.values()) - set(report['sources_observed'])
                if missing:
                    print('No entries observed for: ' + ', '.join(sorted(missing)))
                if not report['findings']:
                    print('No recognised errors in the inspected logs and time range.')
            return
        if args.source != 'game':
            for entry in journal_entries(args.source, args.since, args.lines or DEFAULT_LOG_LINES, args.follow):
                print(json.dumps({'version': SCHEMA_VERSION, 'entry': entry}) if args.json else
                      f"{timestamp(entry)} {safe_terminal(message_text(entry))}", flush=True)
            return
        if args.follow or args.since:
            raise InspectionError('Game log supports --lines; --follow/--since apply to host journals')
        with NativeInspector() as native:
            report = native.text('MUD.LOG', area='logs')
        report['text'] = '\n'.join(report['text'].splitlines()[-(args.lines or DEFAULT_LOG_LINES):])
    else:
        if not 0 < args.port < 65536:
            raise InspectionError('Invalid loopback guest port')
        if args.action == 'file':
            text_filename(args.name)
        with NativeInspector(args.port) as native:
            if args.action == 'inspection-install':
                native.install()
                report = {'version': SCHEMA_VERSION, 'installed': ['MVPER', 'MVTXT']}
            elif args.action in ('personas', 'persona'):
                report = native.personas()
                query = args.name.lower() if args.action == 'persona' else args.search.lower()
                report['personas'] = [row for row in report['personas'] if
                                      (row['name'].lower() == query if args.action == 'persona'
                                       else query in row['name'].lower())]
                if args.action == 'persona' and not report['personas']:
                    raise InspectionError('Saved persona not found')
            elif args.action == 'files':
                report = native.files(args.area)
            else:
                report = native.text(args.name, args.area)
    if args.json:
        print(json.dumps(report, indent=2))
    elif 'personas' in report:
        print('Saved personas (guest-clock dates; password values excluded)')
        print(f"{'Name':10} {'Score':>10} {'Games':>7} {'Password':>9}")
        for row in report['personas']:
            print(f"{row['name']:10} {row['score']:>10} {row['games']:>7} {'set' if row['password_set'] else 'unset':>9}")
            if args.action == 'persona':
                print(f"  Strength {row['strength']}; dexterity {row['dexterity']}; stamina {row['stamina']}/{row['stamina_max']}")
                print(f"  Guest last-play day {row['last_play_guest_day']}, fraction {row['last_play_guest_fraction']}; "
                      f"state flags {row['state_flags']}; sex bit {row['sex_bit']}")
        print(f"{len(report['personas'])} matching; {report['records']} total records, {report['deleted']} deleted.")
    elif 'installed' in report:
        print('Installed and verified standalone readers: ' + ', '.join(report['installed']))
    else:
        if report.get('truncated'):
            print('[Showing retained tail; earlier file content omitted]')
        print(safe_terminal(report.get('text', report.get('listing', ''))))


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        execute(args)
        return 0
    except (InspectionError, OSError, EOFError) as error:
        print('Inspection failed: ' + str(error), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    sys.exit(main())
