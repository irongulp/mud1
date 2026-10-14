"""Foreground, systemd-notifying supervisor for the original TOPS-10 runtime."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
import re
from pathlib import Path
import signal
import socket
import sys
import threading
import tempfile
import time

from tools.guest_control import ControlError, COPY_READY_DELAY, console_byte, console_notice, operator_redraw, submit_line

BOOT_TIMEOUT = 60
SHUTDOWN_TIMEOUT = 90
BOOT_ATTEMPTS = 3
RETRY_DELAY = 3
BOOT_CALIBRATION_SECONDS = 22
DEPLOYMENT_MIPS = 5
LISTENER_WAIT=90
MONITOR_PROMPT = r'\n\.'
OPERATOR_PROMPT = 'OPR>'
MAX_OPERATOR_NOTICES = 16  # Startup/accounting plus completed readiness probes.
BATCH_DRAIN_TIMEOUT = 10
BATCH_DRAIN_POLL = .25
_BATCH_SHUTDOWN = r'\r?\n *[0-9]{1,2}:[0-9]{2}:[0-9]{2} +Batch-Stream ([01]) +-- Shutdown --\r?\n'
BOOT_DIAGNOSTIC_CHARS = 8192
BOOT_PROMPTS = frozenset(('BOOT>', 'Why reload:', 'Date:', 'Time:', 'Startup option:', OPERATOR_PROMPT))


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


def batch_pty_jobs(output):
    """Read the native SYSTAT job table, including BATCON's reusable PTY jobs."""
    text = output.replace('\r', '').expandtabs(8)
    table = re.search(r'(?m)^Job +Who +Line# +What +Size\(P\) +State +Run Time\n'
                      r'([\s\S]*?)^High Segments:', text)
    if table is None:
        raise RuntimeError('Native batch drain needs a complete SYSTAT job table')
    return [int(job) for job in re.findall(r'(?m)^ *([0-9]+) +\S+ +P[0-9]+J[0-9]+(?: +|$)', table[1])]


def probe_game(port):
    from tools.audit_archwizards import Guest, logoff
    guest = Guest(port, 'mudguest', [])
    try:
        guest.connection.write(b'\x03\x03')
        guest.expect(b'\n.')
        logoff(guest.connection, complete=True)
    finally:
        guest.connection.close()


class Runtime:
    def __init__(self, state, executable, port=2020, idle=False,persona_config=None, *, browser_terminals=False):
        self.state, self.executable = Path(state), str(executable)
        self.port, self.idle = port, idle
        self.child = None
        self.booted = False
        self.stopping = threading.Event()
        self.persona_config=persona_config
        self.bridge=self.store=None
        self.control_prompt = None
        self.batch_ready = False
        self.browser_terminals = browser_terminals
        self.terminal_rebooted = False
        self.boot_phase = None

    def verify_batch(self):
        from tools.batch_readiness import BatchReadinessError, ensure_batch_ready
        try:
            proof = ensure_batch_ready(self.port)
        except BatchReadinessError as error:
            print(str(error), flush=True)
            raise
        print(f'Native batch readiness verified: {proof["name"]} request {proof["request"]}', flush=True)

    def _submit_control(self, text, deadline, *, operator=False):
        delay = self.child.delaybeforesend
        self.child.delaybeforesend = 0
        try:
            return submit_line(text, lambda data: self.child.send(data.decode('ascii')),
                               lambda timeout: console_byte(self.child, timeout),
                               timeout=max(0, deadline - time.monotonic()), notice=console_notice,
                               redraw=operator_redraw if operator else None).decode('ascii')
        finally:
            self.child.delaybeforesend = delay

    def command(self,text,prompt=MONITOR_PROMPT, *, timeout=BOOT_TIMEOUT):
        if self.control_prompt not in (MONITOR_PROMPT, OPERATOR_PROMPT):
            raise RuntimeError('Guest control command requires a confirmed prompt')
        ready_prompt = self.control_prompt
        self.control_prompt = None
        deadline = time.monotonic() + timeout
        for attempt in range(MAX_OPERATOR_NOTICES + 1):
            try:
                echo = self._submit_control(text, deadline, operator=ready_prompt == OPERATOR_PROMPT)
                break
            except ControlError as error:
                # OPR emits queued operator notices after its initial prompt.
                # Only resynchronize when no input has been sent: never search
                # through a bad echo or replay a partly/fully submitted command.
                if (ready_prompt != OPERATOR_PROMPT or error.input_started or error.submitted
                        or attempt == MAX_OPERATOR_NOTICES or time.monotonic() >= deadline):
                    raise
                self.child.expect(OPERATOR_PROMPT, timeout=max(0, deadline - time.monotonic()))
        self.child.expect(prompt, timeout=max(0, deadline - time.monotonic()))
        output = echo + self.child.before + self.child.after
        if prompt in (MONITOR_PROMPT, OPERATOR_PROMPT):
            self.control_prompt = prompt
        return output

    def copy_text(self, filename, text):
        """Explicit COPY dialogue. Callers must stage and verify before use."""
        import re
        if not re.fullmatch(r'(?:sys:)?[a-z0-9]{1,6}\.[a-z0-9]{1,3}', filename):
            raise ValueError('Invalid guest staging filename')
        if self.control_prompt != MONITOR_PROMPT:
            raise RuntimeError('Guest COPY requires a confirmed monitor prompt')
        self.control_prompt = None
        deadline = time.monotonic() + BOOT_TIMEOUT
        self._submit_control('copy ' + filename + '=tty:', deadline)
        self.child.expect_exact('\r\n', timeout=max(0, deadline - time.monotonic()))
        time.sleep(COPY_READY_DELAY)
        for line in text.splitlines():
            if time.monotonic() >= deadline:
                raise TimeoutError('Guest COPY deadline expired')
            if line:
                self._submit_control(line, deadline)
            else:
                self.child.send('\r')
            self.child.expect_exact('\r\n', timeout=max(0, deadline - time.monotonic()))
            time.sleep(COPY_READY_DELAY)
        if time.monotonic() >= deadline:
            raise TimeoutError('Guest COPY deadline expired')
        self.child.sendcontrol('z')
        self.child.expect(MONITOR_PROMPT, timeout=max(0, deadline - time.monotonic()))
        self.control_prompt = MONITOR_PROMPT

    def drain_batch(self, *, timeout=BATCH_DRAIN_TIMEOUT):
        """Release the supplied SYSTEM.CMD's two ordinary streams before KSYS.

        A completed probe leaves reusable logged-in PTY jobs owned by BATCON.
        The independent KSYS worker cannot seize them while that owner retains
        them. Native SHUTDOWN releases them; never kill or impersonate the jobs.
        """
        deadline = time.monotonic() + min(timeout, BATCH_DRAIN_TIMEOUT)
        output = self.command('shutdown batch-stream 0:1', OPERATOR_PROMPT,
                              timeout=max(0, deadline - time.monotonic()))
        self.control_prompt = None
        seen = set(re.findall(_BATCH_SHUTDOWN, output))
        while seen != {'0', '1'}:
            self.child.expect(_BATCH_SHUTDOWN, timeout=max(0, deadline - time.monotonic()))
            output = self.child.before + self.child.after
            seen.update(re.findall(_BATCH_SHUTDOWN, output))
        if not output.endswith(OPERATOR_PROMPT):
            self.child.expect_exact(OPERATOR_PROMPT, timeout=max(0, deadline - time.monotonic()))
        self.control_prompt = OPERATOR_PROMPT
        self.command('exit', timeout=max(0, deadline - time.monotonic()))
        # SHUTDOWN acknowledges its request before BATCON finishes P$CLOS.
        # Witness job release, rather than replacing that race with a sleep.
        while batch_pty_jobs(self.command('systat', timeout=max(0, deadline - time.monotonic()))):
            if time.monotonic() >= deadline:
                raise TimeoutError('Native batch jobs were not released before KSYS')
            time.sleep(min(BATCH_DRAIN_POLL, max(0, deadline - time.monotonic())))
        self.command('r opr', OPERATOR_PROMPT, timeout=max(0, deadline - time.monotonic()))

    def boot(self):
        import pexpect
        self.boot_phase = 'listener'
        wait_listener(self.port)
        self.control_prompt = None
        self.batch_ready = False
        config = self.state / 'runtime.ini'
        ports=None
        if self.persona_config:
            from server.persona_bridge import reserve_ports
            ports=reserve_ports()
        config.write_text(simulator_config(self.state, self.port, self.idle,bridge_ports=ports))
        self.boot_phase = 'spawn'
        self.child = pexpect.spawn(self.executable, [str(config)], cwd=str(self.state),
                                   encoding='ascii', codec_errors='replace', timeout=BOOT_TIMEOUT)
        self.child.logfile_read = sys.stdout
        clock = datetime.now(timezone.utc)
        for prompt, response in (('BOOT>', '/tm02'), ('Why reload:', 'sched'),
                                 ('Date:', clock.strftime('%m-%d-%Y')),
                                 ('Time:', clock.strftime('%H%M%S')),
                                 ('Startup option:', 'g'), ('OPR>', 'exit')):
            self.boot_phase = prompt
            self.child.expect_exact(prompt)
            if self.stopping.is_set():
                raise InterruptedError('Shutdown requested during boot')
            if prompt == 'Startup option:' and self.stopping.wait(BOOT_CALIBRATION_SECONDS):
                raise InterruptedError('Shutdown requested during calibration')
            if prompt == OPERATOR_PROMPT:
                self.control_prompt = OPERATOR_PROMPT
                self.command(response)
            else:
                self.child.send(response + '\r')
        self.booted = True
        self.boot_phase = 'private-readiness'
        if self.browser_terminals:
            from tools.terminal_config import protect_bridge_terminals
            if protect_bridge_terminals(self):
                if self.terminal_rebooted:
                    raise RuntimeError('Browser terminal configuration did not survive reboot')
                self.terminal_rebooted = True
                self.verify_batch()
                self.batch_ready = True
                if not self.stop():
                    raise RuntimeError('Browser terminal setup requires a confirmed clean shutdown')
                self.boot()
                return
            if 'STOMPR' in self.command('systat'):
                raise RuntimeError('Terminal initializer still owns browser lines; admission blocked')
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
        # Preserve the existing private transport/bootstrap check first. Public
        # readiness is still withheld until native batch execution also passes.
        self.verify_batch()
        self.batch_ready = True
        self.boot_phase = 'ready'

    def record_startup_failure(self, attempt, failure):
        """Private bounded prompt evidence, never exception payloads or game data."""
        directory = self.state / 'boot-diagnostics'
        directory.mkdir(mode=0o700, exist_ok=True)
        evidence = {'version': 1, 'attempt': attempt, 'phase': self.boot_phase,
                    'error': type(failure).__name__, 'booted': self.booted,
                    'batch_ready': self.batch_ready}
        if self.boot_phase in BOOT_PROMPTS and self.child is not None:
            output = self.child.before
            if isinstance(output, str):
                evidence['pending_output'] = output[-BOOT_DIAGNOSTIC_CHARS:]
        descriptor, filename = tempfile.mkstemp(prefix='attempt-', suffix='.json', dir=directory)
        with os.fdopen(descriptor, 'w') as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(evidence, stream)
            stream.write('\n')
        return Path(filename)

    def start(self):
        """Bounded cold-boot recovery only; caller work starts after this returns."""
        if self.child is not None or self.bridge is not None or self.store is not None:
            raise RuntimeError('Cannot start another guest while runtime resources are owned')
        (self.state / 'shutdown.json').write_text('{"clean": false}\n')
        for attempt in range(BOOT_ATTEMPTS):
            try:
                self.boot()
                return
            except BaseException as failure:
                print(f'Guest startup attempt {attempt + 1}/{BOOT_ATTEMPTS} failed '
                      f'at {self.boot_phase or "unknown"}: {type(failure).__name__}', flush=True)
                try:
                    self.record_startup_failure(attempt + 1, failure)
                except OSError as diagnostic:
                    print('Startup evidence unavailable: ' + type(diagnostic).__name__, flush=True)
                try:
                    self.stop()
                except Exception as cleanup:
                    print('Startup cleanup failed: ' + type(cleanup).__name__ +
                          '; original startup failure retained, no further guest started.', flush=True)
                    raise failure from None
                if self.child is not None or self.bridge is not None or self.store is not None:
                    print('Startup resources remain; no further guest started.', flush=True)
                    raise
                if (not isinstance(failure, Exception) or self.stopping.is_set()
                        or attempt + 1 == BOOT_ATTEMPTS):
                    raise
                print(f'Retrying guest boot ({attempt + 2}/{BOOT_ATTEMPTS})', flush=True)
                time.sleep(RETRY_DELAY)

    @contextmanager
    def session(self):
        """Private controller scope: recover startup, never replay its body."""
        with (self.state / 'runtime.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            started = False
            try:
                self.start()
                started = True
                yield self
            finally:
                failure = sys.exc_info()[1]
                # start owns failed-start cleanup. Never repeat that shutdown
                # just because its original exception crossed this scope.
                if started:
                    try:
                        clean = self.stop()
                    except Exception as cleanup:
                        if failure is None:
                            raise
                        print('Private guest cleanup failed: ' + type(cleanup).__name__ +
                              '; original failure retained.', flush=True)
                    else:
                        if not clean:
                            if failure is None:
                                raise RuntimeError('Private guest shutdown was not confirmed clean')
                            print('Private guest shutdown was not confirmed; original failure retained.', flush=True)

    def stop(self):
        clean = False
        if self.child is not None:
            try:
                if self.child.isalive():
                    if self.booted:
                        batch_verified = False
                        if self.batch_ready:
                            try:
                                self.verify_batch()
                                batch_verified = True
                            except Exception as error:
                                print('Native batch shutdown preflight failed: ' + type(error).__name__ +
                                      '; backup remains blocked.', flush=True)
                        try:
                            deadline = time.monotonic() + SHUTDOWN_TIMEOUT
                            if self.control_prompt not in (MONITOR_PROMPT, OPERATOR_PROMPT):
                                # A failed COPY may still be accepting file data.
                                # Interrupt and witness a monitor before sending
                                # any operator commands, never type R OPR into it.
                                self.child.send('\x03\x03')
                                self.child.expect_exact('^C', timeout=max(0, deadline - time.monotonic()))
                                self.child.expect(MONITOR_PROMPT, timeout=max(0, deadline - time.monotonic()))
                                self.control_prompt = MONITOR_PROMPT
                            if self.control_prompt == MONITOR_PROMPT:
                                self.command('r opr', OPERATOR_PROMPT,
                                             timeout=max(0, deadline - time.monotonic()))
                            if self.batch_ready:
                                self.drain_batch(timeout=max(0, deadline - time.monotonic()))
                            self.command('set ksys now', 'KSYS processing completed',
                                         timeout=max(0, deadline - time.monotonic()))
                            clean = batch_verified
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
                self.control_prompt = None
                self.batch_ready = False
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
                self.start()
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
                failure = sys.exc_info()[1]
                try:
                    self.stop()
                except Exception as cleanup:
                    if failure is None:
                        raise
                    print('Runtime cleanup failed: ' + type(cleanup).__name__ +
                          '; original failure retained.', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--simh', type=Path, required=True)
    parser.add_argument('--port', type=int, default=2020)
    parser.add_argument('--idle', action='store_true', help='Experimental; validate lifecycle on the target host first')
    parser.add_argument('--persona-config',type=Path,default=os.environ.get('MUD86_PERSONA_CONFIG'))
    parser.add_argument('--browser-terminals', action='store_true',
                        help='Disable the optional line-claiming initializer on this deployed browser guest')
    args = parser.parse_args()
    Runtime(args.state.resolve(), args.simh.resolve(), args.port, args.idle,args.persona_config,
            browser_terminals=args.browser_terminals).run()


if __name__ == '__main__':
    main()
