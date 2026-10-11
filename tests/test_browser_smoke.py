"""Synchronization regressions for the original-engine browser smoke client."""
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from playwright.async_api import async_playwright

from tests import browser_smoke


class EditingSequenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_editing_waits_for_each_echo_before_the_next_key(self):
        page = AsyncMock()
        pending_echo = False

        async def type_text(text):
            nonlocal pending_echo
            self.assertFalse(pending_echo, 'Typing advanced before the previous echo')
            pending_echo = text != 'info'

        async def press_key(key):
            nonlocal pending_echo
            self.assertFalse(pending_echo, 'Editing advanced before the previous echo')
            pending_echo = key != 'Enter'

        async def rendered(*args, **kwargs):
            nonlocal pending_echo
            pending_echo = False

        page.keyboard.type.side_effect = type_text
        page.keyboard.press.side_effect = press_key
        page.evaluate.side_effect = lambda expression: (
            'Candidate is playing' if expression == 'gameOutput' else [])
        with patch.object(browser_smoke, 'wait_prompt', side_effect=rendered), \
                patch.object(browser_smoke, 'wait_terminal_line', side_effect=rendered,
                             create=True) as wait_line:
            self.assertEqual(await browser_smoke.check_editing_and_width(page, 'Candidate'), [])
        self.assertEqual([call.args[1] for call in wait_line.await_args_list],
                         ['*wx', '*w', '*who'] * 3)


class RenderedLineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch()
        self.page = await self.browser.new_page()
        await self.page.set_content('<div id="terminal"></div>')
        await self.page.add_script_tag(path=str(browser_smoke.ROOT / 'web/vendor/xterm.js'))
        await self.page.evaluate("""() => {
            window.terminal = new Terminal();
            terminal.open(document.getElementById('terminal'));
            window.incoming = {pending: ''};
            window.outgoing = {pending: ''};
            window.gameOutput = 'ho';
        }""")

    async def asyncTearDown(self):
        await self.browser.close()
        await self.playwright.stop()

    async def test_raw_suffix_does_not_substitute_for_completed_redraw(self):
        await self.page.evaluate("""() => new Promise(resolve => {
            terminal.write('*howho', resolve);
        })""")
        await self.page.evaluate(r"""() => {
            setTimeout(() => terminal.write('\r\x1b[2K*who'), 100);
        }""")
        await browser_smoke.wait_terminal_line(self.page, '*who', 'Backspace redraw')
        self.assertEqual(await self.page.evaluate("""() => {
            const buffer = terminal.buffer.active;
            return buffer.getLine(buffer.baseY + buffer.cursorY).translateToString(true);
        }"""), '*who')

    async def test_matching_line_still_waits_for_pacing_queues(self):
        await self.page.evaluate("""() => new Promise(resolve => {
            terminal.write('*who', resolve);
        })""")
        await self.page.evaluate("""() => {
            outgoing.pending = 'ho';
            incoming.pending = 'echo';
            setTimeout(() => { outgoing.pending = ''; incoming.pending = ''; }, 100);
        }""")
        await browser_smoke.wait_terminal_line(self.page, '*who', 'paced echo')
        self.assertEqual(await self.page.evaluate('[incoming.pending, outgoing.pending]'), ['', ''])

    async def test_failed_redraw_reports_raw_output_cursor_and_queues(self):
        self.page.screenshot = AsyncMock()
        await self.page.evaluate("""() => new Promise(resolve => {
            terminal.write('*howho', resolve);
        })""")
        with self.assertRaisesRegex(AssertionError, r"Backspace.*howho.*raw_output.*cursor.*incoming"):
            await browser_smoke.wait_terminal_line(
                self.page, '*who', 'Backspace', timeout=100,
                screenshot=Path('failure.png'))
        self.page.screenshot.assert_awaited_once_with(path='failure.png', full_page=True)
