"""Deterministically exercise WRINT between ticks in the pinned SIMH timer.

Scheduling/interpolation statements are from PDP10/pdp10_tim.c at 47b7ddab.
The fake scheduler makes this independent of host speed and guest boot timing.
"""
import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools import deploy


PINNED_SNIPPETS = r'''
#include <stdint.h>
typedef int32_t int32;
typedef int64_t d10;
typedef int t_stat;
typedef struct { int wait; } UNIT;
static int32 tim_mult;
static int32 tick_in_usecs = 16983;
static d10 tim_period = 69632;
static d10 tim_new_period = 69632;
static d10 tim_base[2];
static UNIT tim_unit;
static double remaining;
static void sim_activate_after(UNIT *u, int32 duration) { remaining = duration; }
static double sim_activate_time_usecs(UNIT *u) { return remaining; }
static void update_interval(int32 ticks) { tick_in_usecs = ticks * 1000000.0 / 4100000; }
static void tim_incr_base(d10 *base, d10 incr) { base[1] += incr; }
static d10 rdtim(void) {
d10 tempbase[2] = {tim_base[0], tim_base[1]};
d10 incr;
incr = (d10)((((double)4100000) / 1000000.0) * (tick_in_usecs - sim_activate_time_usecs (&tim_unit)));
tim_incr_base(tempbase, incr);
return tempbase[1] & ~3LL;
}
static t_stat tim_svc (UNIT *uptr)
{
    sim_activate_after (uptr, tick_in_usecs);
    tim_incr_base(tim_base, tim_period);
    tim_period = tim_new_period;
    return 0;
}
static void reset(void) {
update_interval(17*4096);
}
int main(void) {
    reset();
    tim_svc(&tim_unit);
    remaining -= 100;
    d10 before = rdtim();
    update_interval(16*4096);
    tim_new_period = 16*4096;
    d10 after = rdtim();
    if (after != before) return 1;
    remaining -= 100;
    if (rdtim() < after) return 2;
    tim_svc(&tim_unit);
    before = rdtim();
    update_interval(69632);
    tim_new_period = 17*4096;
    if (rdtim() != before) return 3;
    remaining -= 100;
    if (rdtim() < before) return 4;
    return 0;
}
'''


class TimerTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('cc'), 'C compiler required for timer regression')
    def test_wrint_does_not_change_current_tick_interpolation(self):
        from tools.simh_timer import patched_timer
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / 'timer-test'
            for corrected, expected in ((False, 1), (True, 0)):
                with self.subTest(corrected=corrected):
                    source = patched_timer(PINNED_SNIPPETS) if corrected else PINNED_SNIPPETS
                    build = subprocess.run(['cc', '-x', 'c', '-o', str(executable), '-'],
                                           input=source, capture_output=True, text=True)
                    self.assertEqual(build.returncode, 0, build.stderr)
                    self.assertEqual(subprocess.run([str(executable)]).returncode, expected)

    def test_unrecognized_source_cannot_be_patched(self):
        from tools.simh_timer import patched_timer
        with self.assertRaisesRegex(ValueError, 'source'):
            patched_timer('unrelated timer implementation')

    def test_patch_retains_utf8_comments_and_verifies_reruns(self):
        from tools import simh_timer
        original = ('/* µs */\r\n' + PINNED_SNIPPETS.replace('\n', '\r\n')).encode('utf-8')
        corrected = simh_timer.patched_timer(original.decode('utf-8').replace('\r\n', '\n')).encode('utf-8')
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            (source / 'PDP10').mkdir()
            filename = source / 'PDP10/pdp10_tim.c'
            filename.write_bytes(original)
            with patch.object(simh_timer, 'ORIGINAL_SHA256', hashlib.sha256(original).hexdigest()), \
                    patch.object(simh_timer, 'PATCHED_SHA256', hashlib.sha256(corrected).hexdigest()):
                self.assertTrue(simh_timer.apply(source))
                self.assertFalse(simh_timer.apply(source))
                simh_timer.verify(source)
                self.assertIn('µs', filename.read_text())
                filename.write_bytes(corrected + b'/* unrelated edit */')
                with self.assertRaisesRegex(ValueError, 'checksum'):
                    simh_timer.apply(source)
                self.assertEqual(filename.read_bytes(), corrected + b'/* unrelated edit */')


class TimerBuildTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        application = patch('tools.deploy.APP', self.root)
        application.start()
        self.addCleanup(application.stop)

    def test_build_uses_separate_cache_and_patches_before_make(self):
        from tools import simh_timer
        source = self.root / 'simh' / (simh_timer.REVISION + '-' + simh_timer.PATCH_ID)
        old_binary = self.root / 'simh' / simh_timer.REVISION / 'BIN/pdp10'
        old_binary.parent.mkdir(parents=True)
        old_binary.write_bytes(b'previous executable')

        def build(*command):
            if command[0] == 'make':
                self.assertEqual(command[2], source)
                correction.assert_called_once_with(source)
                (source / 'BIN').mkdir(parents=True)
                (source / 'BIN/pdp10').write_bytes(b'corrected executable')

        with patch('tools.deploy.run', side_effect=build) as run, \
                patch('tools.simh_timer.apply') as correction, \
                patch('tools.simh_timer.verify') as verify, \
                patch('tools.deploy.subprocess.check_output', return_value=simh_timer.REVISION + '\n'):
            self.assertEqual(deploy.build_simh(simh_timer.REVISION), source / 'BIN/pdp10')
            verify.assert_called_once_with(source)
        self.assertEqual(old_binary.read_bytes(), b'previous executable')
        self.assertIn(('make', '-C', source, '-j1', 'pdp10', 'USEFUL_PACKAGES=', 'OPTIONAL_PACKAGES='),
                      [call.args for call in run.call_args_list])

    def test_cached_binary_requires_corrected_source_without_mutating_it(self):
        from tools import simh_timer
        source = self.root / 'simh' / (simh_timer.REVISION + '-' + simh_timer.PATCH_ID)
        (source / 'BIN').mkdir(parents=True)
        (source / 'BIN/pdp10').write_bytes(b'existing executable')
        (source / 'PDP10').mkdir()
        timer = source / 'PDP10/pdp10_tim.c'
        timer.write_bytes(b'unexpected source')
        with patch('tools.deploy.run') as run, patch('tools.simh_timer.apply') as apply, \
                patch('tools.deploy.subprocess.check_output', return_value=simh_timer.REVISION + '\n'):
            with self.assertRaisesRegex(ValueError, 'checksum'):
                deploy.build_simh(simh_timer.REVISION)
            run.assert_not_called()
            apply.assert_not_called()
        self.assertEqual(timer.read_bytes(), b'unexpected source')

    def test_verified_cache_is_reused_without_checkout_or_rebuild(self):
        from tools import simh_timer
        source = self.root / 'simh' / (simh_timer.REVISION + '-' + simh_timer.PATCH_ID)
        (source / 'BIN').mkdir(parents=True)
        (source / 'BIN/pdp10').touch()
        with patch('tools.deploy.run') as run, patch('tools.simh_timer.apply') as apply, \
                patch('tools.simh_timer.verify') as verify, \
                patch('tools.deploy.subprocess.check_output', return_value=simh_timer.REVISION + '\n'):
            self.assertEqual(deploy.build_simh(simh_timer.REVISION), source / 'BIN/pdp10')
            run.assert_not_called()
            apply.assert_not_called()
            verify.assert_called_once_with(source)

    def test_unsupported_revision_is_rejected_before_building(self):
        with patch('tools.deploy.run') as run:
            for revision in ('not-a-revision', '0' * 40):
                with self.subTest(revision=revision), self.assertRaises(ValueError):
                    deploy.build_simh(revision)
            run.assert_not_called()
        self.assertFalse((self.root / 'simh').exists())

    def test_cache_with_wrong_checkout_revision_is_rejected(self):
        from tools import simh_timer
        source = self.root / 'simh' / (simh_timer.REVISION + '-' + simh_timer.PATCH_ID)
        (source / 'BIN').mkdir(parents=True)
        (source / 'BIN/pdp10').touch()
        with patch('tools.deploy.run') as run, \
                patch('tools.deploy.subprocess.check_output', return_value='0' * 40 + '\n'):
            with self.assertRaisesRegex(ValueError, 'source revision'):
                deploy.build_simh(simh_timer.REVISION)
            run.assert_not_called()
