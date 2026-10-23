"""Owned local gameplay guest with a guarded monitor bootstrap on every boot."""
import json
import re
import time

from server.monitor_bootstrap import MonitorBootstrap
from server.runtime import BOOT_TIMEOUT, SHUTDOWN_TIMEOUT, BOOT_CALIBRATION_SECONDS
from tools.guest_control import ControlError, COPY_READY_DELAY, console_byte, console_notice, operator_redraw, submit_line
from tools.persona_snapshot import publish_private

MONITOR_PROMPT = r'\n\.'
OPERATOR_PROMPT = 'OPR>'
MAX_OPERATOR_NOTICES = 8
QUEUE_RESPONSE = r'-- (?:The queues are empty|System Queues Listing) --'


class LocalGuest:
    def __init__(self, emulator):
        self.emulator = emulator
        self.child, self.port, self.directory = emulator.child, emulator.port, emulator.directory
        self.scope = MonitorBootstrap(self.child, self.directory)
        self.control_prompt = None
        self.booted = self.stopped = self.clean = False
        self._batch_verified = False
        self.failure = None

    @property
    def monitor_scope_verified(self):
        return self.booted and not self.stopped and self.scope.verified and self.child.isalive()

    @property
    def batch_ready(self):
        return self.monitor_scope_verified and self._batch_verified

    def boot(self):
        phase = 'loader'
        try:
            self.child.expect_exact('BOOT>', timeout=BOOT_TIMEOUT)
            self.scope.arm_from_loader()
            self.child.send('/tm02\r')
            for prompt, answer in (('Why reload:', 'sched'), ('Date:', '09-18-2026'),
                                   ('Time:', '030000'), ('Startup option:', 'g')):
                phase = prompt
                self.child.expect_exact(prompt, timeout=BOOT_TIMEOUT)
                if prompt == 'Startup option:':
                    time.sleep(BOOT_CALIBRATION_SECONDS)
                self.child.send(answer+'\r')
            phase = 'monitor-correction'
            self.scope.install_before_operator(BOOT_TIMEOUT)
            self.control_prompt = OPERATOR_PROMPT
            phase = 'operator-exit'
            self.command('exit')
            self.booted = True
        except BaseException as error:
            if self.failure is None:
                self.failure = dict(phase=phase, error_type=type(error).__name__)
            try:
                self.scope.record('boot-failed', failure=self.failure)
            except OSError:
                pass  # Evidence failure must not replace a non-retryable boot error.
            raise

    def _submit_control(self, text, deadline, *, operator=False):
        delay = self.child.delaybeforesend
        self.child.delaybeforesend = 0
        try:
            return submit_line(text, lambda data: self.child.send(data.decode('ascii')),
                lambda remaining: console_byte(self.child, remaining),
                timeout=max(0, deadline-time.monotonic()), notice=console_notice,
                redraw=operator_redraw if operator else None).decode('ascii')
        finally:
            self.child.delaybeforesend = delay

    def command(self, text, prompt=MONITOR_PROMPT, *, timeout=BOOT_TIMEOUT):
        if self.control_prompt not in (MONITOR_PROMPT, OPERATOR_PROMPT):
            raise RuntimeError('Guest command requires a confirmed prompt')
        ready = self.control_prompt
        self.control_prompt = None
        deadline = time.monotonic() + timeout
        try:
            for attempt in range(MAX_OPERATOR_NOTICES + 1):
                try:
                    echo = self._submit_control(text, deadline, operator=ready == OPERATOR_PROMPT)
                    break
                except ControlError as error:
                    if (ready != OPERATOR_PROMPT or error.input_started or error.submitted
                            or attempt == MAX_OPERATOR_NOTICES or time.monotonic() >= deadline):
                        raise
                    self.child.expect_exact(OPERATOR_PROMPT, timeout=max(0, deadline-time.monotonic()))
            self.child.expect(prompt, timeout=max(0, deadline-time.monotonic()))
            result = echo+self.child.before+self.child.after
            if prompt in (MONITOR_PROMPT, OPERATOR_PROMPT):
                self.control_prompt = prompt
            return result
        except Exception as error:
            if self.failure is None:
                self.failure = dict(command=text, error_type=type(error).__name__,
                                    input_started=getattr(error, 'input_started', True),
                                    submitted=getattr(error, 'submitted', True))
            raise

    def copy_text(self, filename, text, *, timeout=BOOT_TIMEOUT):
        """Owned COPY-from-TTY dialogue; a failed echo never receives Enter/EOF."""
        if not re.fullmatch(r'(?:sys:)?[a-z0-9]{1,6}\.[a-z0-9]{1,3}', filename):
            raise ValueError('Invalid guest configuration filename')
        if self.control_prompt != MONITOR_PROMPT:
            raise RuntimeError('COPY requires a confirmed monitor prompt')
        self.control_prompt = None
        deadline = time.monotonic()+timeout
        phase = 'copy-header'
        try:
            self._submit_control('copy '+filename+'=tty:', deadline)
            self.child.expect_exact('\r\n', timeout=max(0, deadline-time.monotonic()))
            time.sleep(COPY_READY_DELAY)
            phase = 'copy-data'
            for line in text.splitlines():
                if time.monotonic() >= deadline:
                    raise TimeoutError('COPY deadline expired')
                if line:
                    self._submit_control(line, deadline)
                else:
                    self.child.send('\r')
                self.child.expect_exact('\r\n', timeout=max(0, deadline-time.monotonic()))
                time.sleep(COPY_READY_DELAY)
            if time.monotonic() >= deadline:
                raise TimeoutError('COPY deadline expired')
            phase = 'copy-eof'
            self.child.sendcontrol('z')
            self.child.expect(MONITOR_PROMPT, timeout=max(0, deadline-time.monotonic()))
            self.control_prompt = MONITOR_PROMPT
        except Exception as error:
            if self.failure is None:
                self.failure = dict(command='copy '+filename+'=tty:', phase=phase,
                    error_type=type(error).__name__, input_started=getattr(error, 'input_started', True),
                    submitted=getattr(error, 'submitted', True))
            raise

    def stop(self):
        if self.stopped:
            return self.clean
        goodbye = False
        try:
            if self.child.isalive() and self.booted:
                try:
                    deadline = time.monotonic() + SHUTDOWN_TIMEOUT
                    if self.control_prompt not in (MONITOR_PROMPT, OPERATOR_PROMPT):
                        # Abort unknown dialogue before OS commands, without replay.
                        self.child.send('\x03\x03')
                        self.child.expect_exact('^C', timeout=max(0, deadline-time.monotonic()))
                        self.child.expect(MONITOR_PROMPT, timeout=max(0, deadline-time.monotonic()))
                        self.control_prompt = MONITOR_PROMPT
                    if self.control_prompt == MONITOR_PROMPT:
                        self.command('r opr', OPERATOR_PROMPT, timeout=max(0, deadline-time.monotonic()))
                    self.command('show queues', QUEUE_RESPONSE,
                                 timeout=max(0, deadline-time.monotonic()))
                    self.child.expect_exact(OPERATOR_PROMPT, timeout=max(0, deadline-time.monotonic()))
                    self.control_prompt = OPERATOR_PROMPT
                    self.command('set ksys now', 'KSYS processing completed',
                                 timeout=max(0, deadline-time.monotonic()))
                    self.clean = True
                except Exception:
                    self.clean = False
            if self.child.isalive():
                self.scope.console.deadline = None
                self.scope.console.halt()
                self.child.send('quit\r')
                self.child.expect_exact('Goodbye', timeout=BOOT_TIMEOUT)
                goodbye = True
        except Exception:
            self.clean = False
        finally:
            self.child.close(force=True)
            self.emulator.log.close()
            self.stopped = True
            self.clean = self.clean and goodbye and not self.child.isalive()
            report = dict(clean=self.clean, monitor_scope_verified=self.scope.verified,
                          simulator_goodbye_seen=goodbye, process_exited=not self.child.isalive(),
                          failure=self.failure)
            publish_private(self.scope.evidence/'shutdown.json',
                            lambda stream: stream.write(json.dumps(report, indent=2).encode('ascii')+b'\n'))
        return self.clean
