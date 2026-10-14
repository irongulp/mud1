"""Verified printable input for a controller-owned, echo-enabled guest prompt.

Never use this implicitly for player input, passwords, or arbitrary programs.
The caller owns prompt synchronization, post-Enter completion, and recovery.
"""
import re
import time

MAX_CONTROL_LINE = 255
COPY_READY_DELAY = .1
MAX_CONSOLE_NOTICE = 160
MAX_MONITOR_PADDING = 16
MAX_OPERATOR_FRAME = 4096
MAX_OPERATOR_FRAMES = 8
_HOURLY_STATUS = re.compile(
    rb'\r\nMonitor KS10\r\nSystem uptime '
    rb'(?:[0-9]*:[0-5][0-9]:[0-5][0-9]|[0-5]?[0-9]\.[0-9]{2})\r\n'
    rb'Current date/time (?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday) '
    rb'[0-9]{1,2}-(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)-[0-9]{3,4} '
    rb'[0-9]{1,2}:[0-5][0-9]:[0-5][0-9]\r\n\r\n')
_OPERATOR_TIME = rb' *[0-9]{1,2}:[0-9]{2}:[0-9]{2} +'
_OPERATOR_MESSAGES = re.compile(
    rb'(?:\n*(?:' + _OPERATOR_TIME + rb'-- Begin auto take file --\n +File: SYS:SYSTEM\.CMD\[1,4\]\n|'
    + _OPERATOR_TIME + rb'-- End auto take file --\n +[0-9]+ lines processed\n|'
    + _OPERATOR_TIME + rb'-- Message from the Accounting System --\n +Account validation is not required\n|'
    + _OPERATOR_TIME + rb'Batch-Stream [0-9]+ +-- Started --\n|'
    + _OPERATOR_TIME + rb'-- BATCON logging out --\n +All streams have been idle for 10 minutes\n|'
    + _OPERATOR_TIME + rb'Batch-Stream [01] +-- Shutdown --\n|'
    + _OPERATOR_TIME + rb'Batch-Stream [0-9]+ +-- Begin --\n'
      rb' +Job (?P<probe>MB[0-9A-F]{4}) Req #[0-9]+ for RICHARD \[2011,2776\]\n'
      rb' +Control file: +DSKB:(?P=probe)\.CTL\[2011,2776\]\n'
      rb' +Log file: +DSKB:(?P=probe)\.LOG\[2011,2776\]\n|'
    + _OPERATOR_TIME + rb'Batch-Stream [0-9]+ +-- End --\n'
      rb' +Job MB[0-9A-F]{4} Req #[0-9]+ for RICHARD \[2011,2776\]\n))+\n*')


class ControlError(RuntimeError):
    def __init__(self, message, *, submitted=False, input_started=False):
        super().__init__(message)
        self.submitted = submitted
        self.input_started = input_started


def completed_logout(text):
    """Logged-off is a prefix; terminal reuse waits for accounting and prompt."""
    text = text.replace('\r', '').expandtabs(8)
    return re.search(r'Logged-off[^\n]*\n[\s\S]*?'
                     r'^Disk Reads:[0-9]+, Writes:[0-9]+, Blocks saved:[0-9]+\n\n\.$',
                     text, re.M) is not None


def submit_line(text, write, read_one, *, timeout, clock=None, notice=None, monitor_padding=False, redraw=None):
    """Acknowledge every byte before Enter; never search past unexpected data.

    read_one must return at most one byte, consume buffered data before reading
    the transport, and return b'' on timeout. A zero timeout is a pending-data
    check. Returned bytes reconstruct the consumed echo for existing parsers.
    No automatic replay is safe here: after Enter an operation may have run.
    """
    if (not isinstance(text, str) or not 0 < len(text) <= MAX_CONTROL_LINE
            or any(not ' ' <= char <= '~' for char in text)):
        raise ValueError('Control lines must contain bounded printable ASCII only')
    if monitor_padding and text.startswith('.'):
        raise ValueError('A control line cannot start with the monitor prompt character')
    clock = clock or time.monotonic
    deadline = clock() + timeout
    submitted = False
    input_started = False
    first_echo = False
    padding_bytes = 0

    def boundary(data):
        nonlocal padding_bytes
        # Some native companions leave an additional empty monitor prompt.
        # Consume only this bounded grammar, only before the first echo. A dot
        # must never acknowledge a command byte or complete a submitted request.
        if monitor_padding and not first_echo and data in (b'.', b'\r', b'\n'):
            padding_bytes += 1
            if padding_bytes > MAX_MONITOR_PADDING:
                raise ControlError('Excess monitor boundary output')
            return True
        return notice is not None and notice(data, read_one, deadline, clock)

    def pending(prefix=b''):
        while True:
            data = read_one(0)
            if not data:
                return
            if prefix and redraw and redraw(data, prefix, read_one, deadline, clock):
                continue
            if not boundary(data):
                raise ControlError('Unexpected pending control output')

    try:
        encoded = text.encode('ascii')
        for position, value in enumerate(encoded):
            if clock() >= deadline:
                raise ControlError('Control echo deadline expired')
            pending(encoded[:position])
            if clock() >= deadline:
                raise ControlError('Control echo deadline expired')
            byte = bytes([value])
            input_started = True
            write(byte)
            while True:
                remaining = deadline - clock()
                if remaining <= 0:
                    raise ControlError('Control echo deadline expired')
                echoed = read_one(remaining)
                if echoed == byte:
                    first_echo = True
                    break
                if redraw and redraw(echoed, encoded[:position + 1], read_one, deadline, clock):
                    first_echo = True
                    break
                if not boundary(echoed):
                    raise ControlError('Control character echo was not confirmed')
        if clock() >= deadline:
            raise ControlError('Control echo deadline expired')
        pending(encoded)
        if clock() >= deadline:
            raise ControlError('Control echo deadline expired')
        # Even a failed write may have delivered Enter. Never claim otherwise.
        submitted = True
        write(b'\r')
    except ControlError as error:
        error.input_started = input_started
        error.submitted = error.submitted or submitted
        raise
    except (OSError, EOFError, TimeoutError) as error:
        raise ControlError('Control transport failed', submitted=submitted,
                           input_started=input_started) from error
    return text.encode('ascii')


def operator_redraw(first, prefix, read_one, deadline, clock):
    """Validate witnessed OPR startup notifications and the entire redrawn line.

    OPR can interrupt an in-flight echo with notices, then redraw its prompt and
    current input. Matching only the final character would accept corrupted
    input; require the complete typed prefix before acknowledging that byte.
    """
    if first not in (b'\r', b'\n'):
        return False
    frame = bytearray(first)
    for _ in range(MAX_OPERATOR_FRAMES):
        while len(frame) < MAX_OPERATOR_FRAME and clock() < deadline:
            byte = read_one(max(0, deadline - clock()))
            if not byte:
                return False
            frame.extend(byte)
            if frame.endswith(b'\nOPR>'):
                break
        else:
            return False
        message = bytes(frame[:-4]).replace(b'\r', b'').strip(b'\n') + b'\n'
        if not _OPERATOR_MESSAGES.fullmatch(message):
            return False
        first_prefix = read_one(max(0, deadline - clock()))
        if first_prefix in (b'\r', b'\n'):
            # Another complete notification may precede the actual redraw.
            frame = bytearray(first_prefix)
            continue
        if first_prefix != prefix[:1]:
            return False
        for expected in prefix[1:]:
            if clock() >= deadline or read_one(max(0, deadline - clock())) != bytes([expected]):
                return False
        return True
    return False


def console_notice(first, read_one, deadline, clock):
    """Recognize the witnessed CTY stomper and hourly monitor announcements.

    This is not a search for the next matching echo. Unrecognized diagnostics,
    stale prompts and incomplete notices still abort submission. Pexpect's
    console transcript retains this notice; it is not hidden from operators.
    """
    if first not in (b'%', b'\r'):
        return False
    data = bytearray(first)
    while len(data) < MAX_CONSOLE_NOTICE and clock() < deadline:
        byte = read_one(max(0, deadline - clock()))
        if not byte:
            return False
        data.extend(byte)
        if first == b'\r':
            if data.endswith(b'\r\n\r\n'):
                return _HOURLY_STATUS.fullmatch(data) is not None
            continue
        if byte == b'\n':
            return re.fullmatch(rb'%%TTY STOMPER: Quieting open line on TTY[0-7]+ at  NODE\. '
                                rb'failed, code 0\r?\n', data) is not None
    return False


def telnet_byte(connection, timeout):
    index, _, data = connection.expect([br'[\s\S]'], timeout)
    return data if index == 0 else b''


def console_byte(child, timeout):
    import pexpect
    try:
        # expect, unlike read_nonblocking, consumes pexpect's existing buffer.
        child.expect(r'[\s\S]', timeout=timeout)
        return child.after.encode('ascii')
    except pexpect.TIMEOUT:
        return b''
    except pexpect.EOF:
        raise EOFError('Guest console closed') from None
