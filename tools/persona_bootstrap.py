"""Private controller bootstrap for generated external-persona MUD images.

Only call on a controller-owned monitor connection, never a player input stream.
ROBOOT's marker is linked first at low address 140 octal. Seeds are supplied via
ROSEED's per-job TMPCOR file, atomically read/deleted by the game, not DEPOSIT.
"""
import re

from tools.persona_session import new_token

MARKER_ADDRESS = 0o140
RESERVED_ADDRESSES = (0o141, 0o142)
BOOT_MARKER = 0o621714324560
IMAGE = 'dskb:mud[2011,2776]'


def examined_word(text, address):
    matches = [(int(location, 8), (int(high, 8) << 18) | int(low, 8))
               for location, high, low in re.findall(r'([0-7]+)/\s+([0-7]+)\s+([0-7]+)', text)]
    values = [word for location, word in matches if location == address]
    if len(values) != 1:
        raise ValueError('Missing or ambiguous bootstrap examination')
    return values[0]


class SeedIssuer:
    def __init__(self):
        self.used = set()

    def load(self, monitor):
        monitor.command('get ' + IMAGE)
        def examine(address):
            # TOPS-10 EXAMINE ends in a tab, not necessarily CRLF before '.'.
            text = monitor.command(f'examine {address:o}', b'.')
            monitor.at_monitor = True
            return examined_word(text, address)
        marker = examine(MARKER_ADDRESS)
        if marker != BOOT_MARKER:
            raise ValueError('Not an approved external-persona bootstrap image')
        for address in RESERVED_ADDRESSES:
            if examine(address) != 0:
                raise ValueError('Unsupported bootstrap image header')
        while True:
            seed = new_token()
            if seed >> 36 and seed not in self.used:
                break
        self.used.add(seed)
        monitor.command('run dskb:roseed[2011,2776]', b'ROSEED READY\r\n')
        result = monitor.command(f'{seed:024o}')
        if 'ROSEED SET' not in result:
            raise ValueError('Bootstrap token was not provisioned')
        monitor.command('get ' + IMAGE)
        if examine(MARKER_ADDRESS) != BOOT_MARKER:
            raise ValueError('Bootstrap image changed during provisioning')
        return seed
