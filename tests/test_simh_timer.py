"""Compile the pinned timer's scheduling/interpolation snippets with fake scheduling.

The relevant lines are verbatim from PDP10/pdp10_tim.c at 47b7ddab; the stub
scheduler lets us reproduce WRINT between ticks without relying on host timing.
"""
from pathlib import Path
import hashlib
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools.simh_timer import patched_timer
from tools import simh_timer

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
incr = (d10)((((double)TIM_HW_FREQ) / 1000000.0) * (tick_in_usecs - sim_activate_time_usecs (&tim_unit)));
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
    if (after != before) return 1; /* WRINT cannot alter elapsed time. */
    remaining -= 100;
    if (rdtim() < after) return 2;
    tim_svc(&tim_unit);
    before = rdtim();
    update_interval(69632);
    tim_new_period = 17*4096;
    if (rdtim() != before) return 3;
    return 0;
}
'''


class TimerTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('cc'), 'C compiler required for timer regression')
    def test_wrint_does_not_change_current_tick_interpolation(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / 'timer-test'
            source = patched_timer(PINNED_SNIPPETS).replace('TIM_HW_FREQ', '4100000')
            build = subprocess.run(['cc', '-x', 'c', '-o', str(executable), '-'],
                                   input=source, capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            result = subprocess.run([str(executable)], capture_output=True)
            self.assertEqual(result.returncode, 0, 'WRINT changed an already-running tick')

    def test_unrecognized_source_cannot_be_patched(self):
        with self.assertRaisesRegex(ValueError, 'source'):
            patched_timer('unrelated timer implementation')

    def test_patch_retains_utf8_comments_and_verifies_reruns(self):
        original = ('/* µs */\r\n' + PINNED_SNIPPETS.replace('\n', '\r\n')).encode('utf-8')
        corrected = patched_timer(original.decode('utf-8').replace('\r\n', '\n')).encode('utf-8')
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            (source / 'PDP10').mkdir()
            filename = source / 'PDP10/pdp10_tim.c'
            filename.write_bytes(original)
            with patch.object(simh_timer, 'ORIGINAL_SHA256', hashlib.sha256(original).hexdigest()), \
                    patch.object(simh_timer, 'PATCHED_SHA256', hashlib.sha256(corrected).hexdigest()):
                self.assertTrue(simh_timer.apply(source))
                self.assertFalse(simh_timer.apply(source))
                self.assertIn('µs', filename.read_text())
                filename.write_bytes(corrected + b'/* unrelated edit */')
                with self.assertRaisesRegex(ValueError, 'checksum'):
                    simh_timer.apply(source)
