"""Original-engine/browser RESET acceptance on a disposable baseline disk."""
import argparse
import asyncio
from contextlib import ExitStack
import json
from pathlib import Path
import time

from aiohttp import ClientSession
from aiohttp.test_utils import TestServer

from server.gateway import create_app
from tests.integration_gateway_cleanup import Browser, deployment_emulator
from tests.integration_provisioning import require, source_hashes
from tools.provision_archwizards import NativePersonas
from tools.reset_permissions import configure, RESET_PROTECTION

ROOT = Path(__file__).resolve().parents[1]
PASSWORD = 'resetpwd'


async def command(browser, text, wizard=False, expected=None):
    await browser.socket.send_str(text + '\r')
    await browser.expect(text)
    output = await browser.expect(expected) if expected else ''
    return output + await browser.expect('\n----*' if wizard else '\n*')


def identical(native, before, after):
    native.command('r filcom', b'\n*')
    result = native.command('tty:=' + before + ',' + after + '/b', b'\n*')
    require('No differences encountered' in result, 'Native file contents changed: ' + before)
    native.connection.write(b'\x1a')
    native.expect(b'\n.')


async def policy(machine, native, output):
    evidence = {}
    require(not await asyncio.to_thread(configure, native), 'Configuration rerun was not idempotent')
    async with TestServer(create_app(upstream_port=machine.port)) as server, ClientSession() as client:
        async def login(name, wizard=False):
            browser = Browser(await client.ws_connect(server.make_url('/terminal')))
            await browser.login(name, PASSWORD, wizard=wizard)
            return browser

        ordinary = await login('Rplain')
        wizard = await login('Rwizard')
        await command(wizard, 'wizard mode', wizard=True)
        roy = await login('Roy', wizard=True)
        for label, browser, is_wizard in [('ordinary', ordinary, False), ('wizard', wizard, True)]:
            expected = 'What?' if label == 'ordinary' else 'more than just you'
            result = await command(browser, 'reset', is_wizard, expected)
            require(expected in result, label + ' bypassed multiplayer restriction: ' + repr(result))
            evidence[label + '_multiplayer_refused'] = result
        await asyncio.to_thread(native.command, 'copy rstbef.pm=mud.?pm')
        result = await command(roy, 'reset', True, 'You are now in a superseded game.')
        require('superseded game' in result and "can't get at" not in result, 'Archwizard reset failed')
        evidence['archwizard_multiplayer_reset'] = result
        await asyncio.to_thread(native.command, 'copy rstaft.pm=mud.?pm')
        await asyncio.to_thread(identical, native, 'rstbef.pm', 'rstaft.pm')
        # A new name is used so saved-persona admission cannot attach to old players.
        fresh = Browser(await client.ws_connect(server.make_url('/terminal')))
        await fresh.expect('By what name shall I call you?')
        await fresh.expect('*')
        await fresh.socket.send_str('Rfresh\r')
        await fresh.expect('What sex do you wish to be?')
        await fresh.expect('*')
        await fresh.socket.send_str('m')
        await fresh.expect('letters, please.')
        await fresh.expect('*')
        await fresh.socket.send_str(PASSWORD + '\r')
        await fresh.expect('Hello, Rfresh!')
        await fresh.expect('\n*')
        who = await command(fresh, 'who', expected='Rfresh is playing')
        require('Rfresh is playing' in who and all(name not in who for name in ('Roy', 'Rplain', 'Rwizard')),
                'New browser joined the superseded world')
        evidence['new_world_who'] = who
        # TXTBTM.GET's unlesswiz action rejects RESET before SF.RESET.
        result = await command(fresh, 'reset', expected='What?')
        require('What?' in result, 'Ordinary solo player was allowed to reset')
        evidence['ordinary_solo_refused'] = result
        for browser in (fresh, ordinary, wizard, roy):
            await browser.socket.close()
    # Saved credentials still authenticate after all reset/cleanup transitions.
    async with TestServer(create_app(upstream_port=machine.port)) as server, ClientSession() as client:
        wizard = Browser(await client.ws_connect(server.make_url('/terminal')))
        await wizard.expect('By what name shall I call you?')
        await wizard.expect('*')
        await wizard.socket.send_str('Rwizard\r')
        await wizard.expect("what's the password?")
        await wizard.expect('*')
        await wizard.socket.send_str(PASSWORD + '\r')
        await wizard.expect('Hello again, Rwizard')
        admission = await wizard.expect('*')
        if '----*' not in admission:
            await command(wizard, 'wizard mode', True)
        await wizard.socket.send_str('reset\r')
        result = await wizard.expect('Everything in the game has been reset')
        try:
            evidence['wizard_solo_reset'] = result + await wizard.expect('\n----*')
            require("can't get at" not in evidence['wizard_solo_reset'], 'Solo wizard reset failed')
        except Exception:
            (output / 'solo-reset-failure.txt').write_text(result + wizard.buffer)
            raise
        await wizard.socket.close()
    (output / 'policy.json').write_text(json.dumps(evidence, indent=2) + '\n')
    return evidence


async def chromium(machine, output, bootstrap=None):
    from playwright.async_api import async_playwright
    from tests.browser_smoke import wait_display

    evidence = {}
    app = create_app(upstream_port=machine.port, session_bootstrap=bootstrap)
    async with TestServer(app) as server, async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            for chat in (False, True):
                page = await browser.new_page()
                await page.add_init_script("localStorage.setItem('mud86-chat-mode', " +
                                           json.dumps('true' if chat else 'false') + ");")
                await page.add_init_script("""window.gameOutput = '';
                    const OriginalWebSocket = window.WebSocket;
                    window.WebSocket = class extends OriginalWebSocket {
                        constructor(...args) {
                            super(...args);
                            this.addEventListener('message', e => window.gameOutput += e.data);
                        }
                    };""")
                await page.goto(str(server.make_url('/')))
                await page.evaluate('terminalReady')

                async def expect(text):
                    await page.wait_for_function('text => gameOutput.includes(text)', arg=text, timeout=30000)
                    await wait_display(page)

                async def submit(text):
                    await page.evaluate("gameOutput = ''")
                    if chat:
                        field = page.get_by_label('Command', exact=True)
                        await field.fill(text)
                        await field.press('Enter')
                    else:
                        await page.keyboard.type(text)
                        await page.keyboard.press('Enter')

                await expect('By what name shall I call you?')
                await submit('Roy')
                await expect("what's the password?")
                await submit(PASSWORD)
                await expect('Hello again, Roy')
                await expect('\n----*')
                await submit('reset')
                await expect('You are now in a superseded game.')
                await expect('\n----*')
                label = 'chat' if chat else 'terminal'
                evidence[label] = await page.evaluate('gameOutput')
                require("can't get at" not in evidence[label], 'Chromium RESET failed')
                await page.screenshot(path=str(output / (label + '-reset.png')))
                await submit('quit')
                await expect('By what name shall I call you?')
                await submit('Roy')
                await expect("what's the password?")
                await submit(PASSWORD)
                await expect('Hello again, Roy')
                await expect('\n----*')
                await submit('who')
                await expect('Roy the arch-wizard is playing')
                await expect('\n----*')
                require('superseded' not in await page.evaluate('gameOutput'), 'Browser returned to old world')
                await page.close()
                # Let the gateway finish QUIT/KJOB before the next persona login.
                await asyncio.sleep(1)
        finally:
            await browser.close()
    (output / 'chromium.json').write_text(json.dumps(evidence, indent=2) + '\n')
    return evidence


async def combat(machine, output):
    evidence = {}
    async with TestServer(create_app(upstream_port=machine.port)) as server, ClientSession() as client:
        roy = Browser(await client.ws_connect(server.make_url('/terminal')))
        await roy.login('Roy', PASSWORD, wizard=True)
        other = Browser(await client.ws_connect(server.make_url('/terminal')))
        await other.login('Rwizard', PASSWORD, wizard=True)
        evidence['attack'] = await command(roy, 'kill Rwizard', True)
        evidence['response'] = await command(other, 'look me', True)
        evidence['reset'] = await command(roy, 'reset', True, "Not while you're fighting!")
        (output / 'combat.json').write_text(json.dumps(evidence, indent=2) + '\n')
        require("Not while you're fighting!" in evidence['reset'], 'Combat reset restriction not witnessed')
        await command(roy, 'flee west', True)
        await roy.socket.close()
        await other.socket.close()
    return evidence


async def exercise(machine, native, output, protections):
    results = {}
    for protection in protections:
        if protection == RESET_PROTECTION:
            await asyncio.to_thread(native.command, 'protect mud.exe<055>')
            require(await asyncio.to_thread(configure, native), 'Permission installer did not change <055>')
        else:
            await asyncio.to_thread(native.command, 'protect mud.exe<' + protection + '>')
        async with TestServer(create_app(upstream_port=machine.port)) as server, ClientSession() as client:
            socket = await client.ws_connect(server.make_url('/terminal'))
            browser = Browser(socket)
            await browser.login('Roy', PASSWORD, wizard=True)
            await socket.send_str('reset\r')
            response = await browser.expect('\n----*')
            results[protection] = response
            (output / 'reset-responses.json').write_text(json.dumps(results, indent=2) + '\n')
            await socket.close()
    require("can't get at" not in results[protections[-1]], 'RESET still cannot rename the executable')
    require('superseded game' in results[protections[-1]], 'RESET did not supersede the game')
    return results


def run(output, protections):
    output.mkdir(mode=0o700)
    original = source_hashes()
    machine = None
    report = {'complete': False}
    try:
        for attempt in range(3):
            machine = deployment_emulator(output / ('machine-' + str(attempt + 1)))
            startup = ExitStack()
            try:
                machine.boot()
                native = startup.enter_context(NativePersonas(machine.port))
                break
            except Exception:
                startup.close()
                machine.stop()
                machine = None
                if attempt == 2:
                    raise
        with startup:
            native.create_and_save('Roy', PASSWORD)
            native.create_and_save('Rplain', PASSWORD)
            native.create_and_save('Rwizard', PASSWORD)
            native.send('copy mud.wiz=tty:')
            native.expect(b'copy mud.wiz=tty:\r\n')
            native.send('rwizard')
            native.expect(b'\n')
            time.sleep(.1)
            native.connection.write(b'\x1a')
            native.expect(b'\n.')
            native.command('protect mud.wiz<055>')
            native.command('copy rstexe.exe=mud.exe')
            report['responses'] = asyncio.run(exercise(machine, native, output, protections))
            if protections[-1] == RESET_PROTECTION:
                report['policy'] = asyncio.run(policy(machine, native, output))
                report['chromium'] = asyncio.run(chromium(machine, output))
                report['combat'] = asyncio.run(combat(machine, output))
            identical(native, 'rstexe.exe', 'mud.exe')
            report['executable_bytes_unchanged'] = True
        require(source_hashes() == original, 'Original source changed')
        report.update(behavior_complete=True, source_unchanged=True)
        machine.command('r opr', 'OPR>')
        machine.child.send('set ksys now\r')
        machine.child.expect_exact('KSYS processing completed', timeout=120)
        report.update(complete=True, clean_shutdown=True)
    finally:
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        if machine:
            machine.stop()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'runtime' / f'reset-{time.time_ns()}')
    parser.add_argument('--protections', nargs='+', choices=['055','054','053','052','051','050'],
                        default=[RESET_PROTECTION])
    args = parser.parse_args()
    run(args.output.resolve(), args.protections)
