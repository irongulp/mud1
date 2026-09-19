"""Password editing in Chromium against the local original game."""
import asyncio
import secrets
import string

from aiohttp.test_utils import TestServer
from playwright.async_api import async_playwright

from server.gateway import create_app
from tests.browser_smoke import command, wait_display, wait_prompt, wait_text


async def edit_password(page, label, failures):
    await wait_prompt(page)
    await page.evaluate("gameOutput = ''")
    await page.keyboard.type('testpaxs')
    await page.keyboard.press('Backspace')
    await page.keyboard.press('Backspace')
    await page.keyboard.type('ss')
    # No-echo input has no completion marker; allow the emulated serial line
    # to process the edit before checking for unintended output.
    await page.wait_for_timeout(1000)
    await wait_display(page)
    output = await page.evaluate('gameOutput')
    if output:
        failures.append(f'{label}: password editing emitted {output!r}')
    await page.keyboard.press('Enter')


async def main():
    async with TestServer(create_app()) as server:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch()
            failures = []
            try:
                for style in ('original', 'vt220', 'bbc40', 'bbc0'):
                    page = await browser.new_page()
                    try:
                        await page.add_init_script(f"localStorage.setItem('mud86-terminal-style', '{style}')")
                        await page.add_init_script("""(() => {
                            window.gameOutput = '';
                            window.WebSocket = class extends WebSocket {
                                constructor(...args) {
                                    super(...args);
                                    this.addEventListener('message', event => gameOutput += event.data);
                                }
                            };
                        })();""")
                        await page.goto(str(server.make_url('/')))
                        await wait_text(page, 'By what name shall I call you?')
                        name = 'Pw' + ''.join(secrets.choice(string.ascii_lowercase) for _ in range(6))
                        await command(page, name)
                        await wait_text(page, 'What sex do you wish to be?')
                        await command(page, 'm')
                        await wait_text(page, 'letters, please.')
                        await edit_password(page, style + ' creation', failures)
                        await wait_text(page, 'Hello, ' + name)
                        await wait_prompt(page)
                        await page.evaluate("gameOutput = ''")
                        await command(page, 'save')
                        await wait_prompt(page)
                        assert name + ' saved.' in await page.evaluate('gameOutput')
                        await page.evaluate("gameOutput = ''")
                        await command(page, 'quit')
                        await page.wait_for_function("gameOutput.includes('By what name shall I call you?')", timeout=30000)
                        await wait_display(page)
                        await command(page, name)
                        await page.wait_for_function("gameOutput.includes(\"This persona already exists - what's the password?\")", timeout=20000)
                        await edit_password(page, style + ' existing', failures)
                        await page.wait_for_function("gameOutput.includes('Yes!') || gameOutput.includes('No!')", timeout=20000)
                        if 'Yes!' not in await page.evaluate('gameOutput'):
                            failures.append(f'{style}: corrected password was rejected')
                        else:
                            await wait_prompt(page)
                            await command(page, 'quit')
                            await page.wait_for_function('socket.readyState === WebSocket.CLOSED')
                    finally:
                        await page.close()
                assert not failures, '\n'.join(failures)
                print('PASS: password creation and existing-password backspace are silent and authenticate in all four styles')
            finally:
                await browser.close()


if __name__ == '__main__':
    asyncio.run(main())
