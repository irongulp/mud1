"""Real Chromium test against an original MUD gateway (localhost:8080 by default)."""
import argparse
import asyncio
import os
import secrets
import string
from pathlib import Path

from playwright.async_api import TimeoutError as BrowserTimeoutError, async_playwright

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(ROOT / "runtime/browsers"))
EDITING_TIMEOUT_MS = 20000


async def wait_text(page, text):
    await page.wait_for_function(r"""text => {
        const buffer = terminal.buffer.active;
        const lines = [];
        for (let n = 0; n < buffer.length; n++) lines.push(buffer.getLine(n).translateToString());
        return lines.join('\n').includes(text);
    }""", arg=text, timeout=20000)


async def command(page, text):
    await page.keyboard.type(text)
    await page.keyboard.press("Enter")


async def wait_display(page):
    await page.wait_for_function("incoming.pending.length === 0", timeout=60000)
    await page.evaluate("new Promise(resolve => terminal.write('', resolve))")


async def wait_terminal_line(page, expected, stage, *, timeout=EDITING_TIMEOUT_MS,
                             screenshot=None):
    """Wait for paced, parsed output, not a suffix in the raw WebSocket log."""
    try:
        await page.wait_for_function("""expected => {
            if (incoming.pending.length || outgoing.pending.length) return false;
            const buffer = terminal.buffer.active;
            const line = buffer.getLine(buffer.baseY + buffer.cursorY).translateToString(true);
            // Native rubout is BS SPACE BS: the erased cell remains a space.
            // Require exact text/cursor and no visible content beyond it.
            return buffer.cursorX === expected.length &&
                line.slice(0, buffer.cursorX) === expected &&
                line.slice(buffer.cursorX).trim() === '';
        }""", arg=expected, timeout=timeout)
    except BrowserTimeoutError as error:
        state = await page.evaluate("""() => {
            const buffer = terminal.buffer.active;
            return {
                line: buffer.getLine(buffer.baseY + buffer.cursorY).translateToString(true),
                raw_output: gameOutput,
                cursor: {x: buffer.cursorX, y: buffer.cursorY, baseY: buffer.baseY},
                incoming: incoming.pending.length,
                outgoing: outgoing.pending.length
            };
        }""")
        if screenshot is not None:
            await page.screenshot(path=str(screenshot), full_page=True)
        raise AssertionError(f"{stage}: expected terminal line {expected!r}; {state!r}") from error


async def wait_prompt(page):
    await page.wait_for_function(
        "gameOutput.endsWith('\\n*')", timeout=60000)
    await wait_display(page)


async def check_name_prompt(page):
    await wait_prompt(page)
    # Allow a second prompt caused by buffered setup input to arrive.
    await page.wait_for_timeout(500)
    await wait_display(page)
    output = await page.evaluate('gameOutput')
    suffix = output.rsplit('By what name shall I call you?', 1)[1]
    if suffix.count('*') != 1:
        return [f'Expected one initial name prompt, received {suffix!r}']
    return []


async def check_editing_and_width(page, name, *, screenshot=None):
    failures = []
    await wait_prompt(page)
    for key in ("Backspace", "Control+Backspace", "Control+h"):
        await page.evaluate("gameOutput = ''")
        await page.keyboard.type("wx")
        await wait_terminal_line(page, '*wx', f'{key} initial echo', screenshot=screenshot)
        await page.keyboard.press(key)
        await wait_terminal_line(page, '*w', f'{key} erase', screenshot=screenshot)
        await page.keyboard.type("ho")
        await wait_terminal_line(page, '*who', f'{key} completed edit', screenshot=screenshot)
        await page.keyboard.press("Enter")
        await wait_prompt(page)
        output = await page.evaluate("gameOutput")
        if name + " is playing" not in output or "^H" in output:
            failures.append(f"{key} did not erase the typo: {output!r}")

    await page.evaluate("gameOutput = ''; terminal.clear()")
    await command(page, "info")
    await wait_prompt(page)
    wrapped = await page.evaluate("""() => {
        const buffer = terminal.buffer.active;
        const wrapped = [];
        for (let i = 0; i < buffer.length; i++) {
            const line = buffer.getLine(i);
            if (line.isWrapped) wrapped.push(line.translateToString(true));
        }
        return wrapped;
    }""")
    if wrapped:
        failures.append(f"INFO has unintended browser wraps: {wrapped!r}")
    return failures


async def main(url="http://127.0.0.1:8080", screenshot=ROOT / "runtime/browser.png", after_join=None,
               launch_args=None, ignore_https_errors=False):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(args=launch_args or [])
        errors = []
        pages = []
        names = []
        try:
            for _ in range(2):
                page = await browser.new_page(viewport={"width": 1100, "height": 850},
                                              ignore_https_errors=ignore_https_errors)
                page.on("pageerror", lambda error: errors.append(str(error)))
                await page.add_init_script("""(() => {
                    window.gameOutput = '';
                    window.WebSocket = class extends WebSocket {
                        constructor(...args) {
                            super(...args);
                            this.addEventListener('message', event => gameOutput += event.data);
                        }
                    };
                })();""")
                await page.goto(url)
                await wait_text(page, "By what name shall I call you?")
                errors.extend(await check_name_prompt(page))
                name = "Ui" + "".join(secrets.choice(string.ascii_lowercase) for _ in range(6))
                names.append(name)
                await command(page, name)
                await wait_text(page, "What sex do you wish to be?")
                await command(page, "m")
                await wait_text(page, "letters, please.")
                await command(page, "testpass")
                await wait_text(page, "Hello, " + name)
                await wait_text(page, "Narrow road between lands.")
                pages.append(page)
            if after_join is not None:
                await after_join()
            errors.extend(await check_editing_and_width(pages[0], names[0], screenshot=screenshot))
            await command(pages[0], "who")
            for name in names:
                await wait_text(pages[0], name + " is playing")
            marker = "Chromiumproof" + secrets.token_hex(3)
            await command(pages[0], "shout " + marker)
            await wait_text(pages[1], marker)
            await pages[0].screenshot(path=str(screenshot), full_page=True)
            for page in pages:
                await page.evaluate("gameOutput = ''; window.previousSocket = socket")
                await command(page, "quit")
                await page.wait_for_function("socket !== previousSocket && gameOutput.includes('By what name shall I call you?')", timeout=30000)
                errors.extend(await check_name_prompt(page))
                await wait_display(page)
                await wait_text(page, 'Chromiumproof')
            assert not errors, errors
            print("PASS: automatic login, editing and INFO wrapping; two tabs share WHO and speech, quit and reconnect with scrollback")
        finally:
            await browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8080")
    parser.add_argument("--screenshot", type=Path, default=ROOT / "runtime/browser.png")
    args = parser.parse_args()
    asyncio.run(main(args.url, args.screenshot))
