"""Synthetic physical memory: no historical code or binary fixtures."""
import time
import unittest
from unittest.mock import patch

from server.monitor_scope import digest_words
from tests import ksys_capture as capture
from tests.ksys_mapping import CODE_RANGES, LAYOUT, sixbit


class Console:
    def __init__(self):
        self.at_prompt = True
        self.deadline = time.monotonic() + 10
        self.memory = {}
        self.reads = []
        self.registers = dict(EBR=2, PGON=1, T20P=1, SPT=10000, UBR=20, PC=1)

    def register(self, name):
        return self.registers[name]

    def words(self, first, last, *, physical=False):
        assert physical
        self.reads.append((first, last))
        return {a: self.memory.get(a, 0) for a in range(first, last + 1)}


class CaptureTests(unittest.TestCase):
    def fixture(self):
        c = Console()
        immediate = 1 << 33
        bases = dict(executive=0o1000000, quasar=0o2000000, batcon=0o3000000)
        for upt, table, name in ((2, 10, 'executive'), (20, 22, 'quasar'), (21, 23, 'batcon')):
            c.memory[upt * 512 + 0o540] = immediate | table
            for page in range(512):
                c.memory[table * 512 + page] = immediate | (bases[name] // 512 + page)
        def put(name, address, value):
            c.memory[bases[name] + address] = value
        put('executive', 0o500, 123)
        versions = dict(quasar=123, batcon=456)
        signatures = {}
        for job, name, upt in ((1, 'quasar', 20), (2, 'batcon', 21)):
            for table, value in (('name', sixbit(name.upper())), ('status', 0o40000 << 18),
                                 ('core', 1), ('upt', upt)):
                put('executive', LAYOUT[table] + job, value)
            c.memory[upt * 512 + 0o322] = job
            put(name, 0o137, versions[name])
            first, last = CODE_RANGES[name]
            for address in range(first, last + 1):
                put(name, address, 789)
            signatures[name] = (versions[name], digest_words([789] * (last - first + 1)))
        for address, value in {0o60036: 0o2000, 0o2000: 0, 0o2001: (7 << 18) | 0o1003,
                               0o2002: sixbit('BATCON'), 0o2004: 0, 0o2005: 100,
                               0o102624: 90, 0o102647: 0, 0o102754: 0}.items():
            put('quasar', address, value)
        for address, value in {0o16101: 0o177, 0o16102: 0o110,
                               0o15740: (7 << 18) | 0o1002,
                               0o12504: 0o30000, 0o30071: 0}.items():
            put('executive', address, value)
        return c, bases, put, signatures

    def run_capture(self, console, signatures):
        report = {}
        with patch.object(capture, 'MONITOR_SIGNATURES', {(0o500, 0o500): digest_words([123])}), \
                patch.object(capture, 'JOB_SIGNATURES', signatures):
            capture.capture_halted(console, report, scope_verified=True)
        return report

    def test_bound_snapshot_uses_physical_reads_and_preserves_registers(self):
        c, _, _, signatures = self.fixture()
        before = c.memory.copy(), c.registers.copy(), c.deadline
        report = self.run_capture(c, signatures)
        self.assertEqual(report['outcome'], 'complete')
        self.assertEqual(report['binding'], dict(status='verified', context=1))
        self.assertEqual(report['batcon_fields']['count'], 0)
        self.assertEqual((c.memory, c.registers, c.deadline), before)
        self.assertTrue(c.at_prompt)

    def test_zero_stale_pid_and_unmapped_batcon_preserve_raw_registration(self):
        for mode in ('zero', 'stale', 'unmapped'):
            c, _, put, signatures = self.fixture()
            put('quasar', 0o2004, 3 << 27)
            if mode != 'unmapped':
                put('quasar', 0o2001, 0 if mode == 'zero' else (8 << 18) | 0o1003)
            else:
                c.memory[21 * 512 + 0o540] = 0
            report = self.run_capture(c, signatures)
            self.assertEqual(report['registration']['psb_status'], 3)
            self.assertEqual(report['registration']['psb_deadline'], 100)
            self.assertEqual(report['binding']['status'], 'unknown')
            self.assertEqual(report['outcome'], 'partial')
            if mode != 'unmapped':
                self.assertEqual(report['batcon_fields']['ksys'], 0)

    def test_bad_monitor_or_job_code_never_authorizes_state_reads(self):
        for target in ('monitor', 'quasar', 'batcon'):
            c, _, put, signatures = self.fixture()
            put('executive' if target == 'monitor' else target,
                0o500 if target == 'monitor' else CODE_RANGES[target][0], 0)
            report = self.run_capture(c, signatures)
            self.assertNotEqual(report['outcome'], 'complete')
            if target != 'batcon':
                self.assertNotIn('registration', report)
            if target != 'quasar':
                self.assertNotIn('batcon_fields', report)

    def test_missing_psb_retains_independently_identified_batcon_fields(self):
        c, _, put, signatures = self.fixture()
        put('quasar', 0o60036, 0)
        put('batcon', 0o457, 1)
        report = self.run_capture(c, signatures)
        self.assertNotIn('registration', report)
        self.assertEqual(report['batcon_fields']['ksys'], 1)
        self.assertEqual(report['binding']['status'], 'unknown')

    def test_missing_or_duplicate_name_keeps_independent_pid_candidate_unbound(self):
        for mode in ('renamed', 'duplicate', 'unallocated', 'noncurrent', 'bad-code'):
            with self.subTest(mode=mode):
                c, _, put, signatures = self.fixture()
                if mode in ('renamed', 'unallocated', 'noncurrent'):
                    put('executive', LAYOUT['name'] + 2, sixbit('LOGIN'))
                if mode == 'duplicate':
                    put('executive', LAYOUT['name'] + 3, sixbit('BATCON'))
                if mode == 'unallocated':
                    put('executive', LAYOUT['status'] + 2, 0)
                if mode == 'noncurrent':
                    put('quasar', 0o2001, (7 << 18) | 0o2003)
                    put('executive', 0o15740, (7 << 18) | 0o2002)
                if mode == 'bad-code':
                    put('batcon', CODE_RANGES['batcon'][0], 0)
                report = self.run_capture(c, signatures)
                self.assertEqual(report['job_name_matches']['batcon'],
                                 [2, 3] if mode == 'duplicate' else
                                 [2] if mode == 'bad-code' else [])
                self.assertTrue(report['psb_pid_entry']['generation_matches'])
                self.assertEqual(report['psb_pid_job']['job'], 2)
                self.assertEqual(report['psb_pid_job']['name_word'],
                                 sixbit('BATCON' if mode in ('duplicate', 'bad-code') else 'LOGIN'))
                self.assertEqual(report['psb_pid_current_context'],
                                 'unknown' if mode == 'unallocated' else
                                 'mismatch' if mode == 'noncurrent' else 'matches')
                self.assertEqual(report['binding']['status'], 'unknown')
                self.assertNotIn('batcon_fields', report)
                self.assertEqual(report['outcome'], 'partial')

    def test_missing_name_stale_pid_never_reads_replacement_job(self):
        c, bases, put, signatures = self.fixture()
        put('executive', LAYOUT['name'] + 2, sixbit('LOGIN'))
        put('executive', 0o15740, (8 << 18) | 0o1002)
        report = self.run_capture(c, signatures)
        self.assertFalse(report['psb_pid_entry']['generation_matches'])
        self.assertNotIn('psb_pid_job', report)
        self.assertEqual(report['psb_pid_current_context'], 'unknown')
        self.assertEqual(report['binding']['status'], 'unknown')
        # Neither replacement-job PDB context nor its code is queried.
        self.assertFalse(any(first <= bases['executive'] + 0o30071 <= last
                             or first <= bases['batcon'] + 0o137 <= last
                             for first, last in c.reads))

    def test_transport_failure_escapes_private_console_without_raw_payload(self):
        c, _, _, _ = self.fixture()
        def incomplete(*args, **kwargs):
            c.at_prompt = False
            raise TimeoutError('private memory payload')
        c.words = incomplete
        report = {}
        with self.assertRaises(TimeoutError):
            capture.capture_halted(c, report, scope_verified=True)
        self.assertNotIn('private memory', str(report))
        self.assertEqual(report['errors']['capture']['error_type'], 'TimeoutError')

    def test_halt_scope_deadline_and_page_budget_are_required(self):
        for failure in ('halt', 'scope', 'deadline', 'pages'):
            c, _, _, signatures = self.fixture()
            if failure == 'halt':
                c.at_prompt = False
            if failure == 'deadline':
                c.deadline = time.monotonic() - 1
            report = {}
            with patch.object(capture, 'MAX_PHYSICAL_PAGES', 1 if failure == 'pages' else 128), \
                    self.assertRaises((RuntimeError, TimeoutError)):
                capture.capture_halted(c, report, scope_verified=failure != 'scope')
            self.assertNotEqual(report['outcome'], 'complete')
            self.assertNotIn('registration', report)
            self.assertLessEqual(len(c.reads), 1 if failure == 'pages' else 0)
