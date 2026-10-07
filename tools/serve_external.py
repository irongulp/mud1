"""Foreground, loopback-only external-persona browser lab on a copied guest disk."""
import argparse
import asyncio
from contextlib import ExitStack
from dataclasses import asdict
import fcntl
import json
import logging
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

from aiohttp import web
from server.external_bootstrap import ExternalBootstrap
from server.gateway import create_app
from tools.persona_migrate import load_config
from tools.persona_snapshot import publish_private
from tools.persona_write_session import serve_personas
from tools.persona_writes import isolated_writer
# Reuse verified disposable-runtime mechanics for this local research launcher.
# This is not the systemd deployment entry point.
from tests.integration_storage_bridge import private_emulator, BRIDGE_LINES
from tests.integration_persona_read import connect_slave
from tests.integration_persona_writes import enable_writes
from tests.mariadb_fixture import LocalMariaDb, DATABASE

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE = ROOT / 'runtime/external-local'
DEFAULT_IMAGE = ROOT / 'runtime/external-always-open-green/compiled'
DEFAULT_HTTP_PORT = 8081
BOOT_ATTEMPTS = 3
CONFIG_LINE_DELAY = 0.1
LOG = logging.getLogger(__name__)


class StateLock:
    def __init__(self, directory): self.directory = Path(directory)
    def __enter__(self):
        self.directory.mkdir(mode=0o700, parents=False, exist_ok=True)
        if self.directory.stat().st_mode & 0o077:
            raise RuntimeError('Local state directory must have owner-only permissions')
        self.stream = (self.directory / 'launcher.lock').open('a+')
        os.fchmod(self.stream.fileno(), 0o600)
        try: fcntl.flock(self.stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.stream.close()
            raise RuntimeError('Another external launcher owns this state directory') from None
        return self
    def __exit__(self, *exc): self.stream.close()


def source_stopped(path):
    return subprocess.run(['lsof', '-t', '--', str(path)], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 1


def prepare_machine(state, source):
    machine = state / 'machine'
    if (machine / 'guest.dsk').is_file(): return machine
    disk = source / 'guest.dsk'
    if not disk.is_file(): raise RuntimeError('Prepared external runtime has no guest.dsk')
    if not source_stopped(disk): raise RuntimeError('Source guest disk must be stopped before copying')
    machine.mkdir(mode=0o700)
    def copy(stream):
        with disk.open('rb') as input_stream: shutil.copyfileobj(input_stream, stream)
    publish_private(machine / 'guest.dsk', copy)
    return machine


def load_local_config(state):
    config = load_config(state / 'database.json')
    if (config.database != DATABASE or config.namespace != 'mud'
            or config.unix_socket != str(state / 'db/db.sock')):
        raise RuntimeError('Local database configuration must use this state directory and mud namespace')
    return config


class LocalDatabase:
    def __init__(self, state): self.state = state
    def __enter__(self):
        self.database = LocalMariaDb(self.state / 'db', column_schema=True)
        try:
            if (self.state / 'database.json').exists():
                self.config = load_local_config(self.state)
                server = shutil.which('mariadbd')
                if not server: raise RuntimeError('MariaDB is not installed')
                self.database.server = str(Path(server).resolve())
                self.database.start()
            else:
                if (self.state / 'db').exists():
                    raise RuntimeError('Database setup was interrupted; inspect it or choose a fresh state directory')
                self.database.__enter__()
                self.config = enable_writes(self.database, allow_delete=True, allow_create=True)
                publish_private(self.state / 'database.json',
                    lambda stream: stream.write(json.dumps(asdict(self.config)).encode('ascii') + b'\n'))
            return self.config
        except BaseException:
            self.database.stop()
            raise
    def __exit__(self, *exc): self.database.stop()


class PersonaBridge:
    def __init__(self, machine, ports, store):
        self.machine, self.ports, self.store = machine, ports, store
        self.stopping = False
    def __enter__(self):
        self.stack = ExitStack()
        try:
            self.channels = [self.stack.enter_context(connect_slave(self.machine, line, self.ports[line]))
                             for line in BRIDGE_LINES]
            self.executor = ThreadPoolExecutor(max_workers=len(self.channels))
            self.futures = [self.executor.submit(self.worker, channel) for channel in self.channels]
            return self
        except BaseException:
            self.stack.close(); raise
    def worker(self, channel):
        while not self.stopping:
            try:
                serve_personas(channel, self.store, allow_delete=True, allow_create=True, allow_admin=True)
                return
            except TimeoutError:
                # Keep the private raw listener available after idle/frame
                # expiry. The old protocol owner is retired; require fresh H1.
                continue
            except (OSError, ValueError) as error:
                if not self.stopping: LOG.error('Local persona bridge ended: %s', type(error).__name__)
                return
    def __exit__(self, *exc):
        self.stopping = True
        for channel in self.channels:
            try: channel.shutdown(socket.SHUT_RDWR)
            except OSError: pass
        self.executor.shutdown(wait=True)
        self.stack.close()


def reserve_ports():
    with ExitStack() as stack:
        ports = {}
        for line in BRIDGE_LINES:
            connection = stack.enter_context(socket.socket())
            connection.bind(('127.0.0.1', 0)); ports[line] = connection.getsockname()[1]
        return ports


def local_tty_config(text):
    lines = text.replace('\r','').splitlines()
    if not any(line.startswith('ALL ') for line in lines) or not any(line.startswith('CTY:') for line in lines):
        raise RuntimeError('Unrecognized private guest terminal configuration')
    return '\n'.join(line for line in lines if not line.lstrip().upper().startswith('STOMP ')) + '\n'


def protect_bridge_terminals(machine):
    """Disable only the copied lab's optional detached terminal initializer.

    STOMPR can hold released raw bridge devices in INIT, preventing guest OPEN.
    Browser connections already set type/width explicitly. Normal native and
    deployed configurations are not changed by this local-lab procedure.
    """
    response = machine.command('type sys:tty.ini').replace('\r','')
    original = response.split('\n',1)[1].rsplit('\n.',1)[0]
    desired = local_tty_config(original)
    if original.strip() == desired.strip(): return False
    # Keep the original lab configuration as a file in the operator's directory.
    machine.command('copy xtty.ini=sys:tty.ini')
    machine.child.send('copy sys:tty.ini=tty:\r')
    machine.child.expect_exact('copy sys:tty.ini=tty:\r\n')
    for line in desired.splitlines():
        machine.child.send(line+'\r')
        machine.child.expect_exact('\r\n')
        time.sleep(CONFIG_LINE_DELAY)
    machine.child.sendcontrol('z'); machine.child.expect(r'\n\.')
    actual = machine.command('type sys:tty.ini').replace('\r','').split('\n',1)[1].rsplit('\n.',1)[0]
    if actual.strip() != desired.strip(): raise RuntimeError('Private terminal configuration verification failed')
    return True


async def serve(machine, bridge, state, port):
    runner = web.AppRunner(create_app(upstream_port=machine.port, session_bootstrap=ExternalBootstrap()))
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM): loop.add_signal_handler(signum, stop.set)
    try:
        await runner.setup()
        await web.TCPSite(runner, '127.0.0.1', port).start()
        ready = state / 'ready.json'
        ready.unlink(missing_ok=True)
        publish_private(ready, lambda stream: stream.write(json.dumps({
            'url': f'http://127.0.0.1:{port}', 'pid': os.getpid(), 'upstream_port': machine.port,
            'state_dir': str(state), 'persona_storage': 'mariadb'}).encode()))
        print(f'External persona lab: http://127.0.0.1:{port}', flush=True)
        print('Personas persist in ' + str(state) + '. Press Ctrl-C for clean shutdown.', flush=True)
        while not stop.is_set():
            try: await asyncio.wait_for(stop.wait(), 1)
            except asyncio.TimeoutError: pass
            if any(future.done() for future in bridge.futures):
                raise RuntimeError('Persona bridge stopped; local game is shutting down')
    finally:
        (state / 'ready.json').unlink(missing_ok=True)
        await runner.cleanup()  # Keep bridge/database alive through guest QUIT/KJOB.
        for signum in (signal.SIGINT, signal.SIGTERM): loop.remove_signal_handler(signum)


def run(state, source, port):
    state, source = state.resolve(), source.resolve()
    with socket.socket() as probe: probe.bind(('127.0.0.1', port))
    with StateLock(state):
        (state / 'ready.json').unlink(missing_ok=True)
        machine_dir = prepare_machine(state, source)
        machine = None
        try:
            with LocalDatabase(state) as config, isolated_writer(config) as store:
                for attempt in range(BOOT_ATTEMPTS):
                    startup = ExitStack()
                    try:
                        ports = reserve_ports()
                        machine = private_emulator(machine_dir, ports, reuse=True)
                        machine.boot(); machine.command('daytime')
                        if protect_bridge_terminals(machine):
                            LOG.info('Disabled optional terminal initializer on private lab disk; rebooting cleanly')
                            machine.command('r opr','OPR>')
                            machine.child.send('set ksys now\r')
                            machine.child.expect_exact('KSYS processing completed',timeout=120)
                            machine.stop(); machine = None
                            ports = reserve_ports()
                            machine = private_emulator(machine_dir, ports, reuse=True)
                            machine.boot(); machine.command('daytime')
                        if 'STOMPR' in machine.command('systat'):
                            raise RuntimeError('Terminal initializer is still active on private bridge guest')
                        bridge = startup.enter_context(PersonaBridge(machine, ports, store))
                        break
                    except Exception:
                        startup.close()
                        if machine is not None: machine.stop(); machine = None
                        if attempt + 1 == BOOT_ATTEMPTS: raise
                        LOG.info('Retrying private guest startup (%s/%s)', attempt + 2, BOOT_ATTEMPTS)
                with startup:
                    asyncio.run(serve(machine, bridge, state, port))
                machine.command('r opr', 'OPR>')
                machine.child.send('set ksys now\r')
                machine.child.expect_exact('KSYS processing completed', timeout=120)
        finally:
            if machine is not None: machine.stop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir', type=Path, default=DEFAULT_STATE)
    parser.add_argument('--prepared-runtime', type=Path, default=DEFAULT_IMAGE)
    parser.add_argument('--port', type=int, default=DEFAULT_HTTP_PORT)
    args = parser.parse_args()
    if not 0 < args.port < 65536: parser.error('Port must be 1–65535')
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s: %(message)s')
    def interrupt_startup(signum, frame): raise KeyboardInterrupt()
    previous = signal.signal(signal.SIGTERM, interrupt_startup)
    try: run(args.state_dir, args.prepared_runtime, args.port)
    except KeyboardInterrupt: pass
    except Exception as error:
        LOG.error('External lab failed: %s; inspect its private state directory', type(error).__name__)
        raise SystemExit(1) from None
    finally: signal.signal(signal.SIGTERM, previous)


if __name__ == '__main__': main()
