"""Check Chat input and transcript against the local original game in Chromium.

Creates a disposable saved persona to verify password re-entry after QUIT.
"""
import asyncio
import secrets
import string

from aiohttp.test_utils import TestServer
from playwright.async_api import async_playwright

from server.gateway import create_app
from tests.browser_smoke import wait_display, wait_prompt


async def main():
    async with TestServer(create_app()) as server, async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            page = await browser.new_page()
            await page.add_init_script("localStorage.setItem('mud86-terminal-style', 'chat')")
            await page.goto(str(server.make_url('/')))
            await page.evaluate('terminalReady')
            await page.evaluate("""() => {
                window.gameOutput = '';
                socket.addEventListener('message', event => gameOutput += event.data);
            }""")
            command = page.get_by_label('Command', exact=True)

            async def expect(text):
                await page.wait_for_function(
                    "text => document.getElementById('chat-output').textContent.includes(text)",
                    arg=text, timeout=30000)

            async def submit(text):
                await command.fill(text)
                await command.press('Enter')

            name = 'Chat' + ''.join(secrets.choice(string.ascii_lowercase) for _ in range(4))
            password = 'chatproof'
            await expect('By what name shall I call you?')
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
            await command.press('Tab')
            assert await page.get_by_role('dialog', name='Settings', exact=True).is_visible()
            await page.keyboard.press('Escape')
            assert await page.evaluate("document.activeElement.id === 'chat-command'")
            await submit('quit')
            await page.wait_for_function('socket.readyState === WebSocket.CLOSED', timeout=30000)
            print(f'PASS: Chat login, local editing, INFO, expanding transcript, saved-password reconnect and Settings ({name})')
        finally:
            await browser.close()


if __name__ == '__main__':
    asyncio.run(main())
