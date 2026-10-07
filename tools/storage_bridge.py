"""Experimental, storage-free PING/PONG protocol for a private TOPS-10 line.

This is a transport probe, not a persona service or a public TCP endpoint.
"""
from dataclasses import dataclass
import re
import socket
import time

WORD_BITS = 36
WORD_MASK = (1 << WORD_BITS) - 1
IDENTITY_LIMIT = 1 << 18
MAX_FRAME_BYTES = 64
REQUEST_TIMEOUT = 5
FRAME = re.compile(rb'B1 (PING|PONG) ([0-7]{6}) ([0-7]{6}) ([0-7]{12})')


class ProtocolError(ValueError):
    """Invalid or miscorrelated probe traffic (never include raw payloads)."""


@dataclass(frozen=True)
class Frame:
    kind: str
    session: int
    request: int
    word: int

    def encode(self):
        if (self.kind not in ('PING', 'PONG')
                or not 0 < self.session < IDENTITY_LIMIT
                or not 0 < self.request < IDENTITY_LIMIT
                or not 0 <= self.word <= WORD_MASK):
            raise ProtocolError('Invalid probe frame fields')
        return (f'B1 {self.kind} {self.session:06o} {self.request:06o} '
                f'{self.word:012o}\r').encode('ascii')


class FrameDecoder:
    """Incremental bounded framing, accepting CR with an optional following LF."""
    def __init__(self):
        self.buffer = bytearray()
        self.after_cr = False

    def feed(self, data):
        frames = []
        for byte in data:
            if self.after_cr:
                self.after_cr = False
                if byte == 10:
                    continue
            if byte == 13:
                match = FRAME.fullmatch(self.buffer)
                if not match:
                    raise ProtocolError('Malformed probe frame')
                frame = Frame(match[1].decode('ascii'), *(int(part, 8) for part in match.groups()[1:]))
                frame.encode()  # Apply the same range/identity checks on input.
                frames.append(frame)
                self.buffer.clear()
                self.after_cr = True
            else:
                if byte < 32 or byte > 126 or len(self.buffer) >= MAX_FRAME_BYTES:
                    raise ProtocolError('Invalid or oversized probe frame')
                self.buffer.append(byte)
        return frames

    def finish(self):
        if self.buffer:
            raise ProtocolError('Truncated probe frame')


def respond(connection, *, timeout=REQUEST_TIMEOUT, on_request=None):
    """Respond on an already connected private socket; caller owns and closes it.

    Each connection has a fixed session and strictly increasing request numbers.
    The deadline is per complete request, not reset by trickled partial bytes.
    on_request is an optional evidence callback, never a storage operation.
    """
    decoder = FrameDecoder()
    session = None
    previous = 0
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Probe request deadline expired')
        connection.settimeout(remaining)
        try:
            data = connection.recv(MAX_FRAME_BYTES)
        except socket.timeout:
            raise TimeoutError('Probe request deadline expired') from None
        if not data:
            decoder.finish()
            return
        for frame in decoder.feed(data):
            if (frame.kind != 'PING' or frame.request <= previous
                    or (session is not None and frame.session != session)):
                raise ProtocolError('Unexpected probe session, sequence or operation')
            session, previous = frame.session, frame.request
            if on_request:
                on_request(frame)
            connection.sendall(Frame('PONG', session, previous, frame.word).encode())
            deadline = time.monotonic() + timeout
