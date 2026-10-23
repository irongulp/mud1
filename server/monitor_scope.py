"""Pinned KS10 swap-output scope correction, generated from verified live words.

Independently authored host tooling. Historical monitor instructions are read
from the user's installed image; no replacement monitor or research snapshot is
bundled. See docs/local-monitor-fix.md for provenance and acceptance scope.
"""
import hashlib
import re

PATCH_ID = 'ks10-swap-output-scope-v1'
ADDRESS_MASK = 0o777777
WORD_MASK = (1 << 36) - 1
ALLOCATION_WORDS = 0o100
P, T1 = 1, 2
SVEUB, SSEUB = 0o351177, 0o351204
CPOPJ, CPOPJ1 = 0o344247, 0o344245
PI_DISABLE_7, PI_ENABLE_7 = 0o1001, 0o2001
RESTORED_OFFSET, UNMASKED_OFFSET = 8, 12
SCOPED_BODY_OFFSET, COPIED_BODY_OFFSET = 14, 18
SOURCE_RANGES = ((0o506703, 0o506744), (0o506756, 0o506763), (0o510516, 0o510522))
FINGERPRINTS = {
    (0o506703, 0o506744): 'd4494cf04701e8fa6e19984c03497119f8a77ebefa1e5bb756cc75839295cfba',
    (0o506756, 0o506763): '4692f13d471e8c0dfe410e0b691ca65781713f7ac7d053c1b1d870d88a8cd873',
    (0o510516, 0o510522): '1eb3f0790cadaf6536c587aca9b97427bb07c1eeb35870146536a614f4484108',
    (0o351177, 0o351226): '7d557733d60b47c2baaa0c16b1c2fb2593d75ca3092ead1c149de2ae38f74b3d',
    (0o344245, 0o344247): '7c6c004a22c81502361b993de39aa951371bf323856c9d20b2af3a4dd8ca3615',
    (0o401334, 0o401362): 'a701c9e2743d3db167efd8416b40ae2ed40ae1e9959161808c9953410aa22a68',
    (0o401363, 0o401423): '082603ef3dbefcf98d24d3a3e645bf405b8b20051501538c2120aa23a190b062',
    (0o401554, 0o401621): '35f048cb7fd2da8a269e3fae02f3e88975cea95769b4fc87b5b81d1ed07e6bea',
}


class MonitorBootstrapError(RuntimeError):
    """The guarded correction did not complete; admission must remain closed."""


class MonitorCompatibilityError(MonitorBootstrapError):
    """Unsupported installed monitor; never fall back to uncorrected admission."""


def digest_words(words):
    return hashlib.sha256(b''.join(word.to_bytes(5, 'big') for word in words)).hexdigest()


def verify_fingerprints(words, expected=FINGERPRINTS):
    for (first, last), digest in expected.items():
        try:
            actual = digest_words(words[address] for address in range(first, last + 1))
        except (KeyError, OverflowError, AttributeError) as error:
            raise MonitorCompatibilityError('Incomplete monitor fingerprint') from error
        if actual != digest:
            raise MonitorCompatibilityError(f'Unsupported monitor code at {first:06o}-{last:06o}')


def parse_words(text, first, last):
    result, previous = {}, None
    for line in text.splitlines():
        word = re.fullmatch(r'([0-7]+):\s+([0-7]{12})', line)
        repeated = re.fullmatch(r'([0-7]+): thru ([0-7]+): same as above\.', line)
        if word:
            address, previous = (int(field, 8) for field in word.groups())
            if not first <= address <= last:
                raise ValueError('Memory response outside requested range')
            result[address] = previous
        elif repeated:
            if previous is None:
                raise ValueError('Repeat without a preceding word')
            start, end = (int(field, 8) for field in repeated.groups())
            if not first <= start <= end <= last:
                raise ValueError('Repeated memory response outside requested range')
            result.update(dict.fromkeys(range(start, end + 1), previous))
    if set(result) != set(range(first, last + 1)):
        raise ValueError('Incomplete simulator memory response')
    return result


def bitmap_block(address, base, bitmap):
    offset = address - base
    if offset < 0 or offset % 4:
        raise ValueError('Not an aligned kernel allocation block')
    block = offset // 4
    return bitmap + block // 36, 1 << (35 - block % 36)


def stack_push(pointer):
    if pointer >> 18 == ADDRESS_MASK:
        raise ValueError('No null-stack capacity')
    return (pointer + (1 << 18) + 1) & WORD_MASK


def inst(op, ac=0, address=0, index=0):
    return (op << 27) | (ac << 23) | (index << 18) | (address & ADDRESS_MASK)


def build_patch(source, base, capacity):
    expected = {
        0o506703: inst(0o303, 0o15, 0o43),
        0o506704: inst(0o254, address=0o506713),
        0o506705: inst(0o260, P, SVEUB),
        0o506716: inst(0o254, address=0o506756),
        0o506720: inst(0o254, address=0o510516),
        0o506744: inst(0o254, address=0o506071),
        0o506763: inst(0o254, address=0o506335),
        0o510522: inst(0o254, address=0o506756),
    }
    if any(source.get(address) != value for address, value in expected.items()):
        raise MonitorCompatibilityError('Unexpected monitor scope layout')
    wrapper = [
        inst(0o261, P, T1), inst(0o700, 0o15, T1), inst(0o261, P, T1),
        inst(0o700, 0o14, PI_DISABLE_7), inst(0o200, T1, -1, P),
        inst(0o260, P, base + SCOPED_BODY_OFFSET),
        inst(0o254, address=base + RESTORED_OFFSET), inst(0o350, 0, -2, P),
        inst(0o262, P, T1), inst(0o405, T1, 1),
        inst(0o322, T1, base + UNMASKED_OFFSET), inst(0o700, 0o14, PI_ENABLE_7),
        inst(0o262, P, T1), inst(0o263, P),
        inst(0o260, P, SSEUB), inst(0o260, P, base + COPIED_BODY_OFFSET),
        inst(0o263, P), inst(0o254, address=CPOPJ1),
    ]
    if len(wrapper) != COPIED_BODY_OFFSET:
        raise ValueError('Invalid wrapper instruction layout')
    relocated, next_address = {}, base + len(wrapper)
    for first, last in SOURCE_RANGES:
        for address in range(first, last + 1):
            relocated[address] = next_address
            next_address += 1
    if base < 0o20 or next_address > base + capacity or next_address > ADDRESS_MASK:
        raise ValueError('Patch exceeds its owned allocation')
    payload = {base + offset: value for offset, value in enumerate(wrapper)}
    for old, new in relocated.items():
        value = source[old]
        if old in (0o506744, 0o506763):
            value = inst(0o254, address=CPOPJ1 if old == 0o506744 else CPOPJ)
        elif value & ADDRESS_MASK in relocated:
            if value & ((1 << 22) | (15 << 18)):
                raise MonitorCompatibilityError('Unexpected indirect internal branch')
            value = (value & ~ADDRESS_MASK) | relocated[value & ADDRESS_MASK]
        payload[new] = value
    return dict(payload=payload, relocations=relocated, replacements={
        0o506703: inst(0o260, P, base),
        0o506704: inst(0o254, address=0o506335),
        0o506705: inst(0o254, address=0o506071),
    })
