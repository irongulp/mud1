"""Focused original-controller KSYS probe on fresh, private starter-image copies.

Raw terminal/memory/history evidence is private. Only explicitly selected counts,
addresses, job states and lifecycle results enter summary.json for CI artifacts.
No game credentials, persona creation, external compilation or shutdown retry.
"""
import argparse
from collections import Counter
from contextlib import contextmanager, redirect_stdout
import hashlib
import json
from pathlib import Path
import platform
import re
import socket
import time
import uuid

from server.monitor_bootstrap import SimulatorConsole
from server.runtime import MONITOR_PROMPT, Runtime
from tools.audit_archwizards import Guest, logoff
from tools.deploy import install_image, sha256
from tools.guest_control import ControlError
from tools.persona_snapshot import publish_private
from tools.terminal_config import protect_bridge_terminals

ROOT = Path(__file__).resolve().parents[1]
ALLOCATION_FIRST = 0o531142
ALLOCATION_LAST = 0o531156
HISTORY_ENTRIES = 512
HISTORY_CAPACITY = 65536
SAMPLE_SECONDS = .2
CAPTURE_TIMEOUT = 30
MAX_PROBE_GUESTS = 2
MAX_BOOTS = 3
MAX_SETTLE_SECONDS = 120
PAGE_LIMIT = 4096


def history_summary(text):
    rows = re.findall(r'(?m)^([0-7]{6})\s+([0-7]{12})\s+[0-7]{6}\s+[^\r\n]+', text)
    counts = Counter(int(pc, 8) for pc, _ in rows)
    return dict(samples=len(rows), top_pcs=[dict(pc=f'{pc:06o}', count=count)
        for pc, count in counts.most_common(20)],
        allocation_wait_samples=sum(count for pc, count in counts.items()
                                    if ALLOCATION_FIRST <= pc <= ALLOCATION_LAST))


def job_summary(text):
    count = re.search(r'(\d+) Jobs? in use out of ', text)
    header = re.search(r'Job\s+Who\s+Line#\s+What\s+Size\(P\)\s+State', text)
    rows = []
    if header:
        rows = re.findall(r'(?m)^\s*(\d+)\s+(?:\[OPR\]|\d+,\d+)\s+\S+\s+'
                          r'(\w+)\s+(\d+)(?:\+\w+)?\s+(\w+)',
                          text[header.end():].split('High Segments:', 1)[0])
    complete = bool(count and header and len(rows) == int(count.group(1))
                    and all(marker in text for marker in
                            ('High Segments:', 'No busy devices', 'System File Structures:', 'Total Free ')))
    return dict(complete=complete, jobs=len(rows), batcon=[dict(job=int(job), pages=int(pages), state=state)
        for job, name, pages, state in rows if name == 'BATCON'])


@contextmanager
def private_console(child):
    names = ('logfile', 'logfile_read', 'logfile_send')
    saved = {name: getattr(child, name) for name in names}
    try:
        for name in names:
            setattr(child, name, None)
        yield
    except BaseException:
        # A partial private response may remain buffered. Keep logging disabled
        # through teardown rather than leaking it to the operator transcript.
        raise
    else:
        for name, stream in saved.items():
            setattr(child, name, stream)


def private_json(path, value):
    publish_private(path, lambda stream: stream.write((json.dumps(value, indent=2)+'\n').encode()))


class ProbeRuntime(Runtime):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.probe = {}
        self.capture_directory = self.state/'batcon-failures'/uuid.uuid4().hex

    def command(self, text, *args, **kwargs):
        try:
            return super().command(text, *args, **kwargs)
        except Exception as error:
            if text == 'set ksys now' and not (isinstance(error, ControlError) and not error.submitted):
                try:
                    self.capture_failure()
                except Exception as capture_error:
                    self.probe['capture_error_type'] = type(capture_error).__name__
                finally:
                    if self.capture_directory.is_dir():
                        try:
                            private_json(self.capture_directory/'summary.json', self.probe)
                        except OSError as publish_error:
                            self.probe['capture_publish_error_type'] = type(publish_error).__name__
            raise

    def capture_failure(self):
        self.capture_directory.parent.mkdir(mode=0o700, exist_ok=True)
        self.capture_directory.mkdir(mode=0o700)
        output = self.child.before
        private_json(self.capture_directory/'ksys-response.private.json', dict(output=output))
        self.probe.update(ksys_queued='Event KSYS queued' in output,
                          native_batcon_failed='BATCON failed to startup' in output)
        console = SimulatorConsole(self.child)
        console.deadline = time.monotonic()+CAPTURE_TIMEOUT
        raw = {}
        with private_console(self.child):
            try:
                console.halt()
                raw['registers_before'] = {name: console.register(name)
                    for name in ('PC', 'FLAGS', 'UBR', 'PION', 'PIACT')}
                console.command('set cpu history='+str(HISTORY_CAPACITY))
                console.resume()
                time.sleep(SAMPLE_SECONDS)
                console.halt()
                raw['registers_after'] = {name: console.register(name)
                    for name in ('PC', 'FLAGS', 'UBR', 'PION', 'PIACT')}
                history = console.command('show cpu history='+str(HISTORY_ENTRIES))
                raw['history'] = history
                self.probe['history'] = history_summary(history)
                code = console.words(ALLOCATION_FIRST, ALLOCATION_LAST)
                raw['allocation_code'] = {f'{address:o}': f'{word:012o}' for address, word in code.items()}
                self.probe['allocation_code_sha256'] = hashlib.sha256(
                    json.dumps(raw['allocation_code'], sort_keys=True).encode()).hexdigest()
                # Publish page counts only after checking the observed MOVE/ADD
                # instructions are direct references in the pinned monitor loop.
                values = {}
                for offset, name in enumerate(('cortal', 'pagouc', 'pagipq', 'pagsnc', 'paginc')):
                    word = code[ALLOCATION_FIRST+offset]
                    opcode, ac = word >> 27, (word >> 23) & 0o17
                    if (opcode != (0o200 if offset == 0 else 0o270) or ac != 1
                            or word & 0o37000000):
                        values = {}
                        break
                    address = word & 0o777777
                    value = console.words(address)[address]
                    if not 0 <= value <= PAGE_LIMIT:
                        values = {}
                        break
                    values[name] = value
                self.probe['allocation_page_counts'] = values
                console.command('set cpu history=0')
            finally:
                private_json(self.capture_directory/'capture.private.json', raw)
                if console.at_prompt:
                    console.resume()
            # Read native job state only after preserving the unperturbed sample.
            # Ctrl-C belongs to the fixture's CTY operator, never another job.
            self.control_prompt = None
            self.child.send('\x03\x03')
            self.child.expect_exact('^C', timeout=5)
            self.child.expect(MONITOR_PROMPT, timeout=5)
            self.control_prompt = MONITOR_PROMPT
            status = super().command('systat', timeout=15)
            private_json(self.capture_directory/'systat-after.private.json', dict(output=status))
            self.probe['jobs_after'] = job_summary(status)


def run(output, archive, executable, *, boots=MAX_BOOTS, guests=MAX_PROBE_GUESTS, settle=30):
    if not 1 <= boots <= MAX_BOOTS or not 0 <= guests <= MAX_PROBE_GUESTS or not 0 <= settle <= MAX_SETTLE_SECONDS:
        raise ValueError('Probe bounds exceeded')
    output.mkdir(mode=0o700)
    report = dict(architecture=platform.machine(), simulator_sha256=sha256(executable),
                  source='runtime-v1', guests=guests, settle_seconds=settle, observations=[])
    manifest = json.loads((ROOT/'deploy/runtime.json').read_text())
    for index in range(boots):
        state = output/f'boot-{index+1}'
        state.mkdir(mode=0o700)
        install_image(archive, manifest, state/'game')
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        runtime = ProbeRuntime(state, executable, port=port)
        held = []
        observation = dict(boot=index+1, clean=False)
        report['observations'].append(observation)
        try:
            log_path = state/'console.private.log'
            with log_path.open('x') as log, redirect_stdout(log):
                log_path.chmod(0o600)
                try:
                    runtime.boot()
                    # Match deployed external TTY policy without compiling or
                    # substituting the external engine or creating a database.
                    observation['terminal_config_changed'] = protect_bridge_terminals(runtime)
                    if observation['terminal_config_changed']:
                        observation['configuration_shutdown_clean'] = runtime.stop()
                        if not observation['configuration_shutdown_clean']:
                            raise RuntimeError('Configuration shutdown failed; no reboot allowed')
                        runtime = ProbeRuntime(state, executable, port=port)
                        runtime.boot()
                    for _ in range(guests):
                        held.append(Guest(port, 'mudguest', []))
                    time.sleep(settle)
                    for guest in held:
                        guest.connection.write(b'\x03\x03')
                        guest.expect(b'^C')
                        guest.expect(b'\n.')
                        logoff(guest.connection)
                    held.clear()
                    status = runtime.command('systat')
                    private_json(state/'systat-before.private.json', dict(output=status))
                    observation['jobs_before'] = job_summary(status)
                finally:
                    for guest in held:
                        guest.connection.close()
                    if runtime.child is not None:
                        observation['clean'] = runtime.stop()
                    observation.update(runtime.probe)
        except Exception as error:
            observation['error_type'] = type(error).__name__
        finally:
            if runtime.child is not None:
                runtime.child.close(force=True)
            private_json(output/('summary-'+str(index+1)+'.json'), report)
        if not observation['clean'] or 'error_type' in observation:
            raise RuntimeError('Focused BATCON probe failed; inspect private evidence and summary')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--simh', type=Path, required=True)
    parser.add_argument('--boots', type=int, default=MAX_BOOTS)
    parser.add_argument('--guests', type=int, default=MAX_PROBE_GUESTS)
    parser.add_argument('--settle-seconds', type=float, default=30)
    args = parser.parse_args()
    run(args.output.resolve(), args.archive.resolve(strict=True), args.simh.resolve(strict=True),
        boots=args.boots, guests=args.guests, settle=args.settle_seconds)


if __name__ == '__main__':
    main()
