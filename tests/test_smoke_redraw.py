import unittest
from aiohttp.test_utils import TestServer
from playwright.async_api import async_playwright
from server.gateway import create_app
from tests.browser_smoke import wait_terminal_line

REDRAW='\r\x1b[C\x1b[C\x1b[C\x1b[K'
WITNESSED=('Uizywpnb has just arrived.\r\n \r\n\r\n*wx'+REDRAW+'wx'
           '\r\n\r\nA playful rabbit snuffles round your feet. \r\n\r\n \r\n\r\n*'+REDRAW+'wx')


class SmokeRedrawTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.server=TestServer(create_app())
        await self.server.start_server()
        self.playwright=await async_playwright().start()
        self.browser=await self.playwright.chromium.launch()
        self.page=await self.browser.new_page()
        await self.page.add_init_script('''window.sent=[]; window.gameOutput='';
            window.WebSocket=class {static OPEN=1; constructor(){this.readyState=1;}
            send(data){sent.push(data);} close(){this.readyState=3;}};''')
        await self.page.goto(str(self.server.make_url('/')))
        await self.page.evaluate('terminalReady')
        await self.page.evaluate('socket.onopen()')

    async def asyncTearDown(self):
        await self.browser.close()
        await self.playwright.stop()
        await self.server.close()

    async def output(self,text):
        await self.page.evaluate("text => {gameOutput+=text; return new Promise(resolve=>terminal.write(text,resolve));}",text)

    async def test_witnessed_arrival_redraw_keeps_editable_command_despite_prompt_padding(self):
        await self.output(WITNESSED)
        await wait_terminal_line(self.page,'*wx','witnessed redraw',timeout=300)
        await self.page.locator('.xterm-helper-textarea').focus()
        await self.page.keyboard.press('Backspace')
        await self.page.wait_for_function("sent.join('')==='\\x7f'")
        await self.output('\b \b')
        await wait_terminal_line(self.page,'*w','erase',timeout=300)
        await self.page.keyboard.type('ho')
        await self.page.wait_for_function("sent.join('')==='\\x7fho'")
        await self.output('ho')
        await wait_terminal_line(self.page,'*who','completed edit',timeout=300)
        await self.page.keyboard.press('Enter')
        await self.page.wait_for_function("sent.join('')==='\\x7fho\\r'")

    async def test_arbitrary_padding_or_wrong_command_is_still_rejected(self):
        for output in ('*  wx','*'+REDRAW+'wy','*'+REDRAW+'wxjunk'):
            await self.page.evaluate("terminal.reset(); gameOutput=''")
            await self.output(output)
            with self.assertRaises(AssertionError):
                await wait_terminal_line(self.page,'*wx','invalid',timeout=100)
