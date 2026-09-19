"""Verify local 24/7 MUD access without changing the historical HOURS table.

Run with the operator console at its monitor prompt and an emulated time outside
historical opening hours. Creates a disposable
saved persona. --reset-world additionally supersedes the shared world, only
after WHO confirms that the test persona is the sole player.
"""
import argparse
import asyncio
import re
import secrets
import string
import time
from pathlib import Path

from aiohttp import ClientSession
from aiohttp.test_utils import TestServer

from server.gateway import create_app
from tests.integration_web import Browser
from tools.boot import exchange

ROOT = Path(__file__).resolve().parents[1]
CLOSING_GRACE_SECONDS = 5 * 60
CHECK_INTERVAL_SECONDS = 15
DEFAULT_DURATION = CLOSING_GRACE_SECONDS + 30
PASSWORD = 'testpass'
HISTORICAL_HOURS = '''Opening hours as follows:
Sunday 0000 to 2400
Monday 0000 to 0700
Tuesday 0200 to 0700
Wednesday 0200 to 0700
Thursday 0200 to 0700
Friday 0200 to 0700
Saturday 0200 to 2400'''


async def command(player, text):
    await player.send(text)
    await player.expect(text)
    output = await player.expect('\n*')
    assert 'will be closing' not in output and 'is now closed' not in output, output
    return output


async def check_hours(player):
    output = await command(player, 'hours')
    assert ' '.join(HISTORICAL_HOURS.split()) in ' '.join(output.split()), output
    assert 'demonstration' not in output.lower(), output


async def enter_existing(player):
    await player.expect('By what name shall I call you?')
    await player.send(player.name)
    await player.expect("what's the password?")
    await player.send(PASSWORD)
    await player.expect('Hello again, ' + player.name)
    await player.expect('\n*')


async def main(args):
    clock = await asyncio.to_thread(exchange, 'DAYTIME\r', 1)
    match = re.search(r'(Sunday|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday)\s+\S+\s+(\d+):\d+:\d+', clock)
    assert match, 'Cannot verify guest clock; leave the operator console at its monitor prompt: ' + clock
    day, hour = match[1], int(match[2])
    schedule = next(line.split() for line in HISTORICAL_HOURS.splitlines() if line.startswith(day))
    start, end = int(schedule[1]) // 100, int(schedule[3]) // 100
    assert not start <= hour < end, 'Test requires a guest time outside the historical schedule: ' + clock
    print('Guest clock:', match[0], flush=True)
    name = args.name or 'Av' + ''.join(secrets.choice(string.ascii_lowercase) for _ in range(6))
    print('Disposable persona:', name, flush=True)
    async with TestServer(create_app()) as server, ClientSession() as client:
        with args.log.open('w') as log:
            log.write('[operator clock]\n' + clock)
            async def connect(existing=False):
                player = Browser(await client.ws_connect(server.make_url('/terminal')), name, log)
                if existing:
                    await enter_existing(player)
                else:
                    await player.enter()
                return player

            player = await connect(args.existing)
            try:
                await check_hours(player)
                if not args.existing:
                    await command(player, 'save')
                deadline = time.monotonic() + args.duration
                while time.monotonic() < deadline:
                    await asyncio.sleep(min(CHECK_INTERVAL_SECONDS, deadline - time.monotonic()))
                    await command(player, 'look')
                await check_hours(player)
                if args.reset_world:
                    who = await command(player, 'who')
                    names = re.findall(r'(\w+) is playing', who)
                    assert names == [name], 'Other players present; not resetting: ' + who
                await command(player, 'score')
                await player.send('quit')
                await player.expect('\r\n.')
            finally:
                await player.socket.close()
            print(f'PASS: ordinary persona plays for {args.duration}s outside hours; historical HOURS retained', flush=True)

            if args.reset_world:
                result = await asyncio.to_thread(exchange,
                    'RENAME DSKB:MUD.EXE[2011,2776]=DSKB:MUD.EXE[2011,2776]\r', 2)
                log.write('\n[operator reset]\n' + result)
                assert 'Files renamed:' in result and 'MUD.EXE' in result, result
            player = await connect(existing=True)
            try:
                await check_hours(player)
                await command(player, 'look')
                await player.send('quit')
                await player.expect('\r\n.')
            finally:
                await player.socket.close()
            print('PASS: saved persona/password and 24/7 access survive reconnect'
                  + (' and world reset' if args.reset_world else ''), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--duration', type=float, default=DEFAULT_DURATION)
    parser.add_argument('--reset-world', action='store_true')
    parser.add_argument('--name')
    parser.add_argument('--existing', action='store_true')
    parser.add_argument('--log', type=Path, default=ROOT / 'runtime/availability.log')
    args = parser.parse_args()
    if args.duration < 0 or (args.existing and not args.name):
        parser.error('Use a nonnegative duration and provide --name with --existing')
    asyncio.run(main(args))
