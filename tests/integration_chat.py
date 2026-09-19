"""Check Chat input and transcript against the local original game in Chromium.

Creates a disposable saved persona to verify password re-entry after QUIT.
"""
import asyncio
import argparse
import json
import secrets
import string

from aiohttp.test_utils import TestServer
from playwright.async_api import async_playwright

from server.gateway import create_app
from tests.browser_smoke import wait_display, wait_prompt


async def main(style):
    async with TestServer(create_app()) as server, async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            page = await browser.new_page()
            await page.add_init_script(
                f"localStorage.setItem('mud86-terminal-style', {json.dumps(style)});"
                "localStorage.setItem('mud86-chat-mode', 'true')")
            await page.goto(str(server.make_url('/')))
            await page.evaluate('terminalReady')
            await page.evaluate("""() => {
                window.gameOutput = '';
                socket.addEventListener('message', event => gameOutput += event.data);
            }""")
            command = page.get_by_label('Command', exact=True)

            async def expect(text):
                await page.wait_for_function(
                    "text => Array.from(document.querySelectorAll('#chat-output > div'), row => row.textContent).join(' ').includes(text)",
                    arg=text, timeout=30000)

            async def submit(text):
                await command.fill(text)
                await command.press('Enter')

            name = 'Chat' + ''.join(secrets.choice(string.ascii_lowercase) for _ in range(4))
            password = 'chatproof'
            await expect('By what name shall I call you?')
            assert await page.locator('#terminal-style').input_value() == style
            assert await page.locator('#chat-mode').is_checked()
            assert not await page.locator('#chat-form').evaluate("el => el.classList.contains('docked')")
            await submit(name)
            await expect('What sex do you wish to be?')
            await submit('m')
            await expect('letters, please.')
            assert await command.get_attribute('type') == 'password'
            await submit(password)
            await expect('Hello, ' + name)
            await wait_prompt(page)
            assert await command.get_attribute('type') == 'text'
            await command.fill('whox')
            await command.press('Backspace')
            await page.evaluate("gameOutput = ''")
            await command.press('Enter')
            await wait_prompt(page)
            await expect(name + ' is playing')
            for text in ('info', 'save'):
                await page.evaluate("gameOutput = ''")
                await submit(text)
                await wait_prompt(page)
            assert password not in await page.locator('#chat-output').inner_text()
            assert await page.locator('#chat-output > div').count() > 30
            await page.wait_for_function("document.getElementById('chat-form').classList.contains('docked')")
            await page.evaluate('window.scrollTo(0, 0)')
            await page.wait_for_function("!document.getElementById('chat-form').classList.contains('docked')")
            await page.evaluate('window.scrollTo(0, document.documentElement.scrollHeight)')
            await page.wait_for_function("document.getElementById('chat-form').classList.contains('docked')")
            assert abs((await page.locator('header').bounding_box())['y']) < 1
            await submit('quit')
            await page.wait_for_function('socket.readyState === WebSocket.CLOSED', timeout=30000)
            await page.wait_for_function("socket.readyState === WebSocket.OPEN && !document.getElementById('chat-command').disabled", timeout=30000)
            await expect('By what name shall I call you?')
            await submit(name)
            await expect("what's the password?")
            assert await command.get_attribute('type') == 'password'
            await submit(password)
            await expect('Hello again, ' + name)
            await wait_display(page)
            assert password not in await page.locator('#chat-output').inner_text()
            await page.get_by_role('button', name='Settings (Tab)', exact=True).click()
            assert await page.get_by_role('dialog', name='Settings', exact=True).is_visible()
            await page.keyboard.press('Escape')
            await page.wait_for_function("document.activeElement.id === 'chat-command'")
            await submit('quit')
            await page.wait_for_function('socket.readyState === WebSocket.CLOSED', timeout=30000)
            print(f'PASS: {style} Chat login, editing, INFO, adaptive input, pinned header, saved-password reconnect and Settings ({name})')
        finally:
            await browser.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--style', choices=('original', 'vt220', 'bbc0', 'bbc40'), default='original')
    asyncio.run(main(parser.parse_args().style))
