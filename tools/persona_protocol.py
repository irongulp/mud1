"""Experimental read-only logical-persona wire contract, independent of a database.

No listener, native MUD adapter or lease handshake is implemented here. A caller
must bind each request to a freshly established channel epoch and one configured
persona store. Never log encoded record bodies: word 8 is the native password.
"""
from dataclasses import dataclass, field
from functools import reduce
from operator import xor
import re
import time
from typing import Optional, Tuple

from tools.storage_bridge import ProtocolError, WORD_MASK
from tools.persona_errors import InvalidRecord

FORMAT_VERSION = 1
RECORD_WORDS = 11  # Native offsets 1..11; offset 0 is physical chain bookkeeping.
EPOCH_LIMIT = 1 << 72
MAX_LINE_BYTES = 79
MAX_RESPONSE_BYTES = (RECORD_WORDS + 2) * (MAX_LINE_BYTES + 2)
DEFAULT_TIMEOUT = 5
MAX_NAME_LENGTH = 9
CHAR_BITS = 7
CHARS_PER_WORD = 5
CHAR_MASK = (1 << CHAR_BITS) - 1
LENGTH_SHIFT = 29
ERROR_STATUSES = frozenset(('NOT_FOUND', 'UNAVAILABLE', 'INVALID_RECORD'))
NAME = re.compile(rf'[a-z0-9]{{1,{MAX_NAME_LENGTH}}}')
COMMON = re.compile(rb'R1 ([A-Z_]+) ([0-7]{24}) ([0-7]{12})(.*)')
GET = re.compile(rb'R1 GET ([0-7]{24}) ([0-7]{12}) ([0-7]{12}) ([0-7]{12})\r\n?')


def _words(values, count):
    if (not isinstance(values, (tuple, list)) or len(values) != count
            or any(type(word) is not int or not 0 <= word <= WORD_MASK for word in values)):
        raise ProtocolError('Invalid logical record words')
    return tuple(values)


def pack_name(name):
    """Encode already-canonical native text; input parsing/case folding stays in BCPL."""
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise ProtocolError('Invalid canonical persona name')
    words = [len(name) << LENGTH_SHIFT, 0]
    for index, char in enumerate(name, 1):
        words[index // CHARS_PER_WORD] |= ord(char) << (LENGTH_SHIFT - CHAR_BITS * (index % CHARS_PER_WORD))
    return tuple(words)


def _name_key(values):
    words = _words(values, 2)
    length = words[0] >> LENGTH_SHIFT
    if not 1 <= length <= MAX_NAME_LENGTH:
        raise ProtocolError('Invalid packed persona name')
    name = ''.join(chr((words[index // CHARS_PER_WORD] >>
                       (LENGTH_SHIFT - CHAR_BITS * (index % CHARS_PER_WORD))) & CHAR_MASK)
                   for index in range(1, length + 1))
    canonical = pack_name(name)
    if tuple(word & ~1 for word in words) != canonical:
        raise ProtocolError('Noncanonical packed persona name')
    return canonical


def validate_name_key(values):
    """Validate a logical lookup key without constructing a wire request."""
    words = _words(values, 2)
    if words != _name_key(words):
        raise ProtocolError('Lookup key contains persona flag bits')
    return words


@dataclass(frozen=True)
class GetRequest:
    epoch: int
    sequence: int
    name_words: Tuple[int, int]

    def __post_init__(self):
        if (type(self.epoch) is not int or not 0 < self.epoch < EPOCH_LIMIT
                or type(self.sequence) is not int or not 0 < self.sequence <= WORD_MASK):
            raise ProtocolError('Invalid read identity')
        object.__setattr__(self, 'name_words', validate_name_key(self.name_words))


@dataclass(frozen=True)
class LogicalRecord:
    words: Tuple[int, ...] = field(repr=False)

    def __post_init__(self):
        object.__setattr__(self, 'words', _words(self.words, RECORD_WORDS))
        _name_key(self.words[1:3])

    @property
    def name_words(self):
        return _name_key(self.words[1:3])


@dataclass(frozen=True)
class ReadResult:
    status: str
    record: Optional[LogicalRecord] = field(default=None, repr=False)

    def __post_init__(self):
        if self.status == 'FOUND':
            if not isinstance(self.record, LogicalRecord):
                raise ProtocolError('FOUND requires a complete logical record')
        elif self.status not in ERROR_STATUSES or self.record is not None:
            raise ProtocolError('Invalid read outcome')


def _prefix(operation, request):
    return f'R1 {operation} {request.epoch:024o} {request.sequence:012o}'


def encode_get(request):
    return (_prefix('GET', request)
            + ''.join(f' {word:012o}' for word in request.name_words) + '\r').encode('ascii')


def decode_get(data):
    match = GET.fullmatch(data)
    if not match:
        raise ProtocolError('Malformed read request')
    epoch, sequence, first, second = (int(part, 8) for part in match.groups())
    return GetRequest(epoch, sequence, (first, second))


def _checksum(words):
    # Error detection only, not authentication. Every input is a 36-bit word.
    return reduce(xor, words, FORMAT_VERSION ^ RECORD_WORDS)


def encode_result(request, result):
    if result.status != 'FOUND':
        return (_prefix(result.status, request) + '\r').encode('ascii')
    record = result.record
    if record.name_words != request.name_words:
        raise ProtocolError('Record identity differs from lookup key')
    rows = [_prefix('FOUND', request) + f' {FORMAT_VERSION:03o} {RECORD_WORDS:03o}']
    rows.extend(_prefix('WORD', request) + f' {index:02o} {word:012o}'
                for index, word in enumerate(record.words, 1))
    rows.append(_prefix('END', request) + f' {_checksum(record.words):012o}')
    return ('\r'.join(rows) + '\r').encode('ascii')


def lookup_response(request, fetch):
    """Pure fixture/adapter boundary; the future service must bound backend I/O.

    fetch receives the canonical two-word name key in an already selected store.
    Only None means absent. Exceptions and invalid data have distinct outcomes.
    """
    try:
        value = fetch(request.name_words)
    except InvalidRecord:
        return encode_result(request, ReadResult('INVALID_RECORD'))
    except Exception:
        return encode_result(request, ReadResult('UNAVAILABLE'))
    if value is None:
        return encode_result(request, ReadResult('NOT_FOUND'))
    try:
        record = value if isinstance(value, LogicalRecord) else LogicalRecord(value)
        return encode_result(request, ReadResult('FOUND', record))
    except ProtocolError:
        return encode_result(request, ReadResult('INVALID_RECORD'))


class ResponseDecoder:
    """One bounded response; publish a record only after its validated END frame.

    Time is measured over the whole response, not restarted by each fragment or
    word. Call check_deadline while awaiting input; finish handles EOF. The socket
    owner must use that same deadline for reads. Any failure poisons this decoder.
    """
    def __init__(self, request, *, timeout=DEFAULT_TIMEOUT, clock=time.monotonic):
        if timeout <= 0:
            raise ValueError('Response timeout must be positive')
        self.request = request
        self._clock = clock
        self.deadline = clock() + timeout
        self._buffer = bytearray()
        self._after_cr = False
        self._size = 0
        self._state = 'header'
        self._words = []
        self._result = None

    @property
    def result(self):
        return self._result

    def _poison(self):
        self._state = 'failed'
        self._buffer.clear()
        self._words.clear()
        self._result = None

    def check_deadline(self):
        if self._state == 'failed':
            raise ProtocolError('Read response has already failed')
        if self._result is None and self._clock() >= self.deadline:
            self._poison()
            raise TimeoutError('Read response deadline expired')

    def feed(self, data):
        self.check_deadline()
        try:
            for byte in data:
                self._size += 1
                if self._size > MAX_RESPONSE_BYTES:
                    raise ProtocolError('Read response exceeds byte limit')
                if self._after_cr:
                    self._after_cr = False
                    if byte == 10:
                        continue
                if self._result is not None:
                    raise ProtocolError('Unexpected data after read response')
                if byte == 13:
                    self._consume(bytes(self._buffer))
                    self._buffer.clear()
                    self._after_cr = True
                else:
                    if byte < 32 or byte > 126 or len(self._buffer) >= MAX_LINE_BYTES:
                        raise ProtocolError('Invalid or oversized read frame')
                    self._buffer.append(byte)
            return self._result
        except ProtocolError:
            self._poison()
            raise

    def _consume(self, line):
        match = COMMON.fullmatch(line)
        if not match:
            raise ProtocolError('Malformed read response')
        operation, epoch, sequence, tail = match.groups()
        if int(epoch, 8) != self.request.epoch or int(sequence, 8) != self.request.sequence:
            raise ProtocolError('Read response identity mismatch')
        if self._state == 'header':
            status = operation.decode('ascii')
            if status in ERROR_STATUSES and not tail:
                self._result = ReadResult(status)
                self._state = 'done'
                return
            shape = re.fullmatch(rb' ([0-7]{3}) ([0-7]{3})', tail)
            if (status != 'FOUND' or not shape
                    or tuple(int(part, 8) for part in shape.groups()) != (FORMAT_VERSION, RECORD_WORDS)):
                raise ProtocolError('Unsupported record format or outcome')
            self._state = 'words'
        elif self._state == 'words':
            word = re.fullmatch(rb' ([0-7]{2}) ([0-7]{12})', tail)
            if operation != b'WORD' or not word or int(word[1], 8) != len(self._words) + 1:
                raise ProtocolError('Invalid record word order')
            self._words.append(int(word[2], 8))
            if len(self._words) == RECORD_WORDS:
                self._state = 'end'
        elif self._state == 'end':
            checksum = re.fullmatch(rb' ([0-7]{12})', tail)
            if operation != b'END' or not checksum or int(checksum[1], 8) != _checksum(self._words):
                raise ProtocolError('Invalid record terminator or checksum')
            record = LogicalRecord(self._words)
            if record.name_words != self.request.name_words:
                raise ProtocolError('Record identity differs from lookup key')
            self._result = ReadResult('FOUND', record)
            self._words.clear()
            self._state = 'done'
        else:
            raise ProtocolError('Unexpected read response state')

    def finish(self):
        self.check_deadline()
        if self._result is None:
            self._poison()
            raise ProtocolError('Truncated read response')
        return self._result
