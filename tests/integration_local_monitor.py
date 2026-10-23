"""Disposable normal-launcher acceptance for the per-boot startup guards.

--assets-root selects read-only media/browser assets for an isolated checkout.
Guest disks, database and listener ports are private to the new output directory.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
from unittest.mock import patch


def record_simulator(output, executable):
    from tools.persona_snapshot import publish_private
    metadata = dict(path=str(executable), sha256=hashlib.sha256(executable.read_bytes()).hexdigest())
    filename = output/'simulator.json'
    if filename.exists():
        if json.loads(filename.read_text()) != metadata:
            raise ValueError('Simulator identity changed across restart')
        return
    publish_private(filename,
        lambda stream: stream.write((json.dumps(metadata, indent=2)+'\n').encode('ascii')))


def terminal_fixture(assets, source, state):
    """Stopped source copy with STOMP enabled to exercise the internal reboot."""
    from tools import benchmark_idle
    from tools.serve_external import prepare_machine, start_guest, reserve_ports
    state.mkdir(mode=0o700)
    directory = prepare_machine(state, source)
    machine = None
    failed = False
    try:
        with patch.object(benchmark_idle, 'ROOT', assets):
            machine = start_guest(directory, reserve_ports())
        raw = machine.command('type sys:tty.ini').replace('\r', '')
        text = raw.split('\n', 1)[1].rsplit('\n.', 1)[0]
        if not any(line.startswith('STOMP ') for line in text.splitlines()):
            machine.copy_text('sys:tty.ini', text.rstrip()+'\nSTOMP ACCOUNT "SYSTEM"\n')
        if 'STOMP ACCOUNT' not in machine.command('type sys:tty.ini'):
            raise AssertionError('Could not prepare terminal initializer fixture')
        return directory
    except BaseException:
        failed = True
        raise
    finally:
        if machine is not None and not machine.stop() and not failed:
            raise AssertionError('Terminal fixture did not shut down cleanly')


async def wait_for_cleanup(url):
    from aiohttp import ClientSession
    async with ClientSession() as client:
        deadline = asyncio.get_running_loop().time()+15
        while True:
            async with client.get(url+'/internal/maintenance', allow_redirects=False) as response:
                if response.status != 200:
                    raise AssertionError('Cannot verify local gateway cleanup')
                if (await response.json())['sessions'] == 0:
                    return
            if asyncio.get_running_loop().time() >= deadline:
                raise AssertionError('Gateway jobs did not finish cleanup')
            await asyncio.sleep(.1)


async def multiplayer(url, name, password, output):
    from playwright.async_api import async_playwright
    from tests.browser_smoke import wait_display
    helper = 'Mon'+''.join(secrets.choice('abcdefghijklmnopqrstuvwxyz') for _ in range(5))
    observations = []
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            context = await browser.new_context()
            await context.add_init_script("""
                localStorage.setItem('mud86-chat-mode','true');
                window.monitorOutput=''; window.monitorEpoch=0;
                const NativeSocket=window.WebSocket;
                window.WebSocket=class extends NativeSocket {
                    constructor(...args) { super(...args); monitorEpoch++;
                        this.addEventListener('message', e => {
                            if(typeof e.data==='string') monitorOutput+=e.data;
                        });
                    }
                };
            """)
            pages = []

            async def submit(page, text, expected):
                await wait_display(page)
                await page.evaluate("monitorOutput=''")
                field = page.get_by_label('Command', exact=True)
                await field.fill(text)
                await field.press('Enter')
                await page.wait_for_function('text => monitorOutput.includes(text)', arg=expected, timeout=45000)
                await wait_display(page)
                return await page.evaluate('monitorOutput')

            for persona, creating in ((name, False), (helper, True)):
                page = await context.new_page()
                pages.append(page)
                await page.goto(url)
                await page.evaluate('terminalReady')
                await page.wait_for_function("monitorOutput.includes('By what name shall I call you?')", timeout=45000)
                await submit(page, persona, 'What sex do you wish to be?' if creating else "what's the password?")
                if creating:
                    await submit(page, 'm', 'letters, please.')
                raw = await submit(page, password, 'Hello')
                if password in raw:
                    raise AssertionError('Browser exposed the fixture password')
                raw = await submit(page, 'score', 'Games played to date:')
                if 'Score to date: 0' not in raw:
                    raise AssertionError('Unexpected ordinary-player score')
                observations.append(dict(persona=persona, command='score', output=raw))
            for page, persona in zip(pages, (name, helper)):
                raw = await submit(page, 'who', helper)
                if name not in raw or helper not in raw:
                    raise AssertionError('WHO did not show both simultaneous players')
                if await page.evaluate('monitorEpoch') != 1:
                    raise AssertionError('Browser reconnected during multiplayer check')
                observations.append(dict(persona=persona, command='who', output=raw))
            (output/'multiplayer.json').write_text(json.dumps(dict(complete=True,
                personas=[name, helper], observations=observations, epochs=[1, 1]), indent=2)+'\n')
        finally:
            await browser.close()
    await wait_for_cleanup(url)


def run(output, assets, source, idle_seconds, fixture=None):
    os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(assets/'runtime/browsers'))
    if fixture:
        source = terminal_fixture(assets, source, fixture)
    from tests import integration_external_local as acceptance
    from tools import benchmark_idle
    from tools.serve_external import local_simulator
    from server.local_batch import BATCH_READINESS_ID, completed_probe
    original_check, original_popen = acceptance.browser_check, subprocess.Popen
    launches = []

    def launch(arguments, *args, **kwargs):
        if isinstance(arguments, list) and arguments[1:3] == ['-m', 'tools.serve_external']:
            with patch.object(benchmark_idle, 'ROOT', assets):
                executable = local_simulator()
            record_simulator(output, executable)
            code = ('from pathlib import Path; from tools import benchmark_idle; '
                    f'benchmark_idle.ROOT=Path({str(assets)!r}); '
                    'from tools.serve_external import main; main()')
            arguments = [arguments[0], '-c', code]+arguments[3:]
            launches.append(arguments)
        return original_popen(arguments, *args, **kwargs)

    async def check(url, name, password, creating, output, expected_score=None):
        ready = json.loads((output/'state/ready.json').read_text())
        boot_id = ready['monitor_boot']
        boot = output/'state/machine/monitor-boots'/boot_id
        verified = [json.loads(path.read_text()) for path in boot.glob('*-verified.json')]
        if (ready['monitor_scope'] != 'ks10-swap-output-scope-v1'
                or not any(item.get('installed') and item.get('boot_id') == boot_id for item in verified)):
            raise AssertionError('Readiness is not tied to this verified boot')
        probe = json.loads((boot/'batch-probe.json').read_text())
        batch_records = [json.loads(path.read_text()) for path in boot.glob('*-batch-ready.json')]
        if (ready.get('batch_readiness') != BATCH_READINESS_ID or probe['boot_id'] != boot_id
                or not any(item.get('batch_ready') and item.get('boot_id') == boot_id for item in batch_records)
                or not completed_probe(probe['log'], boot_id[:6], boot_id, probe['request'])):
            raise AssertionError('Native batch proof is not tied to this current boot')
        await original_check(url, name, password, creating, output, expected_score)
        await wait_for_cleanup(url)
        if not creating:
            await multiplayer(url, name, password, output)

    with patch('subprocess.Popen', launch), patch.object(acceptance, 'browser_check', check):
        acceptance.run(output, source, idle_seconds)
    evidence = []
    for directory in sorted((output/'state/machine/monitor-boots').iterdir()):
        records = [json.loads(path.read_text()) for path in sorted(directory.glob('*.json'))]
        verified = [record for record in records if record.get('stage') == 'verified']
        shutdown = json.loads((directory/'shutdown.json').read_text())
        if not verified or not shutdown['clean']:
            raise AssertionError('A boot lacked verified correction or clean native shutdown')
        if any(path.suffix == '.ini' for path in directory.iterdir()):
            raise AssertionError('Private register/stack restore script was retained')
        evidence.append(dict(directory=str(directory), address=verified[0]['address'],
                             payload_sha256=verified[0]['payload_sha256'], clean=True))
    if len(launches) != 2 or len(evidence) < (3 if fixture else 2):
        raise AssertionError('Full launcher restart/internal reboot was not exercised')
    console = (output/'state/machine/console.log').read_text()
    if 'REG[0]' in console or 'scope-restore-' in console:
        raise AssertionError('Private monitor memory operations reached the transcript')
    (output/'monitor-report.json').write_text(json.dumps(dict(complete=True, boots=evidence,
        idle_seconds=idle_seconds, research_reference_required=False,
        internal_reboot_verified=bool(fixture), multiplayer=True), indent=2)+'\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--assets-root', type=Path, required=True)
    parser.add_argument('--prepared-runtime', type=Path, required=True)
    parser.add_argument('--idle-seconds', type=float, default=75)
    parser.add_argument('--terminal-fixture', type=Path)
    args = parser.parse_args()
    run(args.output.resolve(), args.assets_root.resolve(), args.prepared_runtime.resolve(), args.idle_seconds,
        args.terminal_fixture.resolve() if args.terminal_fixture else None)
