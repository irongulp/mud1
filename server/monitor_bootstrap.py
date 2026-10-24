"""Per-boot, fail-closed RAM correction for the local KS10 gameplay launcher."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import tempfile
import time
import uuid

from server.monitor_scope import (ADDRESS_MASK, ALLOCATION_WORDS, FINGERPRINTS,
    PATCH_ID, MonitorBootstrapError, MonitorCompatibilityError, bitmap_block,
    build_patch, digest_words, parse_words, stack_push, verify_fingerprints)
from tools.persona_snapshot import publish_private

INSTALL_TIMEOUT = 45
CONSOLE_TIMEOUT = 15
CONSOLE_OUTPUT_LIMIT = 65536
STEP_LIMIT = 100000
AC_BANK_WORDS = 128
NULL_STACK_WORDS = 128
MAX_BITMAP_WORDS = 1024
ENTRY = 0o506703
GETWDS = 0o401334
NULL_STACK_POINTER = 0o720040
POOL_POINTER = 0o15333
POOL_BASE = 0o15334
SUCCESS_HALT = 0o403
RETURN_WORD = 0o004000000402
KERNEL_FLAGS = 0o004000
NULL_UBR = 0o000100000004


class SimulatorConsole:
    """Single-owner SCP dialogue; every command requires a witnessed prompt."""
    def __init__(self, child):
        self.child = child
        self.at_prompt = False
        self.deadline = None

    def timeout(self):
        remaining = CONSOLE_TIMEOUT if self.deadline is None else self.deadline - time.monotonic()
        if remaining <= 0:
            raise MonitorBootstrapError('Monitor installation deadline expired')
        return min(CONSOLE_TIMEOUT, remaining)

    def halt(self):
        if not self.at_prompt:
            budget = self.timeout()
            self.child.sendcontrol('e')
            self.child.expect_exact('sim>', timeout=budget)
            self.at_prompt = True

    def command(self, text):
        if not self.at_prompt:
            raise MonitorBootstrapError('Simulator command requires a confirmed SCP prompt')
        if any(c in text for c in '\r\n'):
            raise ValueError('Simulator command must be one line')
        budget = self.timeout()
        self.at_prompt = False
        self.child.send(text+'\r')
        self.child.expect_exact('sim>', timeout=budget)
        self.at_prompt = True
        output = self.child.before
        if len(output) > CONSOLE_OUTPUT_LIMIT or any(marker in output for marker in (
                'Invalid argument', 'Non-existent', 'Unknown register', 'Relocation error')):
            raise MonitorBootstrapError('Simulator rejected a bounded monitor operation')
        return output

    def resume(self):
        if not self.at_prompt:
            raise MonitorBootstrapError('Resume requires a confirmed SCP prompt')
        budget = self.timeout()
        self.at_prompt = False
        self.child.send('continue\r')
        self.child.expect_exact('continue\r\n', timeout=budget)

    def register(self, name):
        output = self.command('examine '+name)
        match = re.search(r'(?m)^'+re.escape(name)+r':\s+([0-7]+)', output)
        if not match:
            raise MonitorBootstrapError('Incomplete simulator register response')
        return int(match.group(1), 8)

    def deposit(self, name, value):
        self.command(f'deposit {name} {value:o}')

    def words(self, first, last=None, *, physical=False):
        last = first if last is None else last
        mode = '' if physical else '-v -e '
        return parse_words(self.command(f'examine {mode}{first:o}-{last:o}'), first, last)


class MonitorBootstrap:
    def __init__(self, child, machine_directory):
        self.child = child
        self.console = SimulatorConsole(child)
        root = Path(machine_directory) / 'monitor-boots'
        root.mkdir(mode=0o700, exist_ok=True)
        self.evidence = root / uuid.uuid4().hex
        self.evidence.mkdir(mode=0o700)
        if any(c in str(self.evidence) for c in '\r\n"'):
            raise ValueError('Invalid monitor evidence path')
        self.verified = False
        self.stage = 'created'
        self.sequence = 0
        self.report = dict(patch_id=PATCH_ID, boot_id=self.evidence.name,
                           started_at=time.time(), installed=False)

    def record(self, stage, **fields):
        self.stage = stage
        self.sequence += 1
        self.report.update(fields)
        data = dict(self.report, stage=stage)
        publish_private(self.evidence/f'{self.sequence:02d}-{stage}.json',
                        lambda stream: stream.write(json.dumps(data, indent=2).encode('ascii')+b'\n'))

    @contextmanager
    def private_console(self):
        # Stacks/AC banks can contain private data. Never transcript them or
        # retain the scratch restore script; evidence contains summaries only.
        names = ('logfile', 'logfile_read', 'logfile_send')
        saved = {name: getattr(self.child, name) for name in names}
        try:
            for name in names:
                setattr(self.child, name, None)
            yield
        except BaseException:
            # A partial memory response may still be queued. Leave logging off
            # through teardown so that pending private output cannot leak.
            raise
        else:
            for name, stream in saved.items():
                setattr(self.child, name, stream)

    def arm_from_loader(self):
        """Caller has witnessed BOOT>; it supplies /tm02 once after this returns."""
        with self.private_console():
            self.console.halt()
            self.console.command(f'break {ENTRY:o}')
            self.console.resume()
        self.record('armed')

    def install_before_operator(self, timeout):
        try:
            with self.private_console():
                selected = self.child.expect_exact(['OPR>', 'sim>'], timeout=timeout)
                if selected != 1 or 'Breakpoint, PC: 506703' not in self.child.before:
                    raise MonitorCompatibilityError('Expected the first swap-output breakpoint before OPR')
                self.console.at_prompt = True
                self.console.deadline = time.monotonic() + INSTALL_TIMEOUT
                self.console.command(f'nobreak {ENTRY:o}')
                self._install()
                self.console.resume()
                self.console.deadline = None
                self.child.expect_exact('OPR>', timeout=timeout)
            self.verified = True
            self.record('verified', installed=True)
        except Exception as error:
            self.verified = False
            try:
                self.record('failed', installed=False, failed_stage=self.stage, error_type=type(error).__name__)
            except OSError:
                # Preserve the non-retryable failure even if evidence is unwritable.
                pass
            if isinstance(error, MonitorBootstrapError):
                raise
            raise MonitorBootstrapError('Monitor correction failed; inspect per-boot evidence') from None

    def _banks(self):
        output = self.console.command('examine cpu state')
        result, previous = {}, None
        for line in output.splitlines():
            word = re.fullmatch(r'REG\[(\d+)\]:\s+([0-7]{12})', line)
            repeated = re.fullmatch(r'REG\[(\d+)\](?:-REG\[(\d+)\])?:\s+same as above', line)
            if word:
                index, value = word.groups()
                previous = result[int(index)] = int(value, 8)
            elif repeated and previous is not None:
                first, last = repeated.groups()
                result.update(dict.fromkeys(range(int(first), int(last or first)+1), previous))
        if set(result) != set(range(AC_BANK_WORDS)):
            raise MonitorBootstrapError('Incomplete saved accumulator banks')
        return result

    def _install(self):
        console = self.console
        self.record('checking-profile')
        for name, expected in (('PC', ENTRY), ('EBR', 2), ('PGON', 1), ('T20P', 1)):
            if console.register(name) != expected:
                raise MonitorCompatibilityError('Unsupported executive paging context')
        saved = {name: console.register(name) for name in ('PC', 'FLAGS', 'UBR', 'PION', 'PIENB', 'PIACT')}
        if saved['FLAGS'] & 0o10000 or saved['PIACT'] not in (0, 1) or saved['PION'] != 1:
            raise MonitorCompatibilityError('Unsupported scheduling context at correction entry')
        source = {}
        for first, last in FINGERPRINTS:
            source.update(console.words(first, last))
        verify_fingerprints(source)
        if (console.words(0o2540, physical=True)[0o2540] != 0o124000000003
                or console.words(0o402, 0o403) != {0o402: 0o254200000402, 0o403: 0o254200000403}):
            raise MonitorCompatibilityError('Unsupported monitor return or executive section map')
        entry_pte = console.words(0o3506, physical=True)[0o3506]
        if entry_pte >> 33 != 1 or entry_pte & 0o77000000:
            raise MonitorCompatibilityError('Monitor entry text is not directly resident')
        physical_entry = (entry_pte & 0o3777) * 0o1000 + 0o703
        banks = self._banks()
        null_stack = console.words(NULL_STACK_POINTER)[NULL_STACK_POINTER]
        stack_top = null_stack & ADDRESS_MASK
        stack = console.words(stack_top, stack_top + NULL_STACK_WORDS - 1)
        pool_base = console.words(POOL_BASE)[POOL_BASE]
        pool_pointer = console.words(POOL_POINTER)[POOL_POINTER]
        bitmap_base = pool_pointer & ADDRESS_MASK
        bitmap_count = (1 << 18) - (pool_pointer >> 18)
        if not 0 < bitmap_count < MAX_BITMAP_WORDS:
            raise MonitorCompatibilityError('Unsupported kernel allocation bitmap')
        before = console.words(bitmap_base, bitmap_base + bitmap_count - 1)
        self.record('profile-verified', code_fingerprints={f'{a:o}-{b:o}': h for (a, b), h in FINGERPRINTS.items()})
        try:
            self.record('allocating')
            console.deposit('PION', 0)
            console.deposit('PIENB', 0)
            console.deposit('UBR', NULL_UBR)
            console.deposit('FLAGS', KERNEL_FLAGS)
            pushed = stack_push(null_stack)
            console.deposit(f'-v -e {pushed & ADDRESS_MASK:o}', RETURN_WORD)
            console.deposit('REG[1]', pushed)
            console.deposit('REG[2]', 0)
            console.deposit('REG[3]', ALLOCATION_WORDS)
            console.deposit('PC', GETWDS)
            result = console.command(f'step {STEP_LIMIT}')
            if ('HALT instruction' not in result or console.register('PC') != SUCCESS_HALT
                    or console.register('PIACT') != saved['PIACT']):
                raise MonitorBootstrapError('Native allocator did not confirm a bounded successful return')
            allocation = console.register('AC2')
            during = console.words(bitmap_base, bitmap_base + bitmap_count - 1)
            masks = {}
            for offset in range(0, ALLOCATION_WORDS, 4):
                address, mask = bitmap_block(allocation + offset, pool_base, bitmap_base)
                masks[address] = masks.get(address, 0) | mask
            if not set(masks) <= set(before) or any(before[a] & masks.get(a, 0)
                    or during[a] != (before[a] | masks.get(a, 0)) for a in before):
                raise MonitorBootstrapError('Native allocator ownership verification failed')
            plan = build_patch(source, allocation, ALLOCATION_WORDS)
            self.record('reserved', address=f'{allocation:06o}', allocation_words=ALLOCATION_WORDS)
            for address, value in plan['payload'].items():
                console.deposit(f'-v -e {address:o}', value)
            if console.words(min(plan['payload']), max(plan['payload'])) != plan['payload']:
                raise MonitorBootstrapError('Monitor payload readback mismatch')
            for address, value in plan['replacements'].items():
                console.deposit(f'{physical_entry + address - ENTRY:o}', value)
            if console.words(ENTRY, ENTRY + 2) != plan['replacements']:
                raise MonitorBootstrapError('Monitor entry readback mismatch')
            self.record('code-installed', payload_sha256=digest_words(plan['payload'].values()),
                        payload_words=len(plan['payload']))
        finally:
            self._restore(saved, banks, stack)
        if console.words(stack_top, stack_top + NULL_STACK_WORDS - 1) != stack or self._banks() != banks:
            raise MonitorBootstrapError('Interrupted stack or accumulator restoration failed')
        if any(console.register(name) != value for name, value in saved.items()):
            raise MonitorBootstrapError('Interrupted control-register restoration failed')
        self.record('state-restored')

    def _restore(self, saved, banks, stack):
        restore = ['deposit PION 0', 'deposit PIENB 0']
        restore += [f'deposit -v -e {a:o} {v:o}' for a, v in stack.items()]
        restore += [f'deposit REG[{a}] {v:o}' for a, v in banks.items()]
        restore += [f'deposit {name} {saved[name]:o}' for name in ('UBR', 'FLAGS', 'PC', 'PIENB', 'PION')]
        path = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.ini', prefix='scope-restore-',
                                             dir=self.evidence, delete=False) as stream:
                path = Path(stream.name)
                os.fchmod(stream.fileno(), 0o600)
                stream.write('\n'.join(restore)+'\n')
            self.console.command(f'do -v "{path}"')
        finally:
            if path is not None:
                path.unlink(missing_ok=True)
