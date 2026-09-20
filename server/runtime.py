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


def simulator_config(state, port, idle):
    state = Path(state).resolve()
    if any(char in str(state) for char in '\r\n"') or not 0 < port < 65536:
        raise ValueError('Invalid simulator path or port')
    return (f'set tim y2k\nset dz 8b\nattach -e rp0 "{state / "game/guest.dsk"}"\n'
            f'attach -am dz 127.0.0.1:{port},SPEED=*8\nset tu0 locked\n'
            f'attach -e tu0 "{state / "game/t10boot.tap"}"\n'
            f'set cpu {"idle" if idle else "noidle"}\n'
            + ('' if idle else f'set throttle {DEPLOYMENT_MIPS}M\n') + 'boot tu0\n')


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
    def __init__(self, state, executable, port=2020, idle=False):
        self.state, self.executable = Path(state), str(executable)
        self.port, self.idle = port, idle
        self.child = None
        self.booted = False
        self.stopping = threading.Event()

    def boot(self):
        import pexpect
        config = self.state / 'runtime.ini'
        config.write_text(simulator_config(self.state, self.port, self.idle))
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
        probe_game(self.port)

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
                    self.child.sendcontrol('e')
                    self.child.expect_exact('sim>')
                    self.child.send('quit\r')
                    self.child.expect_exact('Goodbye')
            finally:
                self.child.close(force=True)
                self.child = None
                self.booted = False
        (self.state / 'shutdown.json').write_text(json.dumps({'clean': clean}) + '\n')
        return clean

    def run(self):
        import pexpect
        self.state.mkdir(parents=True, exist_ok=True)
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
    args = parser.parse_args()
    Runtime(args.state.resolve(), args.simh.resolve(), args.port, args.idle).run()


if __name__ == '__main__':
    main()
