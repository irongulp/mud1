"""Browser transport tests; MUD86_TEST_BROWSER selects an engine (default chromium)."""
import os
import unittest
from pathlib import Path

from aiohttp.test_utils import TestServer
from playwright.async_api import async_playwright

from server.gateway import create_app

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(ROOT / "runtime/browsers"))


class TerminalTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.server = TestServer(create_app())
        await self.server.start_server()
        self.playwright = await async_playwright().start()
        browser_type = getattr(self.playwright, os.environ.get('MUD86_TEST_BROWSER', 'chromium'))
        self.browser = await browser_type.launch()
        self.page = await self.browser.new_page()
        await self.page.clock.install()
        await self.page.add_init_script("""(() => {
            window.sent = [];
            window.connections = [];
            window.WebSocket = class {
                static OPEN = 1; static CLOSING = 2;
                constructor(url) { this.readyState = 1; this.url = url; connections.push(this); }
                send(data) { sent.push(data); }
                close() { this.readyState = 3; this.onclose({reason: '', code: 1000}); }
            };
        })();""")
        await self.page.goto(str(self.server.make_url("/")))
        await self.page.clock.pause_at("2030-01-01T00:00:00Z")

    async def asyncTearDown(self):
        await self.browser.close()
        await self.playwright.stop()
        await self.server.close()

    async def connect(self):
        await self.page.evaluate('terminalReady')
        await self.page.evaluate("socket.onopen()")

    async def open_controls(self):
        await self.page.evaluate('terminalReady.then(focusInput)')
        await self.page.keyboard.press('Tab')

    async def initial_style(self, style):
        await self.page.evaluate("style => localStorage.setItem('mud86-terminal-style', style)", style)
        await self.page.reload()
        await self.page.evaluate('terminalReady')

    async def initial_chat(self, style='original'):
        await self.page.evaluate("localStorage.setItem('mud86-chat-mode', 'true')")
        await self.initial_style(style)

    async def test_terminal_input_discourages_login_autofill_across_reconnect(self):
        await self.connect()
        entry = self.page.locator('.xterm-helper-textarea')
        self.assertEqual(await entry.get_attribute('autocomplete'), 'new-password')
        await self.page.locator('#terminal').click()
        await self.page.keyboard.type('look')
        await self.page.keyboard.press('Enter')
        await self.page.clock.run_for(100)
        self.assertEqual(await self.page.evaluate("sent.join('')"), 'look\r')
        await self.page.evaluate('socket.close()')
        await self.page.clock.run_for(1500)
        await self.page.evaluate('socket.onopen(); sent = []')
        self.assertEqual(await entry.get_attribute('autocomplete'), 'new-password')
        await self.page.locator('#terminal').click()
        await self.page.keyboard.type('who')
        await self.page.keyboard.press('Enter')
        await self.page.clock.run_for(100)
        self.assertEqual(await self.page.evaluate("sent.join('')"), 'who\r')

    async def test_controls_tabs_default_content_and_session_preservation(self):
        await self.connect()
        await self.open_controls()
        tabs = self.page.get_by_role('tab')
        self.assertEqual(await tabs.all_text_contents(), ['Settings', 'About', 'Licences', 'Links'])
        self.assertEqual(await self.page.get_by_role('tab', name='Settings', exact=True).get_attribute('aria-selected'), 'true')
        await self.page.get_by_label('Connection speed').select_option('1200-75')
        await self.page.get_by_role('tab', name='About', exact=True).click()
        about = self.page.get_by_role('tabpanel', name='About', exact=True)
        text = await about.inner_text()
        for expected in ('1978', 'University of Essex', 'Roy Trubshaw', 'Richard Bartle',
                         '1986', 'BCPL', 'MACRO-10', 'TOPS-10', 'SIMH', 'Python',
                         'Tim Rogers', 'OpenCode', 'GPT-6 Astra'):
            self.assertIn(expected, text)
        self.assertFalse(await self.page.get_by_label('Connection speed').is_visible())
        self.assertFalse(await self.page.get_by_role('button', name='Send Tab to game').is_visible())
        await self.page.get_by_role('button', name='Return to game', exact=True).click()
        await self.open_controls()
        self.assertTrue(await self.page.get_by_role('tabpanel', name='Settings', exact=True).is_visible())
        self.assertEqual(await self.page.get_by_label('Connection speed').input_value(), '1200-75')
        self.assertEqual(await self.page.evaluate('[connections.length, sent.length]'), [1, 0])

    async def test_controls_links_order_and_small_screen_scrolling(self):
        await self.page.set_viewport_size({'width': 360, 'height': 480})
        await self.open_controls()
        await self.page.get_by_role('tab', name='Links', exact=True).click()
        links = self.page.get_by_role('tabpanel', name='Links', exact=True).get_by_role('link')
        self.assertNotIn('Game history, source code and restoration resources.',
                         await self.page.get_by_role('tabpanel', name='Links', exact=True).inner_text())
        expected = [
            'https://mud.co.uk/richard/',
            'https://github.com/irongulp/mud1',
            'https://en.wikipedia.org/wiki/MUD1',
            'https://en.wikipedia.org/wiki/PDP-10',
            'https://www.quentin.org.uk/2018/12/08/building-mud-86-from-source/',
            'https://www.cl.cam.ac.uk/~mr10/bcpl4raspi.pdf',
            'https://mud.co.uk/muse/speke.htm',
            'https://steubentech.com/~talon/pdp10/readme.txt',
            'https://www.filfre.net/misc/TOPS-10.txt',
            'https://avanthar.com/healyzh/decemulation/TOPS-10_tips.html',
            'https://github.com/irongulp/mud1/blob/main/MUDDL%20-%20Multi%20User%20Dungeon%20Definition%20Language.pdf',
        ]
        self.assertEqual(await links.evaluate_all('(links) => links.map(link => link.href)'), expected)
        self.assertIn('Richard Bartle', await links.first.inner_text())
        self.assertTrue(await links.evaluate_all("links => links.every(link => link.target === '_blank' && link.relList.contains('noopener'))"))
        await self.page.locator('.controls-content').evaluate('(element) => element.scrollTop = element.scrollHeight')
        for locator in (self.page.locator('#controls'), self.page.get_by_role('tablist'),
                        self.page.get_by_role('button', name='Return to game', exact=True)):
            box = await locator.bounding_box()
            self.assertGreaterEqual(box['x'], 0)
            self.assertGreaterEqual(box['y'], 0)
            self.assertLessEqual(box['x'] + box['width'], 360)
            self.assertLessEqual(box['y'] + box['height'], 480)

    async def test_controls_tabs_form_a_continuous_strip_joined_to_the_panel(self):
        for style in ('original', 'mda'):
            await self.initial_style(style)
            await self.open_controls()
            await self.page.get_by_role('tab', name='About', exact=True).click()
            appearance = await self.page.evaluate("""() => {
                const strip = document.querySelector('.controls-tabs');
                const selected = strip.querySelector('[aria-selected="true"]');
                const inactive = strip.querySelector('[aria-selected="false"]');
                return {
                    baseline: getComputedStyle(strip).borderBottomWidth,
                    activeBottom: getComputedStyle(selected).borderBottomColor,
                    surface: getComputedStyle(controls).backgroundColor,
                    corner: getComputedStyle(selected).borderBottomLeftRadius,
                    inactiveBackground: getComputedStyle(inactive).backgroundColor,
                    gap: selected.getBoundingClientRect().left - inactive.getBoundingClientRect().right
                };
            }""")
            self.assertEqual(appearance['baseline'], '1px')
            self.assertEqual(appearance['activeBottom'], appearance['surface'])
            self.assertEqual(appearance['corner'], '0px')
            self.assertEqual(appearance['inactiveBackground'], 'rgba(0, 0, 0, 0)')
            self.assertEqual(appearance['gap'], 0)

    async def test_controls_tabs_have_no_extra_focus_highlight(self):
        await self.open_controls()
        selected = self.page.get_by_role('tab', name='Settings', exact=True)
        self.assertTrue(await selected.evaluate('(element) => element === document.activeElement'))
        self.assertEqual(await selected.evaluate('(element) => getComputedStyle(element).outlineStyle'), 'none')
        await self.page.keyboard.press('ArrowRight')
        selected = self.page.get_by_role('tab', name='About', exact=True)
        self.assertEqual(await selected.get_attribute('aria-selected'), 'true')
        self.assertTrue(await selected.evaluate('(element) => element === document.activeElement'))
        self.assertEqual(await selected.evaluate('(element) => getComputedStyle(element).outlineStyle'), 'none')

    async def test_controls_licence_section_order_and_inventory_link(self):
        await self.page.route('**/legal/third-party', lambda route: route.fulfill(status=404, body='Not found'))
        await self.open_controls()
        await self.page.get_by_role('tab', name='Licences', exact=True).click()
        panel = self.page.get_by_role('tabpanel', name='Licences', exact=True)
        await panel.get_by_text('GPL-3.0-only', exact=True).wait_for()
        self.assertEqual(await panel.locator('h2').all_text_contents(), [
            'Original MUD', 'Browser and restoration software', 'Fonts and other components',
            'Historical runtime permission review',
        ])
        inventory = panel.get_by_role('link', name='component inventory', exact=True)
        self.assertEqual(await inventory.get_attribute('href'),
                         'https://github.com/irongulp/mud1/blob/main/THIRD_PARTY.md')
        self.assertEqual(await inventory.get_attribute('target'), '_blank')
        self.assertIn('noopener', await inventory.get_attribute('rel'))

    async def test_controls_all_licence_links_work_without_legal_routes(self):
        await self.page.route('**/legal/**', lambda route: route.fulfill(status=404, body='Not found'))
        await self.open_controls()
        await self.page.get_by_role('tab', name='Licences', exact=True).click()
        panel = self.page.get_by_role('tabpanel', name='Licences', exact=True)
        await panel.get_by_text('GPL-3.0-only', exact=True).wait_for()
        documents = {
            'original copyright notices and custom not-for-profit terms': 'licenses/MUD1-NOTICE.txt',
            'GNU General Public License version 3': 'COPYING',
            'precise scope and exclusions': 'LICENSE',
            'MIT notice': 'web/vendor/LICENSE',
            'SIMH — full pinned upstream notice, including additional restrictions': 'licenses/SIMH.txt',
            'distribution status': 'NOTICE',
            'DEC agreement reference': 'licenses/DEC-HOBBYIST.txt',
            'BCPL review': 'licenses/BCPL-STATUS.md',
        }
        for label, path in documents.items():
            link = panel.get_by_role('link', name=label, exact=True)
            self.assertEqual(await link.get_attribute('href'),
                             'https://github.com/irongulp/mud1/blob/main/' + path)
            self.assertEqual(await link.get_attribute('target'), '_blank')
            self.assertIn('noopener', await link.get_attribute('rel'))
        for href in await panel.locator('a').evaluate_all('links => links.map(link => link.getAttribute("href"))'):
            if href.startswith('/'):
                self.assertTrue(href.startswith('/static/'), href)
                response = await self.page.request.get(str(self.server.make_url(href)))
                self.assertEqual(response.status, 200, href)

    async def test_controls_licences_inline_and_failed_load_recovery(self):
        requests = []
        self.page.on('request', lambda request: requests.append(request.url) if request.url.endswith('/static/legal.html') else None)
        await self.open_controls()
        await self.page.route('**/static/legal.html', lambda route: route.fulfill(status=503, body='Unavailable'))
        await self.page.get_by_role('tab', name='Licences', exact=True).click()
        panel = self.page.get_by_role('tabpanel', name='Licences', exact=True)
        await panel.get_by_text('The notices could not be loaded.').wait_for()
        self.assertEqual(await panel.get_by_role('link', name='Open the licence page').get_attribute('href'), '/static/legal.html')
        await self.page.unroute('**/static/legal.html')
        await self.page.get_by_role('tab', name='Settings', exact=True).click()
        await self.page.get_by_role('tab', name='Licences', exact=True).click()
        await panel.get_by_text('GPL-3.0-only', exact=True).wait_for()
        text = await panel.inner_text()
        self.assertIn('no warranty', text)
        self.assertIn('custom not-for-profit terms', text)
        self.assertIn('Redistribution review is incomplete.', text)
        self.assertTrue(await panel.locator('a').evaluate_all("links => links.every(link => link.target === '_blank' && link.relList.contains('noopener'))"))
        await self.page.get_by_role('tab', name='About', exact=True).click()
        await self.page.get_by_role('tab', name='Licences', exact=True).click()
        self.assertEqual(len(requests), 2, 'A successfully loaded notice panel should be reused')

    async def test_controls_licences_work_without_the_new_legal_route(self):
        await self.page.route('**/legal', lambda route: route.fulfill(status=404, body='Not found'))
        await self.open_controls()
        await self.page.get_by_role('tab', name='Licences', exact=True).click()
        await self.page.wait_for_function("""() => {
            const text = document.getElementById('licence-notices').textContent;
            return text.includes('GPL-3.0-only') || text.includes('could not be loaded');
        }""")
        panel = self.page.get_by_role('tabpanel', name='Licences', exact=True)
        self.assertIn('GPL-3.0-only', await panel.inner_text())
        self.assertFalse(await self.page.locator('#licence-fallback').is_visible())

    async def test_controls_keyboard_tabs_keep_tab_to_close_and_chat_draft(self):
        await self.initial_chat()
        await self.connect()
        command = self.page.get_by_label('Command', exact=True)
        await command.fill('unfinished')
        await self.page.clock.run_for(200)
        await self.open_controls()
        for key, name in (('ArrowRight', 'About'), ('End', 'Links'),
                          ('Home', 'Settings'), ('ArrowLeft', 'Links')):
            await self.page.keyboard.press(key)
            tab = self.page.get_by_role('tab', name=name, exact=True)
            self.assertEqual(await tab.get_attribute('aria-selected'), 'true')
            self.assertTrue(await tab.evaluate('(element) => element === document.activeElement'))
        await self.page.keyboard.press('Tab')
        self.assertFalse(await self.page.locator('#controls').is_visible())
        self.assertTrue(await command.evaluate('(element) => element === document.activeElement'))
        self.assertEqual(await command.input_value(), 'unfinished')
        for name in ('Settings', 'About', 'Licences', 'Links'):
            await self.open_controls()
            await self.page.get_by_role('tab', name=name, exact=True).click()
            await self.page.keyboard.press('Tab')
            self.assertFalse(await self.page.locator('#controls').is_visible())
        await self.open_controls()
        await self.page.get_by_role('tab', name='About', exact=True).click()
        await self.page.keyboard.press('Escape')
        self.assertFalse(await self.page.locator('#controls').is_visible())
        self.assertEqual(await command.input_value(), 'unfinished')
        self.assertEqual(await self.page.evaluate('[connections.length, sent.length]'), [1, 0])

    async def test_chat_paces_typing_then_sends_one_complete_line(self):
        await self.initial_chat()
        await self.connect()
        await self.open_controls()
        await self.page.get_by_label('Connection speed').select_option('1200-75')
        await self.page.keyboard.press('Escape')
        command = self.page.get_by_label('Command', exact=True)
        await command.press_sequentially('abcdefghij')
        self.assertEqual(await command.input_value(), '')
        await self.page.clock.run_for(400)
        self.assertEqual(await command.input_value(), 'abc')
        self.assertEqual(await self.page.evaluate('sent'), [])
        await command.press('Enter')
        await self.page.clock.run_for(800)
        self.assertEqual(await command.input_value(), 'abcdefghi')
        self.assertEqual(await self.page.evaluate('sent'), [])
        await self.page.clock.run_for(200)
        self.assertEqual(await self.page.evaluate('sent'), ['abcdefghij\r'])
        self.assertEqual(await command.input_value(), '')
        # When typing has already caught up, Enter has no additional baud wait.
        await command.press_sequentially('look')
        await self.page.clock.run_for(600)
        self.assertEqual(await command.input_value(), 'look')
        await command.press('Enter')
        self.assertEqual(await self.page.evaluate('sent'), ['abcdefghij\r', 'look\r'])

    async def test_chat_paced_paste_editing_typeahead_and_disconnect(self):
        await self.initial_chat()
        await self.connect()
        await self.open_controls()
        await self.page.get_by_label('Connection speed').select_option('1200-75')
        await self.page.keyboard.press('Escape')
        command = self.page.get_by_label('Command', exact=True)
        await command.evaluate("""el => {
            const clipboardData = new DataTransfer();
            clipboardData.setData('text/plain', 'lookx');
            el.dispatchEvent(new ClipboardEvent('paste', {bubbles: true, cancelable: true, clipboardData}));
        }""")
        await command.press('Backspace')
        await command.press('Enter')
        await command.press_sequentially('who')
        await command.press('Enter')
        await self.page.clock.run_for(400)
        self.assertEqual(await command.input_value(), 'loo')
        self.assertEqual(await self.page.evaluate('sent'), [])
        await self.page.clock.run_for(900)
        self.assertEqual(await self.page.evaluate('sent'), ['look\r', 'who\r'])
        await self.page.evaluate("socket.onmessage({data: \"This persona already exists - what's the password?\\r\\n*\"})")
        await command.press_sequentially('secret')
        await command.press('Enter')
        await self.page.clock.run_for(300)
        self.assertEqual(await command.get_attribute('type'), 'password')
        self.assertEqual(await command.input_value(), 'se')
        await self.page.evaluate('socket.close()')
        await self.page.clock.run_for(1600)
        await self.page.evaluate('socket.onopen()')
        await self.page.clock.run_for(1000)
        self.assertEqual(await command.input_value(), '')
        self.assertEqual(await self.page.evaluate('sent'), ['look\r', 'who\r'])

    async def test_chat_paced_selection_and_speed_change(self):
        await self.initial_chat()
        await self.connect()
        await self.open_controls()
        await self.page.get_by_label('Connection speed').select_option('300-300')
        await self.page.keyboard.press('Escape')
        command = self.page.get_by_label('Command', exact=True)
        await command.press_sequentially('say hello')
        await self.page.clock.run_for(400)
        await command.evaluate('el => el.setSelectionRange(4, 9)')
        await command.press_sequentially('there')
        await command.press('Enter')
        await self.page.clock.run_for(200)
        self.assertEqual(await self.page.evaluate('sent'), ['say there\r'])
        await command.press_sequentially('obsolete')
        await command.press('ControlOrMeta+a')
        await command.press_sequentially('look')
        await command.press('Enter')
        await self.open_controls()
        await self.page.get_by_label('Connection speed').select_option('9600-9600')
        await self.page.keyboard.press('Escape')
        await self.page.clock.run_for(100)
        self.assertEqual(await self.page.evaluate('sent'), ['say there\r', 'look\r'])

    async def test_chat_selection_replacement_while_typing_is_pending(self):
        await self.initial_chat()
        await self.connect()
        await self.open_controls()
        await self.page.get_by_label('Connection speed').select_option('1200-75')
        await self.page.keyboard.press('Escape')
        command = self.page.get_by_label('Command', exact=True)
        await command.press_sequentially('abcdef')
        await self.page.clock.run_for(400)
        self.assertEqual(await command.input_value(), 'abc')
        await command.evaluate('el => el.setSelectionRange(1, 3)')
        await command.press_sequentially('XY')
        await command.press('Enter')
        await self.page.clock.run_for(800)
        self.assertEqual(await self.page.evaluate('sent'), ['aXYdef\r'])

    async def copy_chat(self, start=None, end=None, backwards=False):
        return await self.page.evaluate("""({start, end, backwards}) => {
            document.activeElement.blur();
            const output = document.getElementById('chat-output');
            const point = position => {
                const row = output.children[position[0]];
                return [row.firstChild || row, position[1]];
            };
            const a = start ? point(start) : [output, 0];
            const b = end ? point(end) : [output, output.childNodes.length];
            const selection = getSelection();
            selection.removeAllRanges();
            selection.setBaseAndExtent(...(backwards ? b : a), ...(backwards ? a : b));
            const data = new DataTransfer();
            const event = new ClipboardEvent('copy', {bubbles: true, cancelable: true, clipboardData: data});
            output.dispatchEvent(event);
            return {text: data.getData('text/plain'), handled: event.defaultPrevented};
        }""", dict(start=start, end=end, backwards=backwards))

    async def test_chat_copy_preserves_rows_blank_lines_and_indentation(self):
        await self.initial_chat()
        await self.connect()
        text = '*who\r\nAlice is playing\r\nBob is playing\r\n\r\n  Indented text\r\n*'
        await self.page.evaluate('data => socket.onmessage({data})', text)
        await self.page.clock.run_for(300)
        copied = await self.copy_chat()
        self.assertEqual(copied, dict(text=text.replace('\r\n', '\n'), handled=True))
        # Exercise an actual browser keyboard copy as well as the event contract
        # used by keyboard shortcuts and the context menu alike.
        await self.page.context.grant_permissions(['clipboard-read', 'clipboard-write'])
        await self.page.keyboard.press('ControlOrMeta+c')
        self.assertEqual(await self.page.evaluate('navigator.clipboard.readText()'), copied['text'])
        self.assertEqual(await self.page.evaluate('sent'), [])

    async def test_chat_copy_partial_and_backwards_selections(self):
        await self.initial_chat()
        await self.connect()
        await self.page.evaluate("socket.onmessage({data: '*who\\r\\nAlice is playing\\r\\n\\r\\n  Indented text'})")
        await self.page.clock.run_for(300)
        for backwards in (False, True):
            self.assertEqual((await self.copy_chat([0, 2], [3, 6], backwards))['text'],
                             'ho\nAlice is playing\n\n  Inde')
        self.assertEqual((await self.copy_chat([1, 2], [1, 5]))['text'], 'ice')
        self.assertEqual((await self.copy_chat([1, 16], [3, 0]))['text'], '\n\n')
        self.assertFalse((await self.copy_chat([1, 2], [1, 2]))['handled'])
        handled = await self.page.evaluate("""() => {
            const range = document.createRange();
            range.setStart(document.querySelector('h1').firstChild, 0);
            range.setEnd(document.getElementById('chat-output').children[1].firstChild, 3);
            getSelection().removeAllRanges();
            getSelection().addRange(range);
            const event = new ClipboardEvent('copy', {cancelable: true, clipboardData: new DataTransfer()});
            document.dispatchEvent(event);
            return event.defaultPrevented;
        }""")
        self.assertFalse(handled, 'Mixed page/transcript selections should retain native copying')

    async def test_chat_copy_mode7_visible_wraps_and_excludes_draft(self):
        await self.initial_chat('bbc40')
        await self.connect()
        await self.page.evaluate("socket.onmessage({data: 'A sentence with thirty characters: elephant walks past.\\r\\n*'})")
        await self.page.clock.run_for(300)
        await self.page.locator('#chat-command').fill('unsent draft')
        await self.page.clock.run_for(50)
        self.assertEqual((await self.copy_chat())['text'],
                         'A sentence with thirty characters:\nelephant walks past.\n*')
        await self.page.locator('#chat-command').evaluate("el => { el.focus(); el.select(); }")
        handled = await self.page.locator('#chat-command').evaluate("""el => {
            const event = new ClipboardEvent('copy', {bubbles: true, cancelable: true, clipboardData: new DataTransfer()});
            el.dispatchEvent(event);
            return event.defaultPrevented;
        }""")
        self.assertFalse(handled)

    async def test_settings_shortcut_opens_modal_without_sending_tab(self):
        for chat_mode in (False, True):
            if chat_mode:
                await self.initial_chat()
            await self.connect()
            shortcut = self.page.get_by_role('button', name='Settings (Tab)', exact=True)
            self.assertEqual(await shortcut.inner_text(), 'Tab')
            self.assertEqual(await shortcut.locator('svg').count(), 1)
            self.assertTrue(await shortcut.evaluate("el => el.closest('header') !== null"))
            header = await self.page.locator('header').bounding_box()
            button = await shortcut.bounding_box()
            self.assertAlmostEqual(button['x'] + button['width'], header['x'] + header['width'], delta=1)
            self.assertAlmostEqual(button['y'], (await self.page.locator('h1').bounding_box())['y'], delta=1)
            await shortcut.click()
            self.assertTrue(await self.page.get_by_role('dialog', name='Settings', exact=True).is_visible())
            await self.page.keyboard.press('Tab')
            await self.page.clock.run_for(50)
            self.assertFalse(await self.page.locator('#controls').is_visible())
            self.assertTrue(await self.page.evaluate(
                "document.activeElement.id === 'chat-command'" if chat_mode else
                "document.activeElement.classList.contains('xterm-helper-textarea')"))
            self.assertEqual(await self.page.evaluate('sent'), [])

    async def test_docked_command_joins_display_frame_at_both_widths(self):
        for style in ('original', 'bbc40'):
            await self.initial_chat(style)
            await self.connect()
            await self.page.evaluate("socket.onmessage({data: ('Line\\r\\n').repeat(80) + '*'})")
            await self.page.clock.run_for(1000)
            self.assertTrue(await self.page.locator('#chat-form').evaluate("el => el.classList.contains('docked')"))
            self.assertEqual(await self.page.locator('#chat-form button').count(), 0)
            frame = await self.page.locator('main').bounding_box()
            form = await self.page.locator('#chat-form').bounding_box()
            field = await self.page.locator('#chat-command').bounding_box()
            self.assertGreaterEqual(form['height'] - field['height'], 12)
            for property in ('x', 'width'):
                self.assertAlmostEqual(form[property], frame[property], delta=1)
            self.assertAlmostEqual(form['y'] + form['height'], frame['y'] + frame['height'], delta=1)
            self.assertEqual(await self.page.locator('#chat-command').evaluate(
                "el => [getComputedStyle(el).borderTopWidth, getComputedStyle(el).outlineStyle]"), ['0px', 'none'])
            self.assertEqual(await self.page.locator('#chat-form').evaluate(
                "el => getComputedStyle(el).borderColor"), await self.page.locator('main').evaluate(
                "el => getComputedStyle(el).borderColor"))
            await self.page.get_by_label('Command', exact=True).fill('look')
            await self.page.get_by_label('Command', exact=True).press('Enter')
            await self.page.clock.run_for(100)
            self.assertEqual(await self.page.evaluate("sent.join('')"), 'look\r')

    async def test_docked_prompt_moves_without_losing_history_or_draft(self):
        for style in ('original', 'bbc40'):
            await self.initial_chat(style)
            await self.connect()
            await self.page.evaluate("socket.onmessage({data: ('Line\\r\\n').repeat(80) + '*'})")
            await self.page.clock.run_for(1000)
            self.assertEqual(await self.page.locator('#chat-prompt').count(), 1)
            command = self.page.get_by_label('Command', exact=True)
            await command.fill('draft')
            await self.page.clock.run_for(50)
            await command.evaluate('el => el.setSelectionRange(1, 4)')
            for prompt in ('*', '----*', '>', '"', '(*)', '(----*)', '(>)', '(----")', '.'):
                await self.page.evaluate('data => socket.onmessage({data})', '\r\x1b[K' + prompt)
                await self.page.clock.run_for(100)
                self.assertEqual(await self.page.locator('#chat-prompt').inner_text(), prompt)
                self.assertEqual(await self.page.locator('#chat-output > div').last.inner_text(), '')
                self.assertEqual(await command.input_value(), 'draft')
                self.assertEqual(await command.evaluate('el => [el.selectionStart, el.selectionEnd]'), [1, 4])
                await self.page.evaluate("socket.onmessage({data: 'look\\r\\nA room.\\r\\n*'})")
                await self.page.clock.run_for(100)
                self.assertIn(prompt + 'look', await self.page.locator('#chat-output > div').all_text_contents())
            # Non-prompt output must stay in the transcript, even if it starts '*'.
            await self.page.evaluate("socket.onmessage({data: 'This is text\\r\\nWhat is your present password?\\r\\n*'})")
            await self.page.clock.run_for(200)
            self.assertEqual(await command.get_attribute('type'), 'password')
            self.assertIn('*This is text', await self.page.locator('#chat-output > div').all_text_contents())
            await self.page.clock.resume()
            await self.page.evaluate('scrollTo(0, 0)')
            await self.page.wait_for_function("!document.getElementById('chat-form').classList.contains('docked')")
            self.assertEqual(await self.page.locator('#chat-output > div').last.inner_text(), '*')
            self.assertFalse(await self.page.locator('#chat-prompt').is_visible())
            await self.page.evaluate('scrollTo(0, document.documentElement.scrollHeight)')
            await self.page.wait_for_function("document.getElementById('chat-form').classList.contains('docked')")
            self.assertEqual(await self.page.locator('#chat-prompt').inner_text(), '*')
            self.assertEqual(await self.page.locator('#chat-output > div').last.inner_text(), '')
            self.assertEqual(await command.input_value(), 'draft')
            self.assertEqual(await command.get_attribute('type'), 'password')
            self.assertEqual(await self.page.evaluate('sent'), [])

    async def test_chat_leaves_password_element_behind_without_losing_editor_state(self):
        await self.initial_chat()
        await self.connect()
        command = self.page.get_by_label('Command', exact=True)
        await self.page.evaluate("socket.onmessage({data: 'What is your present password?\\r\\n*'})")
        await self.page.clock.run_for(200)
        await command.fill('lookx')
        await self.page.clock.run_for(100)
        await command.evaluate("input => { window.passwordInput = input; input.setSelectionRange(0, 4); }")
        await self.page.evaluate("socket.onmessage({data: 'Your password will be updated\\r\\n*'})")
        self.assertTrue(await command.evaluate('input => input !== window.passwordInput'))
        self.assertEqual(await command.get_attribute('type'), 'text')
        self.assertEqual(await command.input_value(), 'lookx')
        self.assertEqual(await command.evaluate('input => [input.selectionStart, input.selectionEnd]'), [0, 4])
        self.assertTrue(await command.evaluate('input => input === document.activeElement'))
        await command.press('i')
        await self.page.clock.run_for(100)
        await command.press('Enter')
        await self.page.clock.run_for(100)
        self.assertEqual(await self.page.evaluate("sent.join('')"), 'ix\r')

        # Pending paced edits must also follow the new element.
        await self.page.evaluate("chat.setBaud(75); socket.onmessage({data: 'What is your present password?\\r\\n*'})")
        await command.evaluate('input => window.passwordInput = input')
        await command.fill('queued')
        await command.press('Tab')
        focused_control = await self.page.evaluate('document.activeElement.id')
        await self.page.evaluate("socket.onmessage({data: 'Hello again, Tester!\\r\\n*'})")
        self.assertTrue(await command.evaluate('input => input !== window.passwordInput'))
        self.assertEqual(await self.page.evaluate('document.activeElement.id'), focused_control)
        await self.page.clock.run_for(1000)
        self.assertEqual(await command.input_value(), 'queued')
        await self.page.keyboard.press('Tab')
        await command.press('Enter')
        self.assertEqual(await self.page.evaluate("sent.join('')"), 'ix\rqueued\r')

        # A disconnect at a password prompt must not recycle that element either.
        await self.page.evaluate("socket.onmessage({data: 'What is your present password?\\r\\n*'})")
        await command.evaluate('input => window.passwordInput = input')
        await self.page.evaluate('socket.close()')
        self.assertTrue(await command.evaluate('input => input !== window.passwordInput'))
        self.assertEqual(await command.get_attribute('type'), 'text')
        self.assertEqual(await command.input_value(), '')
        self.assertTrue(await command.is_disabled())

    async def test_chat_submission_passwords_settings_and_reconnect(self):
        await self.initial_chat()
        await self.connect()
        self.assertEqual(await self.page.locator('#terminal-style option').all_text_contents(),
                         ['Default', 'Computer Centre on Square 2', 'DEC VT52', 'IBM PC MDA',
                          'IBM PC CGA', 'BBC Micro Mode 0', 'BBC Micro Mode 7'])
        command = self.page.get_by_label('Command', exact=True)
        self.assertEqual(await self.page.locator('#chat-form').get_attribute('autocomplete'), 'off')
        self.assertEqual(await command.get_attribute('autocomplete'), 'new-password')
        await self.page.evaluate("socket.onmessage({data: 'Welcome! By what name shall I call you?\\r\\n*'})")
        await self.page.clock.run_for(200)
        await command.fill('lookx')
        await self.page.clock.run_for(100)
        await command.press('Backspace')
        self.assertEqual(await self.page.evaluate('sent'), [])
        await command.press('Enter')
        await self.page.clock.run_for(100)
        self.assertEqual(await self.page.evaluate("sent.join('')"), 'look\r')
        await self.page.evaluate("socket.onmessage({data: \"This persona already exists - what's the pass\"})")
        await self.page.evaluate("socket.onmessage({data: 'word?\\r\\n*'})")
        await self.page.clock.run_for(200)
        self.assertEqual(await command.get_attribute('type'), 'password')
        await command.fill('secret')
        self.assertEqual(await command.get_attribute('autocomplete'), 'new-password')
        await command.press('Enter')
        await self.page.clock.run_for(100)
        self.assertNotIn('secret', await self.page.locator('#chat-output').inner_text())
        await self.page.evaluate("socket.onmessage({data: 'Yes!\\r\\nHello, Tester!\\r\\n*'})")
        await self.page.clock.run_for(200)
        self.assertEqual(await command.get_attribute('type'), 'text')
        await self.page.evaluate("socket.onmessage({data: 'What is your present password?\\r\\n*'})")
        self.assertEqual(await command.get_attribute('type'), 'password')
        await self.page.evaluate("socket.onmessage({data: \"No, they're different - password remains unchanged.\\r\\n*\"})")
        self.assertEqual(await command.get_attribute('type'), 'text')
        await command.fill('draft')
        await command.press('Tab')
        self.assertTrue(await self.page.get_by_role('dialog', name='Settings', exact=True).is_visible())
        await self.page.keyboard.press('Tab')
        await self.page.clock.run_for(50)
        self.assertEqual(await self.page.evaluate('document.activeElement.id'), 'chat-command')
        self.assertEqual(await command.input_value(), 'draft')
        await self.page.evaluate('socket.close()')
        self.assertEqual(await command.input_value(), '')
        self.assertTrue(await command.is_disabled())
        await self.page.clock.run_for(1500)
        await self.page.evaluate("socket.onopen(); socket.onmessage({data: 'Fresh persona prompt*'})")
        await self.page.clock.run_for(200)
        self.assertIn('Welcome!', await self.page.locator('#chat-output').inner_text())
        self.assertIn('Fresh persona prompt*', await self.page.locator('#chat-output').inner_text())
        await command.click()
        self.assertEqual(await command.get_attribute('type'), 'text')
        self.assertEqual(await command.get_attribute('autocomplete'), 'new-password')
        self.assertTrue((await self.page.evaluate('socket.url')).endswith('?style=original'))

    async def test_chat_expands_to_80_columns_and_preserves_scrolling(self):
        await self.initial_chat()
        await self.connect()
        await self.page.evaluate("socket.onmessage({data: ('x'.repeat(80) + '\\r\\n').repeat(80) + '*wx\\b \\bho'})")
        await self.page.clock.run_for(8000)
        rows = self.page.locator('#chat-output > div')
        self.assertEqual(await rows.count(), 81)
        self.assertEqual(await rows.nth(0).inner_text(), 'x' * 80)
        self.assertEqual(await rows.nth(80).inner_text(), '*who')
        self.assertGreater((await self.page.locator('#chat-output').bounding_box())['height'], 1000)
        await self.page.evaluate('window.scrollTo(0, 0)')
        await self.page.clock.run_for(100)
        await self.page.evaluate("socket.onmessage({data: '\\r\\nNew output'})")
        await self.page.clock.run_for(100)
        self.assertEqual(await self.page.evaluate('window.scrollY'), 0)
        await self.page.evaluate('window.scrollTo(0, document.documentElement.scrollHeight)')
        await self.page.clock.run_for(100)
        await self.page.evaluate("socket.onmessage({data: '\\r\\nMore output'})")
        await self.page.clock.run_for(100)
        self.assertLessEqual(await self.page.evaluate(
            'document.documentElement.scrollHeight - innerHeight - scrollY'), 2)

    async def test_chat_switch_requires_confirmation_even_at_same_dimensions(self):
        await self.connect()
        await self.open_controls()
        await self.page.get_by_role('switch', name='Chat mode').check()
        self.assertTrue(await self.page.locator('#confirm-style').is_visible())
        await self.page.get_by_role('button', name='Cancel', exact=True).click()
        await self.page.clock.run_for(50)
        self.assertEqual(await self.page.locator('#terminal-style').input_value(), 'original')
        self.assertFalse(await self.page.get_by_role('switch', name='Chat mode').is_checked())
        self.assertIsNone(await self.page.evaluate("localStorage.getItem('mud86-chat-mode')"))

    async def test_chat_confirmed_switch_and_literal_tab(self):
        await self.connect()
        await self.open_controls()
        await self.page.get_by_role('switch', name='Chat mode').check()
        await self.page.get_by_role('button', name='Change settings and reconnect').click()
        await self.page.clock.run_for(50)
        self.assertEqual(await self.page.evaluate('Array.from(sent[0])'), list(b'restart'))
        self.assertFalse(await self.page.locator('#chat-form').is_visible())
        await self.page.evaluate('socket.close()')
        await self.page.clock.run_for(1500)
        await self.page.evaluate('socket.onopen(); sent = []')
        command = self.page.get_by_label('Command', exact=True)
        await command.fill('say one')
        await command.press('Tab')
        await self.page.get_by_role('button', name='Send Tab to game').click()
        await self.page.clock.run_for(50)
        self.assertEqual(await self.page.evaluate('sent'), [])
        await command.press('End')
        await command.press('Enter')
        await self.page.clock.run_for(100)
        self.assertEqual(await self.page.evaluate("sent.join('')"), 'say one\t\r')
        await command.press('Tab')
        await self.page.get_by_role('switch', name='Chat mode').uncheck()
        await self.page.get_by_role('button', name='Change settings and reconnect').click()
        await self.page.clock.run_for(50)
        await self.page.evaluate('socket.close()')
        await self.page.clock.run_for(1500)
        await self.page.evaluate('socket.onopen()')
        self.assertTrue(await self.page.locator('#terminal').is_visible())
        self.assertFalse(await self.page.locator('#chat-form').is_visible())

    async def test_legacy_chat_preference_migrates_to_independent_toggle(self):
        await self.initial_style('chat')
        self.assertEqual(await self.page.locator('#terminal-style').input_value(), 'original')
        self.assertTrue(await self.page.locator('#chat-mode').is_checked())
        self.assertEqual(await self.page.evaluate("localStorage.getItem('mud86-terminal-style')"), 'original')
        self.assertEqual(await self.page.evaluate("localStorage.getItem('mud86-chat-mode')"), 'true')

    async def test_chat_follows_each_style_and_mode7_wraps_words(self):
        for style, cols, font, size in [('original', 80, 'Menlo', 16), ('vt220', 80, 'GlassTTY', 20),
                                        ('bbc0', 80, 'BBCBitmap', 16), ('bbc40', 40, 'Bedstead', 20)]:
            await self.initial_chat(style)
            await self.connect()
            self.assertEqual(await self.page.locator('#terminal-style').input_value(), style)
            self.assertTrue(await self.page.locator('#chat-mode').is_checked())
            self.assertTrue((await self.page.evaluate('socket.url')).endswith('?style=' + style))
            self.assertEqual(await self.page.evaluate('terminal.cols'), cols)
            measured = await self.page.evaluate("""() => {
                const output = document.getElementById('chat-output');
                const style = getComputedStyle(output);
                const canvas = document.createElement('canvas').getContext('2d');
                canvas.font = style.font;
                return {font: style.fontFamily, size: style.fontSize,
                    columns: output.getBoundingClientRect().width / canvas.measureText('0').width};
            }""")
            self.assertIn(font, measured['font'])
            self.assertEqual(measured['size'], f'{size}px')
            self.assertAlmostEqual(measured['columns'], cols, delta=0.1)
        await self.page.evaluate("socket.onmessage({data: 'A sentence with thirty characters: elephant walks past.\\r\\n*'})")
        await self.page.clock.run_for(200)
        self.assertEqual(await self.page.locator('#chat-output > div').all_text_contents(),
                         ['A sentence with thirty characters:', 'elephant walks past.', '*'])
        await self.open_controls()
        await self.page.get_by_label('Terminal style').select_option('bbc0')
        await self.page.get_by_role('button', name='Cancel', exact=True).click()
        await self.page.clock.run_for(50)
        self.assertEqual(await self.page.locator('#terminal-style').input_value(), 'bbc40')
        self.assertTrue(await self.page.locator('#chat-mode').is_checked())
        await self.page.get_by_label('Terminal style').select_option('bbc0')
        await self.page.get_by_role('button', name='Change settings and reconnect').click()
        await self.page.clock.run_for(50)
        await self.page.evaluate('socket.close()')
        await self.page.clock.run_for(1500)
        await self.page.evaluate('socket.onopen()')
        self.assertTrue(await self.page.locator('#chat-panel').is_visible())
        self.assertEqual(await self.page.evaluate('terminal.cols'), 80)
        self.assertEqual(await self.page.evaluate("localStorage.getItem('mud86-terminal-style')"), 'bbc0')
        self.assertEqual(await self.page.evaluate("localStorage.getItem('mud86-chat-mode')"), 'true')

    async def test_same_width_styles_change_live_preserving_session_and_input(self):
        for chat_mode in (False, True):
            if chat_mode:
                await self.initial_chat()
            await self.connect()
            await self.page.evaluate("socket.onmessage({data: 'Earlier output\\r\\n' + 'Line\\r\\n'.repeat(40) + '*'}); window.originalSocket = socket")
            await self.page.clock.run_for(1000)
            if chat_mode:
                await self.page.locator('#chat-command').fill('unsent draft')
                await self.page.clock.run_for(50)
            await self.open_controls()
            await self.page.get_by_label('Connection speed').select_option('1200-75')
            await self.page.evaluate("outgoing.enqueue('look\\r')")
            for style, rows, font in [('vt220', 24, 'GlassTTY'), ('bbc0', 32, 'BBCBitmap'),
                                      ('vt52', 24, 'VT52'), ('mda', 25, 'IBMMDA'),
                                      ('cga', 25, 'IBMCGA'), ('original', 30, 'Menlo')]:
                await self.page.get_by_label('Terminal style').select_option(style)
                self.assertFalse(await self.page.locator('#confirm-style').is_visible())
                self.assertTrue(await self.page.evaluate('socket === originalSocket && socket.readyState === WebSocket.OPEN'))
                self.assertEqual(await self.page.evaluate('[terminal.cols, terminal.rows]'), [80, rows])
                self.assertIn(font, await self.page.evaluate('terminal.options.fontFamily'))
                self.assertEqual(await self.page.evaluate('[incoming.baud, outgoing.baud, outgoing.pending]'), [1200, 75, 'look\r'])
                self.assertEqual(await self.page.evaluate('localStorage.getItem(styleKey)'), style)
                self.assertEqual(await self.page.evaluate('terminal.buffer.active.getLine(0).translateToString(true)'), 'Earlier output')
                if chat_mode:
                    self.assertEqual(await self.page.locator('#chat-command').input_value(), 'unsent draft')
            await self.page.keyboard.press('Escape')

    async def test_new_terminal_fonts_geometry_and_chat_persistence(self):
        for style, label, rows, font, size, colour in [
            ('vt52', 'DEC VT52', 24, 'VT52', 15, '#dddddd'),
            ('mda', 'IBM PC MDA', 25, 'IBMMDA', 14, '#80ff80'),
            ('cga', 'IBM PC CGA', 25, 'IBMCGA', 16, '#aaaaaa'),
        ]:
            with self.subTest(style=style):
                await self.initial_style(style)
                await self.connect()
                self.assertEqual(await self.page.locator(f'#terminal-style option[value={style}]').inner_text(), label)
                self.assertEqual(await self.page.evaluate('[terminal.cols, terminal.rows, terminal.options.fontSize, terminal.options.theme.foreground]'),
                                 [80, rows, size, colour])
                self.assertTrue((await self.page.evaluate('socket.url')).endswith('?style=' + style))
                metrics = await self.page.evaluate("""({font, size}) => {
                    const face = Array.from(document.fonts).find(f => f.family === font);
                    const canvas = document.createElement('canvas').getContext('2d');
                    canvas.font = `${size}px ${font}`;
                    const widths = Array.from({length: 95}, (_, i) => canvas.measureText(String.fromCharCode(32 + i)).width);
                    return {loaded: face && face.status === 'loaded', min: Math.min(...widths), max: Math.max(...widths)};
                }""", dict(font=font, size=size))
                self.assertTrue(metrics['loaded'])
                self.assertAlmostEqual(metrics['min'], metrics['max'], delta=0.01)
                await self.page.evaluate("socket.onmessage({data: 'W'.repeat(80) + 'i'})")
                await self.page.clock.run_for(300)
                self.assertEqual(await self.page.evaluate('terminal.buffer.active.getLine(0).translateToString(true)'), 'W' * 80)
                self.assertEqual(await self.page.evaluate('terminal.buffer.active.getLine(1).translateToString(true)'), 'i')
                await self.initial_chat(style)
                await self.connect()
                self.assertEqual(await self.page.locator('#terminal-style').input_value(), style)
                self.assertIn(font, await self.page.locator('#chat-output').evaluate('el => getComputedStyle(el).fontFamily'))
                self.assertEqual(await self.page.locator('#chat-output').evaluate('el => getComputedStyle(el).fontSize'), f'{size}px')

    async def test_chat_input_docks_only_at_bottom_and_preserves_draft(self):
        await self.initial_chat()
        await self.connect()
        await self.page.evaluate("socket.onmessage({data: 'Welcome\\r\\n*'})")
        await self.page.clock.run_for(200)
        command = self.page.get_by_label('Command', exact=True)
        self.assertTrue(await command.is_visible())
        self.assertEqual(await self.page.locator('#chat-form label').count(), 0)
        self.assertFalse(await self.page.locator('#chat-form').evaluate("el => el.classList.contains('docked')"))
        self.assertFalse(await self.page.get_by_role('button', name='Send', exact=True).is_visible())
        prompt = await self.page.locator('#chat-output > div').last.bounding_box()
        field = await command.bounding_box()
        self.assertAlmostEqual(field['y'], prompt['y'], delta=2)
        self.assertGreater(field['x'], prompt['x'])
        await self.page.evaluate("socket.onmessage({data: 'What is your present password?\\r\\n*'})")
        await self.page.clock.run_for(100)
        await command.fill('secret draft')
        await self.page.clock.run_for(50)
        await command.evaluate('el => el.setSelectionRange(1, 5)')
        await self.page.evaluate("socket.onmessage({data: ('\\r\\nLine').repeat(70) + '\\r\\n*'})")
        await self.page.clock.run_for(1000)
        self.assertTrue(await self.page.locator('#chat-form').evaluate("el => el.classList.contains('docked')"))
        self.assertEqual(await self.page.locator('#chat-form button').count(), 0)
        # Native scroll/resize events are dispatched by the browser's real frames.
        await self.page.clock.resume()
        for top in (0, 100000):
            await self.page.evaluate('top => window.scrollTo(0, top)', top)
            await self.page.wait_for_function(
                "expected => document.getElementById('chat-form').classList.contains('docked') === expected", arg=top != 0)
            self.assertEqual(await self.page.locator('#chat-form').evaluate("el => el.classList.contains('docked')"), top != 0)
            self.assertAlmostEqual((await self.page.locator('header').bounding_box())['y'], 0, delta=1)
            self.assertEqual(await command.input_value(), 'secret draft')
            self.assertEqual(await command.get_attribute('type'), 'password')
            self.assertEqual(await command.evaluate('el => [el.selectionStart, el.selectionEnd]'), [1, 5])
        await self.page.set_viewport_size({'width': 1280, 'height': 3000})
        await self.page.wait_for_function("!document.getElementById('chat-form').classList.contains('docked')")
        self.assertFalse(await self.page.locator('#chat-form').evaluate("el => el.classList.contains('docked')"))
        self.assertEqual(await self.page.evaluate('sent'), [])

    async def test_style_restart_confirmation_and_cancel(self):
        await self.connect()
        await self.page.evaluate("socket.onmessage({data: 'Old session'}); window.originalSocket = socket")
        await self.page.clock.run_for(100)
        await self.open_controls()
        selector = self.page.get_by_label('Terminal style')
        await selector.select_option('bbc40')
        dialog = self.page.get_by_role('dialog', name='Change terminal settings?')
        self.assertTrue(await dialog.is_visible())
        self.assertIn('Your current session will be terminated so the new settings can take effect. You’ll reconnect automatically to rejoin the game. Are you sure?', await dialog.inner_text())
        await self.page.get_by_role('button', name='Cancel', exact=True).click()
        await self.page.clock.run_for(20)
        self.assertEqual(await selector.input_value(), 'original')
        self.assertTrue(await self.page.evaluate('socket === originalSocket && socket.readyState === 1'))
        self.assertIsNone(await self.page.evaluate('localStorage.getItem(styleKey)'))
        await selector.select_option('bbc40')
        await self.page.keyboard.press('Escape')
        await self.page.wait_for_function("!confirmStyle.open", polling=10)
        await self.page.clock.run_for(100)
        await self.page.wait_for_function("styleSelect.value === selectedStyle", polling=10)
        self.assertEqual(await selector.input_value(), 'original')
        await selector.select_option('bbc40')
        await self.page.evaluate("outgoing.setBaud(75); outgoing.enqueue('look\\r')")
        await self.page.get_by_role('button', name='Change settings and reconnect').click()
        await self.page.clock.run_for(20)
        self.assertEqual(await self.page.evaluate('outgoing.pending'), '')
        self.assertEqual(await self.page.evaluate('Array.from(sent[0])'), list(b'restart'))
        self.assertEqual(await self.page.evaluate('terminal.cols'), 80)
        await self.page.clock.run_for(2000)
        self.assertEqual(await self.page.evaluate('connections.length'), 1)
        # Only the gateway's close, after cleanup, permits the new connection.
        await self.page.evaluate('socket.close()')
        await self.page.clock.run_for(1200)
        self.assertEqual(await self.page.evaluate('terminal.cols'), 40)
        self.assertTrue((await self.page.evaluate('socket.url')).endswith('?style=bbc40'))
        self.assertEqual(await self.page.evaluate('localStorage.getItem(styleKey)'), 'bbc40')
        self.assertEqual(await self.page.locator('#dimensions-notice, #style-note').count(), 0)

    async def test_automatic_connection_and_preserved_output(self):
        await self.connect()
        self.assertEqual(await self.page.locator('#connect, #status, #settings').count(), 0)
        self.assertEqual(await self.page.locator('footer').count(), 0)
        self.assertEqual(await self.page.locator('header #settings-shortcut').inner_text(), 'Tab')
        self.assertEqual(await self.page.evaluate('connections.length'), 1)
        await self.page.evaluate("incoming.setBaud(300); outgoing.setBaud(75); socket.onmessage({data: 'Final score: ' + 'x'.repeat(100)}); outgoing.enqueue('look\\r'); socket.close()")
        await self.page.clock.run_for(1000)
        self.assertEqual(await self.page.evaluate('connections.length'), 1)
        self.assertEqual(await self.page.evaluate('outgoing.pending'), '')
        await self.page.clock.run_for(6000)
        self.assertEqual(await self.page.evaluate('connections.length'), 2)
        await self.page.evaluate("socket.onopen(); socket.onmessage({data: 'Fresh prompt*'})")
        await self.page.clock.run_for(1000)
        text = await self.page.evaluate(r"Array.from({length: terminal.buffer.active.length}, (_, i) => terminal.buffer.active.getLine(i).translateToString(true)).join('\n')")
        self.assertIn('Final score:', text)
        self.assertIn('Fresh prompt*', text)
        self.assertEqual(await self.page.evaluate('sent'), [])
        await self.open_controls()
        self.assertTrue(await self.page.get_by_role('dialog').is_visible())

    async def test_failed_connections_back_off_with_a_cap(self):
        await self.connect()
        for attempt, delay in enumerate([1000, 2000, 4000, 8000, 16000, 30000, 30000], 1):
            await self.page.evaluate("socket.readyState = 3; socket.onerror(); socket.onclose({code: 1006, reason: ''})")
            await self.page.clock.run_for(delay - 1)
            self.assertEqual(await self.page.evaluate('connections.length'), attempt)
            await self.page.clock.run_for(100)
            self.assertEqual(await self.page.evaluate('connections.length'), attempt + 1)
        await self.page.evaluate("socket.onmessage({data: 'Goodbye'}); socket.close()")
        await self.page.clock.run_for(1200)
        self.assertEqual(await self.page.evaluate('connections.length'), 9)

    async def test_period_presentation_and_font_alignment(self):
        await self.initial_style('vt220')
        details = await self.page.evaluate("""() => ({
            cols: terminal.cols, rows: terminal.rows,
            font: terminal.options.fontFamily,
            loaded: document.fonts.check('20px "GlassTTY"'),
            background: terminal.options.theme.background,
            foreground: terminal.options.theme.foreground
        })""")
        self.assertEqual(details, dict(cols=80, rows=24, font='GlassTTY, monospace',
                                      loaded=True, background='#000000', foreground='#dddddd'))
        await self.page.clock.run_for(100)
        await self.page.evaluate("terminal.reset(); terminal.write('W'.repeat(80) + 'i')")
        await self.page.clock.run_for(100)
        self.assertEqual(await self.page.evaluate(
            "terminal.buffer.active.getLine(0).translateToString(true)"), 'W' * 80)
        self.assertEqual(await self.page.evaluate(
            "terminal.buffer.active.getLine(1).translateToString(true)"), 'i')

    async def test_styles_default_persistence_and_live_switch(self):
        await self.page.evaluate('terminalReady')
        self.assertEqual(await self.page.evaluate(
            '[terminal.cols, terminal.rows, terminal.options.fontSize, terminal.options.theme.foreground]'),
            [80, 30, 16, '#c0e3bf'])
        await self.open_controls()
        selector = self.page.get_by_label('Terminal style')
        for preset, cols, rows, font in [('bbc40', 40, 25, 'Bedstead'), ('bbc0', 80, 32, 'BBCBitmap')]:
            await selector.select_option(preset)
            await self.page.get_by_role('button', name='Change settings and reconnect').click()
            await self.page.clock.run_for(20)
            await self.page.reload()
            await self.page.evaluate('terminalReady')
            self.assertEqual(await self.page.evaluate(
                f'[terminal.cols, terminal.rows, terminal.options.fontFamily, document.fonts.check(\'16px "{font}"\')]'),
                [cols, rows, font + ', monospace', True])
            await self.open_controls()
        await selector.select_option('bbc40')
        await self.page.get_by_role('button', name='Change settings and reconnect').click()
        await self.page.clock.run_for(20)
        await self.page.reload()
        await self.page.evaluate('terminalReady')
        self.assertEqual(await selector.input_value(), 'bbc40')
        self.assertEqual(await self.page.evaluate('terminal.cols'), 40)
        await self.connect()
        self.assertTrue((await self.page.evaluate('socket.url')).endswith('?style=bbc40'))
        await self.page.evaluate("window.originalSocket = socket; socket.onmessage({data: 'Hello'})")
        await self.page.clock.run_for(100)
        await self.open_controls()
        await selector.select_option('original')
        self.assertTrue(await self.page.evaluate('socket === originalSocket'))
        self.assertEqual(await self.page.evaluate('terminal.cols'), 40)
        self.assertEqual(await self.page.evaluate(
            'terminal.buffer.active.getLine(0).translateToString(true)'), 'Hello')
        await self.page.get_by_role('button', name='Change settings and reconnect').click()
        await self.page.clock.run_for(20)
        await self.page.evaluate("socket.readyState = 3; socket.onclose({reason: ''})")
        await self.page.clock.run_for(2000)
        self.assertEqual(await self.page.evaluate('[terminal.cols, terminal.rows]'), [80, 30])
        self.assertEqual(await self.page.evaluate('terminal.options.theme.foreground'), '#c0e3bf')

    async def test_old_bbc80_preference_migrates_to_mode0(self):
        await self.page.evaluate("localStorage.setItem('mud86-terminal-style', 'bbc80')")
        await self.page.reload()
        await self.page.evaluate('terminalReady')
        self.assertEqual(await self.page.locator('#terminal-style').input_value(), 'bbc0')
        self.assertEqual(await self.page.evaluate('[terminal.cols, terminal.rows]'), [80, 32])
        self.assertEqual(await self.page.evaluate("localStorage.getItem('mud86-terminal-style')"), 'bbc0')
        self.assertEqual(await self.page.locator('#terminal-style option[value=bbc80]').count(), 0)

    async def test_mode7_wraps_fragmented_words_and_edits(self):
        await self.initial_style('bbc40')
        await self.connect()
        async def receive(text):
            await self.page.evaluate('data => socket.onmessage({data})', text)
            await self.page.clock.run_for(300)
        async def lines(count):
            return await self.page.evaluate('count => Array.from({length: count}, (_, i) => terminal.buffer.active.getLine(i).translateToString(true))', count)
        await receive('A sentence with thirty characters: ele')
        await receive('phant walks past.')
        self.assertEqual(await lines(2), ['A sentence with thirty characters:', 'elephant walks past.'])
        # Preserve real newlines, blank lines, indentation and a prompt with no LF.
        await receive('\r\n\r\n  Heading\r\n*')
        self.assertEqual(await lines(5), ['A sentence with thirty characters:', 'elephant walks past.', '', '  Heading', '*'])
        await receive('say ' + 'a' * 30 + ' elephant')
        self.assertEqual((await lines(6))[4:], ['*say ' + 'a' * 30, 'elephant'])
        # TOPS-10 erases with backspace/space/backspace; move back over a wrap.
        await receive('\b \b' * 8)
        await receive('cat')
        self.assertEqual((await lines(5))[4].rstrip(), '*say ' + 'a' * 30 + ' cat')
        await receive('\x1b[')
        await receive('K\r\n' + 'x' * 45 + '\r\n*wx\b \bho')
        self.assertEqual((await lines(8))[5:], ['x' * 40, 'x' * 5, '*who'])
        await receive('\r\n  ' + 'w' * 40)
        self.assertEqual([line.rstrip() for line in (await lines(10))[8:]], ['', 'w' * 40])

    async def test_mode7_exact_80_columns_has_no_extra_line(self):
        await self.initial_style('bbc40')
        await self.connect()
        for text in ['x' * 80, 'a' * 39 + ' ' + 'b' * 40,
                     'a' * 39 + ' ' + 'b' * 39 + ' ',
                     'a' * 35 + ' ' + 'b' * 40 + ' ' * 4]:
            for chunk_size in (1, 19, 80):
                await self.page.evaluate("terminal.reset(); wrappedOutput.reset()")
                for offset in range(0, len(text), chunk_size):
                    await self.page.evaluate('data => incoming.enqueue(data)', text[offset:offset + chunk_size])
                    await self.page.clock.run_for(100)
                await self.page.evaluate("incoming.enqueue('\\r\\nNEXT')")
                await self.page.clock.run_for(100)
                self.assertEqual(await self.page.evaluate(
                    'terminal.buffer.active.getLine(2).translateToString(true)'), 'NEXT',
                    (text, chunk_size))
                await self.page.evaluate("incoming.enqueue('\\r\\n\\r\\nAFTER')")
                await self.page.clock.run_for(100)
                self.assertEqual(await self.page.evaluate(
                    '[3, 4].map(i => terminal.buffer.active.getLine(i).translateToString(true))'),
                    ['', 'AFTER'])
        self.assertEqual(await self.page.locator('#terminal-style option[value=bbc40]').inner_text(),
                         'BBC Micro Mode 7')

    async def test_mode7_slow_pacing_scrolling_and_reconnect(self):
        await self.initial_style('bbc40')
        await self.open_controls()
        await self.page.get_by_label('Connection speed').select_option('300-300')
        await self.page.keyboard.press('Escape')
        await self.connect()
        sentence = 'A sentence with thirty characters: elephant walks past.'
        await self.page.evaluate('data => socket.onmessage({data})', sentence)
        await self.page.clock.run_for(1000)
        await self.page.clock.run_for(5)  # Drain xterm's asynchronous write batch.
        self.assertEqual(await self.page.evaluate(
            'terminal.buffer.active.getLine(0).translateToString(true)'), sentence[:30])
        await self.page.clock.run_for(1000)
        self.assertEqual(await self.page.evaluate(
            'terminal.buffer.active.getLine(1).translateToString(true)'), 'elephant walks past.')
        await self.open_controls()
        await self.page.get_by_label('Connection speed').select_option('1200-75')
        await self.page.keyboard.press('Escape')
        await self.page.evaluate('data => socket.onmessage({data})', '\r\n' + (sentence + '\r\n') * 30 + '*')
        await self.page.clock.run_for(16000)
        rows = await self.page.evaluate('Array.from({length: 62}, (_, i) => terminal.buffer.active.getLine(i).translateToString(true))')
        self.assertEqual(rows, ['A sentence with thirty characters:', 'elephant walks past.'] * 31)
        # CR overwrites; tabs keep tab stops; CSI erase can arrive in pieces.
        await self.page.evaluate("socket.onmessage({data: 'bad\\r*hi\\x1b[K\\r\\n  A\\tB'})")
        await self.page.clock.run_for(1000)
        self.assertEqual(await self.page.evaluate(
            'terminal.buffer.active.getLine(62).translateToString(true)'), '*hi')
        self.assertEqual(await self.page.evaluate(
            'terminal.buffer.active.getLine(63).translateToString(true)'), '  A     B')
        await self.page.evaluate("socket.onmessage({data: '\\x1b['}); socket.readyState = 3; socket.onclose({reason: ''})")
        await self.page.clock.run_for(2000)
        await self.page.evaluate("socket.onopen(); socket.onmessage({data: 'Fresh prompt*'})")
        await self.page.clock.run_for(1000)
        self.assertIn('Fresh prompt*', await self.page.evaluate(
            "Array.from({length: terminal.buffer.active.length}, (_, i) => terminal.buffer.active.getLine(i).translateToString(true))"))

    async def test_pacer_rates_switching_and_reset(self):
        await self.page.evaluate("""() => {
            window.delivered = '';
            window.pacer = new SerialPacer(data => delivered += data, 300);
            pacer.enqueue('x'.repeat(2000));
        }""")
        await self.page.clock.run_for(1000)
        self.assertEqual(await self.page.evaluate("delivered.length"), 30)
        await self.page.evaluate("pacer.setBaud(75)")
        await self.page.clock.run_for(2000)
        self.assertEqual(await self.page.evaluate("delivered.length"), 45)
        await self.page.evaluate("pacer.setBaud(1200)")
        await self.page.clock.run_for(1000)
        self.assertEqual(await self.page.evaluate("delivered.length"), 165)
        await self.page.evaluate("pacer.setBaud(9600)")
        await self.page.clock.run_for(1000)
        self.assertEqual(await self.page.evaluate("delivered.length"), 1125)
        await self.page.evaluate("pacer.reset()")
        await self.page.clock.run_for(1000)
        self.assertEqual(await self.page.evaluate("delivered.length"), 1125)
        # Idle time must not accumulate credit for a later burst.
        await self.page.evaluate("pacer.setBaud(300); pacer.enqueue('abcdef'); pacer.enqueue('ghijkl')")
        await self.page.clock.run_for(100)
        self.assertEqual(await self.page.evaluate("delivered.slice(1125)"), "abc")

    async def test_panel_and_asymmetric_transport(self):
        await self.connect()
        await self.page.keyboard.press("Tab")
        self.assertTrue(await self.page.get_by_role("dialog").is_visible())
        await self.page.get_by_label("Connection speed").select_option("1200-75")
        self.assertEqual(await self.page.evaluate(
            '[terminal.options.cursorBlink, terminal.options.cursorInactiveStyle]'), [False, 'none'])
        self.assertEqual(await self.page.evaluate('getComputedStyle(controls).caretColor'), 'rgba(0, 0, 0, 0)')
        self.assertFalse(await self.page.locator('#terminal .xterm-cursor').first.is_visible())
        await self.page.keyboard.press("Tab")
        await self.page.clock.run_for(50)
        self.assertFalse(await self.page.locator('#controls').is_visible())
        self.assertTrue(await self.page.evaluate("document.activeElement.classList.contains('xterm-helper-textarea')"))
        self.assertTrue(await self.page.evaluate('terminal.options.cursorBlink'))
        self.assertTrue(await self.page.locator('#terminal .xterm-cursor').first.is_visible())
        self.assertEqual(await self.page.evaluate("sent"), [])
        await self.page.keyboard.press('Tab')
        self.assertTrue(await self.page.get_by_role('dialog', name='Settings', exact=True).is_visible())
        await self.page.keyboard.press("Escape")
        self.assertFalse(await self.page.get_by_role("dialog").is_visible())
        await self.page.evaluate("""() => {
            window.displayed = '';
            terminal.write = (data, callback) => { displayed += data.replace(/\x1b\[2J\x1b\[H/g, ''); if (callback) callback(); };
            socket.onmessage({data: 'x'.repeat(300)});
        }""")
        await self.page.keyboard.type("abcdefghijklmnopqrst")
        await self.page.clock.run_for(2000)
        self.assertEqual(await self.page.evaluate("sent.join('')"), "abcdefghijklmno")
        self.assertEqual(await self.page.evaluate("displayed.length"), 240)
        # Pending keystrokes must never leak into a reconnected session.
        await self.page.evaluate("socket.readyState = 3; socket.onclose({reason: ''})")
        await self.page.clock.run_for(2000)
        await self.page.evaluate("socket.onopen(); sent = []")
        await self.page.clock.run_for(2000)
        self.assertEqual(await self.page.evaluate("sent"), [])

    async def test_send_tab_and_backspace(self):
        await self.connect()
        await self.page.keyboard.press("Control+Backspace")
        await self.page.keyboard.press("Tab")
        await self.page.get_by_role("button", name="Send Tab to game").click()
        await self.page.clock.run_for(100)
        self.assertEqual(await self.page.evaluate("sent.join('')"), "\x7f\t")
