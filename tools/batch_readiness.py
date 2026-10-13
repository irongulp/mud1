"""Prove native batch execution before admission and before requesting KSYS.

No game commands or persona records are involved. Probe files belong to the
controller's RICHARD maintenance account, not the protected OPR system account.
"""
import math
import re
import secrets
import time

from tools.build_external_guest import read_back
from tools.guest_control import COPY_READY_DELAY
from tools.inspect_game import NativeInspector

READY_TIMEOUT = 45
IO_TIMEOUT = 10
POLL_INTERVAL = .25
NAME_ATTEMPTS = 8
MAX_LOG_BYTES = 16384
# Keep the supplied system's normal five-minute batch CPU allowance. The host
# readiness deadline, not guest accounting ticks, bounds this short probe.
BATCH_CPU_SECONDS = 5 * 60
MARKER = 'MUD86 BATCH READY '
PPN = '[2011,2776]'


class BatchReadinessError(RuntimeError):
    def __init__(self, message, *, phase=None, name=None, request=None):
        super().__init__(message)
        self.phase, self.name, self.request = phase, name, request


class BatchInspector(NativeInspector):
    def __init__(self, port, deadline):
        super().__init__(port, timeout=IO_TIMEOUT)
        self.probe_deadline = deadline

    def command_timeout(self):
        if self.probe_deadline is None:
            return IO_TIMEOUT
        return max(0, min(IO_TIMEOUT, self.probe_deadline - time.monotonic()))

    def receive(self, marker):
        previous = self._command_deadline
        deadline = time.monotonic() + self.command_timeout()
        self._command_deadline = min(previous, deadline) if previous is not None else deadline
        try:
            return super().receive(marker)
        finally:
            self._command_deadline = previous

    def __exit__(self, *args):
        # Keep bounded cleanup possible even after the probe's deadline expired.
        self.probe_deadline = None
        return super().__exit__(*args)


def new_name():
    return 'mb' + secrets.token_hex(2)


def missing_file(text, filename):
    return re.search(r'(?mi)^%WLDNSF No such files as ' + re.escape(filename) + r'\r?$', text) is not None


def parse_submission(text, name):
    matches = re.findall(r'\[Batch job ([A-Z0-9]+) queued, request #([0-9]+), limit [0-9:]+\]', text)
    if len(matches) != 1 or matches[0][0] != name.upper():
        raise BatchReadinessError('Native batch submission was not confirmed')
    return int(matches[0][1])


def probe_completed(text, name, request, nonce):
    if len(text) > MAX_LOG_BYTES:
        return False
    # A line reused after browser VT100 setup preserves tabs; a text terminal
    # expands them. Interpret the same native columns without changing proof.
    text = text.replace('\r', '').expandtabs(8)
    headers = re.findall(r'(?m)^ +Job ([A-Z0-9]+) Req #([0-9]+) for RICHARD \[2011,2776\] in stream [0-9]+$', text)
    if headers != [(name.upper(), str(request))]:
        return False
    for extension, label in (('CTL', 'Control'), ('LOG', 'Log')):
        if not re.search(r'(?m)^ +' + label + r' file: +'
                         + re.escape(f'DSKB:{name.upper()}.{extension}{PPN}') + '$', text):
            return False
    stamp = r'^ *[0-9]{1,2}:[0-9]{2}:[0-9]{2} '
    patterns = [stamp + 'USER +' + re.escape(MARKER + nonce) + '$',
                stamp + r'BATCH +\.KJOB/BATCH$',
                stamp + r'USER +Logged-off TTY[0-9]+ .*$',
                stamp + r'USER +Disk Reads:[0-9]+, Writes:[0-9]+, Blocks saved:[0-9]+$']
    position = 0
    for pattern in patterns:
        match = re.search(pattern, text[position:], re.M)
        if match is None:
            return False
        position += match.end()
    return True


def put_text(native, filename, text, deadline):
    native.begin_copy(filename)
    for line in text.splitlines():
        if time.monotonic() >= deadline:
            raise BatchReadinessError('Native batch preparation deadline expired')
        native.send(line)
        native.receive(b'\n')
        time.sleep(min(COPY_READY_DELAY, max(0, deadline - time.monotonic())))
    if time.monotonic() >= deadline:
        raise BatchReadinessError('Native batch preparation deadline expired')
    native.connection.write(b'\x1a')
    native.receive(b'\n.')
    native.at_monitor = True
    if read_back(native, filename, text).strip() != text.strip():
        raise BatchReadinessError('Native batch probe file verification failed')


def _run_probe(port, timeout, progress):
    deadline = time.monotonic() + timeout
    nonce = secrets.token_hex(16).upper()
    with BatchInspector(port, deadline) as native:
        progress['phase'] = 'allocation'
        for _ in range(NAME_ATTEMPTS):
            name = new_name()
            if missing_file(native.command('directory ' + name + '.*'), name + '.*'):
                break
        else:
            raise BatchReadinessError('Cannot allocate a fresh native batch probe name')
        progress.update(phase='preparation', name=name)
        put_text(native, name + '.txt', MARKER + nonce + '\n', deadline)
        put_text(native, name + '.ctl', '.type ' + name + '.txt\n', deadline)
        progress['phase'] = 'submission'
        request = parse_submission(native.command('submit ' + name + '.ctl'
            '/output:nolog/batlog:supersede/norestart/assistance:no/time:' + str(BATCH_CPU_SECONDS)), name)
        progress.update(phase='completion', request=request)
        while time.monotonic() < deadline:
            queue = native.command('submit ' + name + '/list:all')
            if not re.search(r'(?m)^\[The queues are empty\]\r?$', queue):
                time.sleep(min(POLL_INTERVAL, max(0, deadline - time.monotonic())))
                continue
            # TYPE of a still-open log can end mid-line, without the normal
            # monitor frame. Wait for QUASAR to release the request first.
            listing = native.command('directory ' + name + '.log')
            if not missing_file(listing, name + '.log'):
                log = native.command('type ' + name + '.log')
                if probe_completed(log, name, request, nonce):
                    break
            time.sleep(min(POLL_INTERVAL, max(0, deadline - time.monotonic())))
        else:
            raise BatchReadinessError('Native batch probe did not execute and log out before its deadline')
        # Only the successful, nonce-bound probe's exact files are removed.
        # Failures retain all evidence; no wildcard deletion or request replay.
        progress['phase'] = 'cleanup'
        for extension in ('ctl', 'txt', 'log'):
            native.command('delete ' + name + '.' + extension)
    return {'name': name, 'request': request}


def ensure_batch_ready(port, *, timeout=READY_TIMEOUT):
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('Batch readiness timeout must be finite and positive')
    progress = {'phase': 'admission', 'name': None, 'request': None}
    try:
        return _run_probe(port, timeout, progress)
    except Exception as error:
        # Only controlled identifiers and an exception type, never a terminal
        # transcript, reach the public service log. Failed probe files remain.
        raise BatchReadinessError(
            f'Native batch readiness failed at {progress["phase"]} '
            f'({progress["name"]}, request {progress["request"]}): {type(error).__name__}',
            **progress) from error
