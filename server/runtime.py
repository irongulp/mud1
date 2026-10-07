"""Foreground, systemd-notifying supervisor for the original TOPS-10 runtime."""
import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import signal
import socket
import sys
import threading
import time

BOOT_TIMEOUT = 60
SHUTDOWN_TIMEOUT = 90
BOOT_ATTEMPTS = 3
RETRY_DELAY = 3
BOOT_CALIBRATION_SECONDS = 22
DEPLOYMENT_MIPS = 5
LISTENER_WAIT=90


def wait_listener(port,timeout=LISTENER_WAIT):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        try:
            with socket.socket() as probe: probe.bind(('127.0.0.1',port))
            return
        except OSError: time.sleep(1)
    raise TimeoutError('Runtime listener is still occupied; no guest was booted without transport')


def simulator_config(state, port, idle, *, bridge_ports=None):
    state = Path(state).resolve()
    if any(char in str(state) for char in '\r\n"') or not 0 < port < 65536:
        raise ValueError('Invalid simulator path or port')
    raw=''
    if bridge_ports is not None:
        if set(bridge_ports)!={6,7} or any(type(value) is not int or not 0<value<65536 for value in bridge_ports.values()):
            raise ValueError('Invalid external storage terminal pool')
        raw=''.join(f'attach dz Line={line},127.0.0.1:{value};notelnet\n' for line,value in sorted(bridge_ports.items()))
    return (f'set tim y2k\nset dz 8b\nattach -e rp0 "{state / "game/guest.dsk"}"\n'
            f'attach -am dz 127.0.0.1:{port},SPEED=*8\nset tu0 locked\n'
            f'attach -e tu0 "{state / "game/t10boot.tap"}"\n'
            f'set cpu {"idle" if idle else "noidle"}\n'
            + ('' if idle else f'set throttle {DEPLOYMENT_MIPS}M\n') + raw+'boot tu0\n')


def notify(message):
    address = os.environ.get('NOTIFY_SOCKET')
    if address:
        if address.startswith('@'):
            address = '\0' + address[1:]
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as connection:
            connection.sendto(message.encode(), address)


def probe_game(port):
    from tools.audit_archwizards import Guest, logoff
    guest = Guest(port, 'mudguest', [])
    try:
        guest.connection.write(b'\x03\x03')
        guest.expect(b'\n.')
        logoff(guest.connection)
    finally:
        guest.connection.close()


class Runtime:
    def __init__(self, state, executable, port=2020, idle=False,persona_config=None):
        self.state, self.executable = Path(state), str(executable)
        self.port, self.idle = port, idle
        self.child = None
        self.booted = False
        self.stopping = threading.Event()
        self.persona_config=persona_config
        self.bridge=self.store=None

    def command(self,text,prompt=r'\n\.'):
        self.child.send(text+'\r'); self.child.expect(prompt)
        return self.child.before+self.child.after

    def boot(self):
        import pexpect
        wait_listener(self.port)
        config = self.state / 'runtime.ini'
        ports=None
        if self.persona_config:
            from server.persona_bridge import reserve_ports
            ports=reserve_ports()
        config.write_text(simulator_config(self.state, self.port, self.idle,bridge_ports=ports))
        self.child = pexpect.spawn(self.executable, [str(config)], cwd=str(self.state),
                                   encoding='ascii', codec_errors='replace', timeout=BOOT_TIMEOUT)
        self.child.logfile_read = sys.stdout
        clock = datetime.now(timezone.utc)
        for prompt, response in (('BOOT>', '/tm02'), ('Why reload:', 'sched'),
                                 ('Date:', clock.strftime('%m-%d-%Y')),
                                 ('Time:', clock.strftime('%H%M%S')),
                                 ('Startup option:', 'g'), ('OPR>', 'exit')):
            self.child.expect_exact(prompt)
            if self.stopping.is_set():
                raise InterruptedError('Shutdown requested during boot')
            if prompt == 'Startup option:' and self.stopping.wait(BOOT_CALIBRATION_SECONDS):
                raise InterruptedError('Shutdown requested during calibration')
            self.child.send(response + '\r')
        self.child.expect(r'\n\.')
        self.booted = True
        if self.persona_config:
            from server.persona_bridge import PersonaBridge
            from tools.persona_migrate import load_config
            from tools.persona_writes import isolated_writer
            from tools.external_guest import probe_external
            if 'STOMPR' in self.command('systat'):
                raise RuntimeError('External guest terminal initializer must be disabled before admission')
            self.store=isolated_writer(load_config(self.persona_config))
            self.bridge=PersonaBridge(self,ports,self.store).__enter__()
            probe_external(self.port,self.store)
        else: probe_game(self.port)

    def stop(self):
        clean = False
        if self.child is not None:
            try:
                if self.child.isalive():
                    if self.booted:
                        try:
                            self.child.send('r opr\r')
                            self.child.expect_exact('OPR>')
                            self.child.send('set ksys now\r')
                            self.child.expect_exact('KSYS processing completed', timeout=SHUTDOWN_TIMEOUT)
                            clean = True
                        except Exception:
                            print('Guest shutdown did not complete; next start must recover the disk.', flush=True)
                    try: self.child.expect_exact('sim>',timeout=1)
                    except Exception:
                        self.child.sendcontrol('e')
                        self.child.expect_exact('sim>')
                    self.child.send('quit\r')
                    self.child.expect_exact('Goodbye')
            finally:
                self.child.close(force=True)
                self.child = None
                self.booted = False
                if self.bridge is not None: self.bridge.__exit__(None,None,None); self.bridge=None
                if self.store is not None: self.store.close(); self.store=None
        (self.state / 'shutdown.json').write_text(json.dumps({'clean': clean}) + '\n')
        if self.bridge is not None: self.bridge.__exit__(None,None,None); self.bridge=None
        if self.store is not None: self.store.close(); self.store=None
        return clean

    def run(self):
        import pexpect
        self.state.mkdir(parents=True, exist_ok=True)
        if not self.persona_config and (self.state/'external/cutover.json').exists():
            raise RuntimeError('Native admission is disabled after external cutover begins; resume external setup')
        with (self.state / 'runtime.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            ready = self.state / 'ready'
            ready.unlink(missing_ok=True)
            (self.state / 'shutdown.json').write_text('{"clean": false}\n')
            for sig in (signal.SIGTERM, signal.SIGINT):
                signal.signal(sig, lambda *_: self.stopping.set())
            try:
                for attempt in range(BOOT_ATTEMPTS):
                    try:
                        self.boot()
                        break
                    except Exception:
                        self.stop()
                        if self.stopping.is_set() or attempt + 1 == BOOT_ATTEMPTS:
                            raise
                        print(f'Retrying guest boot ({attempt + 2}/{BOOT_ATTEMPTS})', flush=True)
                        time.sleep(RETRY_DELAY)
                ready.write_text(str(os.getpid()) + '\n')
                notify('READY=1\nSTATUS=Original MUD is ready')
                while not self.stopping.is_set():
                    if self.bridge and any(future.done() for future in self.bridge.futures):
                        raise RuntimeError('External persona listener exited')
                    try:
                        self.child.read_nonblocking(4096, timeout=1)
                    except pexpect.TIMEOUT:
                        continue
                    except pexpect.EOF:
                        raise RuntimeError('Emulator exited unexpectedly') from None
            finally:
                ready.unlink(missing_ok=True)
                notify('STOPPING=1')
                self.stop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--simh', type=Path, required=True)
    parser.add_argument('--port', type=int, default=2020)
    parser.add_argument('--idle', action='store_true', help='Experimental; validate lifecycle on the target host first')
    parser.add_argument('--persona-config',type=Path,default=os.environ.get('MUD86_PERSONA_CONFIG'))
    args = parser.parse_args()
    Runtime(args.state.resolve(), args.simh.resolve(), args.port, args.idle,args.persona_config).run()


if __name__ == '__main__':
    main()
