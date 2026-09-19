"""Check BBC widths and editing in Chromium against the local original game."""
import asyncio
import secrets
import string

from aiohttp.test_utils import TestServer
from playwright.async_api import async_playwright

from server.gateway import create_app
from tests.browser_smoke import command, check_editing_and_width, wait_prompt, wait_text


async def main():
    async with TestServer(create_app()) as server:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch()
            try:
                for style in ('bbc40', 'bbc0'):
                    page = await browser.new_page()
                    try:
                        await page.add_init_script(f"localStorage.setItem('mud86-terminal-style', '{style}')")
                        await page.goto(str(server.make_url('/')))
                        await page.evaluate('terminalReady')
                        await page.evaluate("""() => {
                            window.gameOutput = '';
                            socket.addEventListener('message', event => gameOutput += event.data);
                        }""")
                        await wait_text(page, 'By what name shall I call you?')
                        name = 'Bbc' + ''.join(secrets.choice(string.ascii_lowercase) for _ in range(5))
                        await command(page, name)
                        await wait_text(page, 'What sex do you wish to be?')
                        await command(page, 'm')
                        await wait_text(page, 'letters, please.')
                        await command(page, 'testpass')
                        await wait_text(page, 'Hello, ' + name)
                        await wait_prompt(page)
                        failures = await check_editing_and_width(page, name)
                        assert not failures, '\n'.join(failures)
                        if style == 'bbc40':
                            # Check word integrity, not just absence of xterm soft-wraps.
                            await page.evaluate("gameOutput = ''")
                            phrase = 'A sentence with thirty characters: elephant walks past.'
                            await command(page, 'say ' + phrase)
                            await wait_prompt(page)
                            screen = await page.evaluate(r"""() => {
                                const b = terminal.buffer.active;
                                return Array.from({length: b.length}, (_, i) => b.getLine(i).translateToString(true)).join('\n');
                            }""")
                            assert 'elephant' in screen, screen
                            assert 'eleph\nant' not in screen, screen
                        for target in (('original', 'bbc40') if style == 'bbc40' else ('bbc40', 'bbc0')):
                            await page.evaluate("window.previousSocket = socket; gameOutput = ''; terminal.focus()")
                            await page.keyboard.press('Tab')
                            await page.get_by_label('Terminal style').select_option(target)
                            await page.get_by_role('button', name='Change settings and reconnect').click()
                            await page.wait_for_function("socket !== previousSocket", timeout=30000)
                            await page.evaluate("socket.addEventListener('message', event => gameOutput += event.data)")
                            await page.wait_for_function("gameOutput.includes('By what name shall I call you?')", timeout=30000)
                            expected = 40 if target == 'bbc40' else 80
                            assert await page.evaluate('terminal.cols') == expected
                        print(f'PASS: {style} login, editing, INFO and confirmed restarts in-game and at persona prompt', flush=True)
                    finally:
                        await page.close()
            finally:
                await browser.close()


if __name__ == '__main__':
    asyncio.run(main())
