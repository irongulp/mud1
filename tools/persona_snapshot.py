"""Private, validated native persona snapshots. There is no native export writer."""
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from types import MappingProxyType

from tools.persona_protocol import LogicalRecord, WORD_MASK

HEADER_WORDS = 256
HASH_BUCKETS = 253
FREE_HEAD = 254
FILE_LENGTH = 255
SLOT_WORDS = 12
MAX_SLOTS = 8192
MAX_WORDS = HEADER_WORDS + MAX_SLOTS * SLOT_WORDS
MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024
SNAPSHOT_FORMAT = 'mud86-native-personas'


class MigrationError(Exception):
    """A public-safe diagnostic; never include record bodies or credentials."""


def digest_words(words):
    digest = hashlib.sha256()
    for word in words: digest.update(word.to_bytes(5, 'big'))
    return digest.hexdigest()


def logical_digest(records):
    digest = hashlib.sha256()
    for key in sorted(records):
        for word in records[key].words: digest.update(word.to_bytes(5, 'big'))
    return digest.hexdigest()


@dataclass(frozen=True)
class NativeSnapshot:
    words: tuple = field(repr=False)
    records: object = field(init=False, repr=False)
    deleted: int = field(init=False)

    def __post_init__(self):
        words = tuple(self.words)
        if not HEADER_WORDS <= len(words) <= MAX_WORDS or any(type(w) is not int or not 0 <= w <= WORD_MASK for w in words):
            raise MigrationError('Invalid native word count or 36-bit value')
        length = words[FILE_LENGTH] or HEADER_WORDS
        if length != len(words) or (length - HEADER_WORDS) % SLOT_WORDS:
            raise MigrationError('Native logical file length does not match snapshot')
        object.__setattr__(self, 'words', words)
        seen, records = set(), {}
        def slot(offset):
            if offset < HEADER_WORDS or offset >= length or (offset-HEADER_WORDS) % SLOT_WORDS or offset in seen:
                raise MigrationError('Invalid, cyclic or multiply referenced native slot')
            seen.add(offset)
            return words[offset:offset+SLOT_WORDS]
        for bucket in range(HASH_BUCKETS):
            offset = words[bucket]
            while offset:
                raw = slot(offset)
                try:
                    record = LogicalRecord(raw[1:])
                except ValueError:
                    raise MigrationError('Malformed live native record') from None
                key = record.name_words
                if ((sum(key) & WORD_MASK) >> 1) % HASH_BUCKETS != bucket:
                    raise MigrationError('Native record is not reachable through its canonical hash bucket')
                if key in records: raise MigrationError('Duplicate canonical native persona identity')
                records[key] = record
                offset = raw[0]
        offset, deleted = words[FREE_HEAD], 0
        while offset:
            raw = slot(offset)
            if raw[2] or raw[3] or raw[1] & ((1 << 18)-1):
                raise MigrationError('Native free chain contains a live or uncleared identity')
            deleted += 1
            offset = raw[0]
        if len(seen) != (length-HEADER_WORDS) // SLOT_WORDS:
            raise MigrationError('Native file contains unreferenced allocated slots')
        object.__setattr__(self, 'records', MappingProxyType(records))
        object.__setattr__(self, 'deleted', deleted)

    @property
    def sha256(self): return digest_words(self.words)

    def report(self):
        return {'personas': len(self.records), 'deleted_slots': self.deleted,
                'allocated_slots': (len(self.words)-HEADER_WORDS)//SLOT_WORDS,
                'snapshot_sha256': self.sha256, 'logical_sha256': logical_digest(self.records)}


def strict_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result: raise MigrationError('Duplicate JSON field')
            result[key] = value
        return result
    try:
        return json.loads(data, object_pairs_hook=pairs)
    except (ValueError, UnicodeError):
        raise MigrationError('Malformed private JSON document') from None


def private_read(path, limit):
    with Path(path).open('rb') as stream:
        if os.fstat(stream.fileno()).st_mode & 0o077:
            raise MigrationError('Private input must not be accessible to group or other users')
        data = stream.read(limit + 1)
    if len(data) > limit: raise MigrationError('Private input exceeds size bound')
    return data


def publish_private(path, write):
    """Publish a completed private file atomically, without replacing any path."""
    path = Path(path)
    descriptor, temporary = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w+b') as stream:
            os.fchmod(stream.fileno(), 0o600)
            write(stream)
            stream.flush(); os.fsync(stream.fileno())
        os.link(temporary, path)  # Atomic, same filesystem, fails if path exists.
        directory = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        os.unlink(temporary)


def write_snapshot(path, snapshot):
    data = {'format': SNAPSHOT_FORMAT, 'version': 1, 'sha256': snapshot.sha256, 'words': snapshot.words}
    publish_private(path, lambda stream: stream.write(json.dumps(data, separators=(',', ':')).encode('ascii') + b'\n'))


def read_snapshot(path):
    data = strict_json(private_read(path, MAX_SNAPSHOT_BYTES))
    if (not isinstance(data, dict) or set(data) != {'format', 'version', 'sha256', 'words'}
            or data['format'] != SNAPSHOT_FORMAT or type(data['version']) is not int or data['version'] != 1
            or not isinstance(data['words'], list)):
        raise MigrationError('Unsupported native snapshot format')
    snapshot = NativeSnapshot(data['words'])
    if snapshot.sha256 != data['sha256']: raise MigrationError('Native snapshot checksum mismatch')
    return snapshot


def parse_native_dump(text):
    words, count, finished, check = [], None, False, 0
    for line in text.replace('\r', '').split('\n'):
        if not line.startswith('NS1 '): continue
        if finished: raise MigrationError('Data after native snapshot terminator')
        parts = line.split()
        if parts[:2] == ['NS1', 'BEGIN'] and count is None and len(parts) == 3 and parts[2].isdigit():
            count = int(parts[2])
            if not HEADER_WORDS <= count <= MAX_WORDS: raise MigrationError('Native snapshot exceeds word bound')
        elif (parts[:2] == ['NS1', 'DATA'] and count is not None and 4 <= len(parts) <= 15
              and parts[2].isdigit() and int(parts[2]) == len(words)):
            for token in parts[3:]:
                if not re.fullmatch(r'[0-7]{1,12}', token): raise MigrationError('Malformed native word')
                word = int(token, 8); words.append(word); check ^= word
            if len(words) > count: raise MigrationError('Native snapshot overrun')
        elif (parts[:2] == ['NS1', 'END'] and count is not None and len(parts) == 4
              and parts[2].isdigit() and int(parts[2]) == count == len(words)
              and re.fullmatch(r'[0-7]{1,12}', parts[3]) and int(parts[3], 8) == check):
            finished = True
        else:
            raise MigrationError('Malformed, incomplete or unordered native snapshot')
    if not finished: raise MigrationError('Incomplete native snapshot')
    return NativeSnapshot(words)
