"""Offline EXE/symbol reader for private KSYS layout research, not live capture.

Input character encoding is tapeutils/t10backup.c pars_5chars (all 36 bits).
EXE page records follow SIMH PDP10/pdp10_sys.c load_exe. Defined symbols use
the legacy negative-count .JBSYM table and DDT RADIX50 flags. Other symbol
formats are deliberately unsupported. Disk matches establish byte presence,
not directory ownership, executable selection or resident job identity.
"""
import struct


WORD_BITS = 36
WORD_MASK = (1 << WORD_BITS) - 1
HALF_BITS = 18
HALF_MASK = (1 << HALF_BITS) - 1
PAGE_WORDS = 512
DISK_WORD_BYTES = 8
BACKUP_WORD_BYTES = 5
EXE_DIRECTORY = 0o1776
EXE_VECTOR = 0o1775
EXE_OPTIONAL = 0o1774
EXE_END = 0o1777
PAGE_FIELD_BITS = 27
PAGE_FIELD_MASK = (1 << PAGE_FIELD_BITS) - 1
JOB_SYMBOL_POINTER = 0o116
SYMBOL_NAME_BITS = 32
SYMBOL_NAME_MASK = (1 << SYMBOL_NAME_BITS) - 1
RADIX50 = ' 0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ.$%'
SYMBOL_CHARACTERS = 6


def backup_words(raw):
    """Decode complete extracted words; never guess missing trailing bytes."""
    if len(raw) % BACKUP_WORD_BYTES:
        raise ValueError('Incomplete backup character word')
    result = []
    for offset in range(0, len(raw), BACKUP_WORD_BYTES):
        a, b, c, d, e = raw[offset:offset + BACKUP_WORD_BYTES]
        if (a | b | c | d) & 0x80:
            raise ValueError('Invalid backup character encoding')
        result.append((a << 29) | (b << 22) | (c << 15) | (d << 8)
                      | ((e & 0x7f) << 1) | (e >> 7))
    return result


def checked_words(words):
    if not words or any(type(word) is not int or not 0 <= word <= WORD_MASK for word in words):
        raise ValueError('Expected nonempty 36-bit words')


def load_exe(words):
    """Map file pages into user virtual addresses, rejecting gaps/overlap errors."""
    checked_words(words)
    offset, directory = 0, None
    while True:
        if offset >= len(words):
            raise ValueError('Missing EXE end block')
        kind, length = words[offset] >> HALF_BITS, words[offset] & HALF_MASK
        if not length or offset + length > len(words):
            raise ValueError('Truncated EXE block')
        body = words[offset + 1:offset + length]
        offset += length
        if kind == EXE_DIRECTORY:
            if directory is not None or not body or len(body) % 2:
                raise ValueError('Invalid EXE directory')
            directory = body
        elif kind == EXE_OPTIONAL:
            continue
        elif kind in (EXE_END, EXE_VECTOR):
            if length != (1 if kind == EXE_END else 3):
                raise ValueError('Invalid EXE terminal block')
            break
        else:
            raise ValueError('Unsupported EXE block')
    if directory is None:
        raise ValueError('Missing EXE directory')
    memory = {}
    for index in range(0, len(directory), 2):
        file_page = directory[index] & PAGE_FIELD_MASK
        memory_page = directory[index + 1] & PAGE_FIELD_MASK
        pages = (directory[index + 1] >> PAGE_FIELD_BITS) + 1
        if (memory_page + pages) * PAGE_WORDS > HALF_MASK + 1:
            raise ValueError('EXE exceeds section-zero address space')
        for repeat in range(pages):
            address = (memory_page + repeat) * PAGE_WORDS
            start = (file_page + repeat) * PAGE_WORDS
            if file_page and start + PAGE_WORDS > len(words):
                raise ValueError('Truncated EXE page')
            if any(address + n in memory for n in range(PAGE_WORDS)):
                raise ValueError('Overlapping EXE pages')
            page = words[start:start + PAGE_WORDS] if file_page else [0] * PAGE_WORDS
            memory.update((address + n, word) for n, word in enumerate(page))
    return memory


def symbol_name(word):
    code = word & SYMBOL_NAME_MASK
    if code >= len(RADIX50) ** SYMBOL_CHARACTERS:
        raise ValueError('Invalid RADIX50 name')
    text = ''
    for _ in range(SYMBOL_CHARACTERS):
        code, character = divmod(code, len(RADIX50))
        text = RADIX50[character] + text
    return text.strip()


def symbols(memory):
    pointer = memory.get(JOB_SYMBOL_POINTER, 0)
    count = (-(pointer >> HALF_BITS)) & HALF_MASK
    start = pointer & HALF_MASK
    if not pointer & (1 << (WORD_BITS - 1)) or not count or count % 2:
        raise ValueError('Missing or unsupported .JBSYM table')
    if start + count > HALF_MASK + 1 or any(n not in memory for n in range(start, start + count)):
        raise ValueError('Unmapped .JBSYM table')
    return [(symbol_name(memory[n]), memory[n] >> SYMBOL_NAME_BITS, memory[n + 1])
            for n in range(start, start + count, 2)]


def unique_symbol(table, name, *, flags):
    """Require an explicit DDT type and exactly one entry, including locals."""
    matches = [value for symbol, kind, value in table if symbol == name and kind == flags]
    if len(matches) != 1:
        raise ValueError('Missing or ambiguous symbol: ' + name)
    return matches[0]


def disk_matches(disk, words):
    """Find whole little-endian word sequences, retaining every aligned copy."""
    checked_words(words)
    raw = struct.pack('<%dQ' % len(words), *words)
    offsets, position = [], 0
    while True:
        position = disk.find(raw, position)
        if position < 0:
            return offsets
        if position % DISK_WORD_BYTES == 0:
            offsets.append(position)
        position += 1
