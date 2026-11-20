import unittest

from tests.ksys_mapping import (
    Mapper, MappingError, find_job, shutdown_state, verify_image, CODE_RANGES, LAYOUT,
    registration, bind_pid,
)


PAGE = 512
IMM = 1 << 33
SHARED = 2 << 33
INDIRECT = 3 << 33


def sixbit(name):
    value = 0
    for character in name.ljust(6):
        value = (value << 6) | (ord(character) - 32)
    return value


class MappingTests(unittest.TestCase):
    def test_version_alone_does_not_bind_job_image(self):
        for name, (first, last) in CODE_RANGES.items():
            image = dict.fromkeys(range(first, last + 1), IMM | 7)
            image[0o137] = 123
            observed = image.copy()
            verify_image(observed.__getitem__, image, name)
            observed[first] ^= 1
            with self.subTest(name=name), self.assertRaises(MappingError):
                verify_image(observed.__getitem__, image, name)

    def test_image_binding_rejects_missing_code_or_different_version(self):
        first, last = CODE_RANGES['quasar']
        image = dict.fromkeys(range(first, last + 1), IMM | 7)
        image[0o137] = 123
        for observed in ({0o137: 123}, image.copy()):
            if len(observed) > 1:
                observed[0o137] = 456
            with self.assertRaises(MappingError):
                verify_image(observed.__getitem__, image, 'quasar')

    def test_immediate_backing_and_cross_page_reads(self):
        words = {4 * PAGE + 0o540: IMM | 5,
                 5 * PAGE: IMM | 7, 5 * PAGE + 1: IMM | 9,
                 7 * PAGE + 511: 123, 9 * PAGE: 456}
        before = words.copy()
        mapper = Mapper(words.__getitem__, spt=10000)
        self.assertEqual(mapper.address(4, 511), 7 * PAGE + 511)
        self.assertEqual(mapper.word(4, 512), 456)
        self.assertEqual(words, before)

    def test_shared_section_and_indirect_page(self):
        words = {4 * PAGE + 0o540: SHARED | 1,
                 10001: IMM | 5,
                 5 * PAGE + 2: INDIRECT | (3 << 18) | 2,
                 10002: IMM | 6, 6 * PAGE + 3: SHARED | 4,
                 10004: IMM | 8, 8 * PAGE + 17: 789}
        self.assertEqual(Mapper(words.__getitem__, spt=10000).word(4, 2 * PAGE + 17), 789)

    def test_nonresident_missing_and_noaccess_are_unknown(self):
        for entry in (0, IMM | 0o1000000 | 5):
            mapper = Mapper({4 * PAGE + 0o540: entry}.__getitem__, spt=10000)
            with self.assertRaises(MappingError):
                mapper.word(4, 100)
        with self.assertRaises(MappingError):
            Mapper({}.__getitem__, spt=0).word(4, 100)
        # ksys-map-03's QUASAR virtual page077: nonzero software contents
        # do not make its type-zero (no-access) pointer usable.
        words = {4 * PAGE + 0o540: IMM | 5,
                 5 * PAGE + 0o77: 0o044400000445}
        with self.assertRaises(MappingError):
            Mapper(words.__getitem__, spt=10000).word(4, 0o77643)

    def test_indirection_cycle_and_section_index_fail_boundedly(self):
        for first in (INDIRECT | 1, INDIRECT | (1 << 18) | 1):
            words = {4 * PAGE + 0o540: first, 10001: IMM | 4,
                     4 * PAGE: INDIRECT | 1}
            with self.assertRaises(MappingError):
                Mapper(words.__getitem__, spt=10000).word(4, 100)

    def test_addresses_do_not_wrap_into_other_memory(self):
        mapper = Mapper(lambda address: IMM | 1, spt=10000)
        for upt, address in ((0, 1), (4096, 1), (4, -1), (4, 1 << 18)):
            with self.assertRaises(MappingError):
                mapper.address(upt, address)

    def roster(self):
        memory = {}
        for job in range(1, LAYOUT['max_job'] + 1):
            for table in ('name', 'status', 'core', 'upt'):
                memory[LAYOUT[table] + job] = 0
        for job, name, upt in ((1, 'BATCON', 20), (3, 'QUASAR', 30)):
            memory[LAYOUT['name'] + job] = sixbit(name)
            memory[LAYOUT['status'] + job] = 0o40000 << 18
            memory[LAYOUT['core'] + job] = 123
            memory[LAYOUT['upt'] + job] = upt
            memory[upt * PAGE + 0o322] = job
        return memory

    def test_job_requires_allocated_resident_unique_name_and_upt_backlink(self):
        memory = self.roster()
        job = find_job(memory.__getitem__, memory.__getitem__, 'BATCON')
        self.assertEqual(job, {'job': 1, 'upt': 20})
        for table, value in (('status', 0), ('core', 0), ('upt', 0)):
            damaged = memory.copy()
            damaged[LAYOUT[table] + 1] = value
            with self.subTest(table=table), self.assertRaises(MappingError):
                find_job(damaged.__getitem__, damaged.__getitem__, 'BATCON')
        memory[20 * PAGE + 0o322] = 2
        with self.assertRaises(MappingError):
            find_job(memory.__getitem__, memory.__getitem__, 'BATCON')

    def test_missing_or_duplicate_jobs_are_not_selected(self):
        memory = self.roster()
        for name in ('MUD', 'BATCON'):
            if name == 'BATCON':
                memory[LAYOUT['name'] + 3] = sixbit(name)
            with self.assertRaises(MappingError):
                find_job(memory.__getitem__, memory.__getitem__, name)

    def state_fixture(self):
        pid = (7 << 18) | 0o1000 | 2
        quasar = {0o60036: 0o2000, 0o2000: 0, 0o2001: pid,
                  0o2002: sixbit('BATCON'), 0o2004: 0, 0o2005: 100,
                  0o102624: 90, 0o102647: 0, 0o102754: 110}
        executive = {0o16101: 0o777, 0o16102: 0o100,
                     0o15735 + 2: (7 << 18) | 0o1000 | 1,
                     0o12502 + 1: 0o30000, 0o30071: 0}
        batcon = {0o457: 0, 0o553: 0}
        return quasar, executive, batcon

    def test_shutdown_fields_require_pid_generation_and_job_binding(self):
        q, e, b = self.state_fixture()
        state = shutdown_state(q.__getitem__, b.__getitem__, e.__getitem__, batcon_job=1)
        self.assertEqual(state['psb_status'], 0)
        self.assertEqual(state['batcon_ksys'], 0)
        self.assertEqual(state['batcon_context'], 1)
        for value in ((8 << 18) | 0o1001, (7 << 18) | 0o1003):
            e[0o15735 + 2] = value
            with self.assertRaises(MappingError) as failure:
                shutdown_state(q.__getitem__, b.__getitem__, e.__getitem__, batcon_job=1)
            self.assertEqual(failure.exception.evidence['pid_entry'], value)
            self.assertEqual(failure.exception.evidence['expected_job'], 1)
            self.assertNotIn('validated', failure.exception.evidence)

    def test_raw_registration_survives_zero_or_stale_pid_without_binding(self):
        for pid in (0, (8 << 18) | 0o1002):
            q, e, _ = self.state_fixture()
            q[0o2001] = pid
            q[0o2004] = 3 << 27
            observed = registration(q.__getitem__)
            self.assertEqual(observed['psb_status'], 3)
            self.assertEqual(observed['psb_pid'], pid)
            self.assertEqual(observed['psb_deadline'], 100)
            with self.assertRaises(MappingError):
                bind_pid(e.__getitem__, observed, batcon_job=1)
            self.assertNotIn('batcon_context', observed)
            self.assertEqual(observed['psb_flags'], 3 << 27)

    def test_witnessed_pid_has_context_one_not_bare_job_number(self):
        q, e, b = self.state_fixture()
        q[0o2001] = 0o400017001002
        e.update({0o16101: 0o177, 0o16102: 0o110,
                  0o15737: 0o400017001014,
                  0o12502 + 12: 0o30000})
        state = shutdown_state(q.__getitem__, b.__getitem__, e.__getitem__, batcon_job=12)
        self.assertEqual(state['batcon_context'], 1)

    def test_pid_context_must_be_current_and_chain_unambiguous(self):
        q, e, b = self.state_fixture()
        e.update({0o30071: 0o31000, 0o30072: 0o31000,
                  0o31000: 1, 0o31002: 0o32000,
                  0o32000: 2, 0o32002: 0})
        self.assertEqual(shutdown_state(q.__getitem__, b.__getitem__, e.__getitem__,
                                       batcon_job=1)['batcon_context'], 1)
        for updates in ({0o30072: 0o32000}, {0o30072: 0o33000},
                        {0o32000: 1}, {0o32002: 0o31000}):
            damaged = e.copy()
            damaged.update(updates)
            with self.subTest(updates=updates), self.assertRaises(MappingError):
                shutdown_state(q.__getitem__, b.__getitem__, damaged.__getitem__, batcon_job=1)
        # Matching PID generation/job cannot establish a nonexistent context2.
        q[0o2001] = (7 << 18) | 0o2002
        e.update({0o30071: 0, 0o15737: (7 << 18) | 0o2001})
        with self.assertRaises(MappingError):
            shutdown_state(q.__getitem__, b.__getitem__, e.__getitem__, batcon_job=1)

    def test_psb_cycle_or_duplicate_name_is_rejected(self):
        q, e, b = self.state_fixture()
        q[0o2000] = 0o2000
        with self.assertRaises(MappingError):
            shutdown_state(q.__getitem__, b.__getitem__, e.__getitem__, batcon_job=1)
        q[0o2000] = 0o2100
        q[0o2100] = 0
        q[0o2102] = sixbit('BATCON')
        with self.assertRaises(MappingError):
            shutdown_state(q.__getitem__, b.__getitem__, e.__getitem__, batcon_job=1)
