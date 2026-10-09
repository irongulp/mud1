"""Controller-only bootstrap on a newly allocated MUDGUEST terminal."""
import asyncio

from tools.persona_bootstrap import BOOT_MARKER, IMAGE, MARKER_ADDRESS, RESERVED_ADDRESSES, examined_word
from tools.persona_session import new_token

BOOTSTRAP_TIMEOUT = 30
INTRODUCTION = b'By what name shall I call you?'
MAX_INTRO_BYTES = 16384


class ExternalBootstrap:
    def __init__(self, *, timeout=BOOTSTRAP_TIMEOUT, token_factory=new_token):
        self.timeout, self.token_factory = timeout, token_factory
        self.used = set()

    async def __call__(self, reader, writer):
        return await asyncio.wait_for(self.bootstrap(reader, writer), self.timeout)

    async def bootstrap(self, reader, writer):
        # MUDGUEST's existing autostart reaches a name question without touching
        # storage. Stop it before any player input, then load the approved image.
        async def introduction():
            data=bytearray()
            while len(data) < MAX_INTRO_BYTES:
                block=await reader.read(1)
                if not block: raise EOFError('Guest closed before introduction')
                data.extend(block.encode('ascii') if isinstance(block,str) else block)
                if data.endswith(INTRODUCTION): return bytes(data)
                if data.endswith(b'\n.'):
                    raise OSError('Guest returned to monitor before introduction')
            raise OSError('Guest introduction exceeded bound')
        await introduction()
        async def command(text, marker=b'\n.'):
            writer.write(text + '\r')
            return await introduction() if marker==INTRODUCTION else await reader.readuntil(marker)
        await command('\x03\x03')
        await command('get ' + IMAGE)
        async def examine(address):
            response = await command(f'examine {address:o}', b'.')
            try: return examined_word(response.decode('ascii'), address)
            except (ValueError, UnicodeError): raise OSError('Bootstrap examination failed') from None
        if await examine(MARKER_ADDRESS) != BOOT_MARKER:
            raise OSError('Unapproved external image')
        for address in RESERVED_ADDRESSES:
            if await examine(address) != 0: raise OSError('Unsupported external image header')
        for attempt in range(100):
            seed = self.token_factory()
            if type(seed) is int and 0 < seed < (1 << 72) and seed >> 36 and seed not in self.used:
                self.used.add(seed)
                break
        else: raise OSError('No fresh bootstrap identity')
        await command('run dskb:roseed[2011,2776]', b'ROSEED READY\r\n')
        if b'ROSEED SET' not in await command(f'{seed:024o}'):
            raise OSError('Seed provisioning failed')
        await command('get ' + IMAGE)
        if await examine(MARKER_ADDRESS) != BOOT_MARKER: raise OSError('Bootstrap image changed')
        return await command('start', INTRODUCTION)
