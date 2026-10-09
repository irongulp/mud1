"""Chromium creation/SAVE and full local-launcher restart against MariaDB."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import time

from playwright.async_api import async_playwright
from aiohttp import ClientSession, WSMsgType
from tools.persona_migrate import load_config
from tools.persona_protocol import pack_name
from tools.persona_writes import isolated_writer
from tools.serve_external import ROOT, DEFAULT_IMAGE
from tests.integration_provisioning import require
from tests.browser_smoke import wait_display

os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(ROOT / 'runtime/browsers'))


async def browser_check(url, name, password, creating, output, expected_score=None):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            page = await browser.new_page()
            await page.add_init_script("localStorage.setItem('mud86-chat-mode','true')")
            await page.goto(url)
            await page.evaluate('terminalReady')
            command = page.get_by_label('Command', exact=True)
            async def expect(text):
                await page.wait_for_function("text => document.getElementById('chat-output').textContent.includes(text)", arg=text, timeout=45000)
            async def submit(text):
                await command.fill(text); await command.press('Enter')
            await expect('By what name shall I call you?')
            await submit(name)
            if creating:
                await expect('What sex do you wish to be?'); await submit('m')
                await expect('letters, please.')
            else: await expect("what's the password?")
            await submit(password)
            await expect('Hello')
            if creating:
                await submit('save'); await expect(' saved.')
                await submit('password'); await expect('What is your present password?')
                await submit(password); await expect('New password for persona')
                await submit('newproof'); await expect("Enter it again to make sure it's correct, please.")
                await submit('newproof'); await expect('Your password will be updated when you leave the game.')
            await submit('score'); await expect('Games played to date:')
            if expected_score is not None:
                await expect('Score to date: '+str(expected_score))
            if not creating:
                await expect('Games played to date: 2')
            # Fresh DOM transcript across processes proves actual re-entry.
            require(password not in await page.locator('#chat-output').inner_text(), 'Browser exposed a password')
            require('newproof' not in await page.locator('#chat-output').inner_text(), 'Browser exposed the changed password')
            await page.screenshot(path=str(output / ('created.png' if creating else 'restored.png')))
        finally: await browser.close()


async def browser_purge(url, target):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            page = await browser.new_page()
            await page.add_init_script("localStorage.setItem('mud86-chat-mode','true')")
            await page.goto(url); await page.evaluate('terminalReady')
            command = page.get_by_label('Command',exact=True)
            async def expect(text):
                await page.wait_for_function("text => document.getElementById('chat-output').textContent.includes(text)",arg=text,timeout=45000)
                await wait_display(page)
            async def submit(text):
                await command.fill(text); await command.press('Enter')
            await expect('By what name shall I call you?')
            await submit('Roy'); await expect('letters, please.')
            await submit('adminproof'); await expect('Hello, Roy')
            await submit('save'); await expect(' saved.')
            await submit('purge ' + target); await expect('Save, delete or finish? ')
            await submit('d'); await expect('deleted.')
            require('adminproof' not in await page.locator('#chat-output').inner_text(), 'Administrator password echoed')
        finally: await browser.close()


async def lookup_only(url, name):
    async with ClientSession() as client, client.ws_connect(url+'/terminal') as socket:
        data = ''
        while not data.endswith('*'):
            message = await asyncio.wait_for(socket.receive(),45)
            require(message.type == WSMsgType.TEXT,'Lookup session ended before name prompt')
            data += message.data
        await socket.send_str(name+'\r')
        data = ''
        while 'password' not in data.lower():
            message = await asyncio.wait_for(socket.receive(),20)
            require(message.type == WSMsgType.TEXT,'Idle lookup closed unexpectedly')
            data += message.data
            require('unavailable' not in data.lower(),'Idle lookup could not claim a storage channel')


def run(output, source, idle_seconds=0):
    output.mkdir(mode=0o700)
    report = {'complete': False}
    name = 'Lab' + ''.join(secrets.choice('abcdefghijklmnopqrstuvwxyz') for _ in range(5))
    password = 'labproof'
    process = None
    try:
        for creating in (True, False):
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', 0)); port = probe.getsockname()[1]
            with (output / ('first.log' if creating else 'restart.log')).open('wb') as log:
                process = subprocess.Popen([sys.executable, '-m', 'tools.serve_external', '--state-dir', str(output / 'state'),
                                            '--prepared-runtime', str(source), '--port', str(port)], stdout=log, stderr=log)
                deadline = time.monotonic() + 240
                ready = output / 'state/ready.json'
                while not ready.exists():
                    require(process.poll() is None, 'Local launcher exited; inspect private log')
                    require(time.monotonic() < deadline, 'Local launcher readiness timed out')
                    time.sleep(0.1)
                asyncio.run(browser_check(json.loads(ready.read_text())['url'], name, password if creating else 'newproof', creating, output))
                if creating and idle_seconds:
                    print('Checking lookup after idle:',idle_seconds,'seconds',flush=True)
                    time.sleep(idle_seconds)
                    asyncio.run(lookup_only(json.loads(ready.read_text())['url'],name))
                config = load_config(output / 'state/database.json')
                with isolated_writer(config) as store:
                    record = store.get(pack_name(name.lower()))
                    require(record is not None, 'Browser SAVE did not persist in MariaDB')
                if not creating:
                    asyncio.run(browser_purge(json.loads(ready.read_text())['url'],name))
                    with isolated_writer(config) as store:
                        require(store.get(pack_name(name.lower())) is None, 'Browser PURGE did not delete column record')
                process.send_signal(signal.SIGTERM)
                require(process.wait(timeout=150) == 0, 'Local launcher did not shut down cleanly')
                process = None
                require(not ready.exists(), 'Launcher left stale readiness')
        report.update(complete=True, browser_create_save=True, password_change_quit=True,
                      full_restart_reentry=True, browser_purge=True, persona=name,idle_seconds=idle_seconds)
        print('Local external browser checks complete:', output, flush=True)
    finally:
        if process is not None and process.poll() is None:
            process.send_signal(signal.SIGTERM)
            try: process.wait(timeout=150)
            except subprocess.TimeoutExpired: process.kill(); process.wait()
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'runtime' / f'external-local-{time.time_ns()}')
    parser.add_argument('--prepared-runtime', type=Path, default=DEFAULT_IMAGE)
    parser.add_argument('--idle-seconds', type=float, default=0)
    args = parser.parse_args()
    run(args.output.resolve(), args.prepared_runtime.resolve(),args.idle_seconds)
