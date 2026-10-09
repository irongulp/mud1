"""Private H1 handover and stop-and-wait R1 read exchange.

Fresh client challenges are provisioned by the standalone test controller. This
is not an authenticated public service. Database getters must supply their own
bounded I/O, such as persona_mariadb.isolated_mariadb().
"""
import re
import secrets
import socket
import time

from tools.persona_protocol import (
    DEFAULT_TIMEOUT, EPOCH_LIMIT, MAX_LINE_BYTES, RECORD_WORDS,
    ProtocolError, decode_get, lookup_response,
)

HISTORY_LIMIT = 1024
IDLE_TIMEOUT = 60
HELLO = re.compile(rb'H1 HELLO ([0-7]{24})\r\n?')
ACCEPT = re.compile(rb'H1 ACCEPT ([0-7]{24}) ([0-7]{24})\r\n?')
ACK = re.compile(rb'R1 ACK ([0-7]{24}) ([0-7]{12}) ([0-7]{2})\r\n?')


def _token(value):
    if type(value) is not int or not 0 < value < EPOCH_LIMIT:
        raise ProtocolError('Invalid handover token')
    return f'{value:024o}'


def hello(challenge):
    return f'H1 HELLO {_token(challenge)}\r'.encode('ascii')


def accept(challenge, epoch):
    return f'H1 ACCEPT {_token(challenge)} {_token(epoch)}\r'.encode('ascii')


def ack(request, index):
    if type(index) is not int or not 0 <= index <= RECORD_WORDS + 1:
        raise ProtocolError('Invalid response credit')
    return f'R1 ACK {request.epoch:024o} {request.sequence:012o} {index:02o}\r'.encode('ascii')


def new_token():
    return secrets.randbelow(EPOCH_LIMIT - 1) + 1


class ReadSession:
    """One physical line, many non-overlapping owners, one GET per epoch.

    receive returns at most one response frame. A new, never-used HELLO retires
    any previous operation. The getter returns a snapshot synchronously, then
    this session alone sends it under credit. A database getter must bound that
    call: while it is running, the channel cannot consume a new HELLO. Isolated
    storage workers never receive a bridge socket and cannot emit late frames.
    """
    def __init__(self, fetch, *, clock=time.monotonic, epoch_factory=new_token,
                 timeout=DEFAULT_TIMEOUT, history_limit=HISTORY_LIMIT):
        if timeout <= 0 or history_limit <= 0:
            raise ValueError('Positive timeout and history limit required')
        self.fetch, self.clock, self.epoch_factory = fetch, clock, epoch_factory
        self.timeout, self.history_limit = timeout, history_limit
        self.challenges, self.epochs = set(), set()
        self.deadline = None
        self.state = 'idle'
        self.challenge = self.epoch = self.request = None
        self.rows = []
        self.index = 0

    @property
    def active(self):
        return self.state != 'idle'

    def retire(self):
        self.rows.clear()
        self.state, self.deadline = 'idle', None
        self.challenge = self.epoch = self.request = None
        self.index = 0

    def expire(self):
        if self.deadline is not None and self.clock() >= self.deadline:
            self.retire()
            raise TimeoutError('Read session expired')

    def receive(self, line):
        try:
            greeting = HELLO.fullmatch(line)
            if greeting:
                challenge = int(greeting[1], 8)
                _token(challenge)
                if challenge in self.challenges or len(self.challenges) >= self.history_limit:
                    raise ProtocolError('Repeated challenge or handover history exhausted')
                self.retire()
                epoch = self.epoch_factory()
                _token(epoch)
                if epoch in self.epochs:
                    raise ProtocolError('Epoch reuse')
                self.challenges.add(challenge)
                self.epochs.add(epoch)
                self.challenge, self.epoch = challenge, epoch
                self.state, self.deadline = 'offered', self.clock() + self.timeout
                return f'H1 OFFER {challenge:024o} {epoch:024o}\r'.encode('ascii')
            self.expire()
            if self.state == 'offered':
                confirmation = ACCEPT.fullmatch(line)
                if not confirmation or tuple(int(part, 8) for part in confirmation.groups()) != (self.challenge, self.epoch):
                    raise ProtocolError('Handover confirmation mismatch')
                self.state = 'ready'
                return f'H1 READY {self.challenge:024o} {self.epoch:024o}\r'.encode('ascii')
            if self.state == 'ready':
                request = decode_get(line)
                if request.epoch != self.epoch or request.sequence != 1:
                    raise ProtocolError('Unexpected read epoch or sequence')
                self.request = request
                self.deadline = self.clock() + self.timeout
                self.rows = lookup_response(request, self.fetch).splitlines(keepends=True)
                self.expire()  # Never emit a snapshot that returned after its deadline.
                self.state, self.index = 'credit', 0
                return self.rows[0]
            if self.state == 'credit':
                credit = ACK.fullmatch(line)
                if not credit or tuple(int(part, 8) for part in credit.groups()) != (
                        self.epoch, self.request.sequence, self.index):
                    raise ProtocolError('Response credit mismatch')
                self.index += 1
                if self.index == len(self.rows):
                    self.retire()
                    return None
                return self.rows[self.index]
            raise ProtocolError('No active read session')
        except (ProtocolError, TimeoutError):
            self.retire()
            raise


class LineSocket:
    """Bounded CR framing; do not over-read data belonging to another owner."""
    def __init__(self, connection):
        self.connection = connection
        self.after_cr = False

    def read(self, deadline):
        data = bytearray()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Channel frame deadline expired')
            self.connection.settimeout(remaining)
            try:
                block = self.connection.recv(1)
            except socket.timeout:
                raise TimeoutError('Channel frame deadline expired') from None
            if not block:
                if data:
                    raise ProtocolError('Truncated channel frame')
                return None
            byte = block[0]
            if self.after_cr:
                self.after_cr = False
                if byte == 10:
                    continue
            if byte == 13:
                self.after_cr = True
                if not data:
                    raise ProtocolError('Empty channel frame')
                return bytes(data) + b'\r'
            if byte < 32 or byte > 126 or len(data) >= MAX_LINE_BYTES:
                raise ProtocolError('Invalid or oversized channel frame')
            if not data:
                deadline = min(deadline, time.monotonic() + DEFAULT_TIMEOUT)
            data.append(byte)

    def send(self, data, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Channel output deadline expired')
        self.connection.settimeout(remaining)
        try:
            self.connection.sendall(data)
        except socket.timeout:
            raise TimeoutError('Channel output deadline expired') from None


def serve_reads(connection, fetch, *, epoch_factory=new_token, on_event=None):
    """Serve a private fixture connection; caller owns its lifecycle and socket.

    Events contain state only, never raw messages/records. Semantic failures
    retire the owner and allow a new HELLO; framing failures/EOF terminate the
    connection. The socket owner must reconnect after those failures.
    """
    session, wire = ReadSession(fetch, epoch_factory=epoch_factory), LineSocket(connection)
    while True:
        deadline = session.deadline or time.monotonic() + IDLE_TIMEOUT
        try:
            line = wire.read(deadline)
            if line is None:
                session.retire()
                return
            try:
                response = session.receive(line)
            except (ProtocolError, TimeoutError):
                if on_event:
                    on_event('rejected')
                continue  # Retired by receive(); only a new HELLO can restart.
            if response is not None:
                wire.send(response, session.deadline)
            if on_event:
                on_event(session.state)
        except (ProtocolError, TimeoutError):
            session.retire()
            # Do not silently resynchronize an incomplete/oversized wire frame.
            # The fixture supervisor owns reconnect and clean bootstrap.
            raise
