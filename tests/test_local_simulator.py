import hashlib
import io
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import local_simulator

SOURCE = b'''static int32 tim_mult;
tick_in_usecs - sim_activate_time_usecs (&tim_unit)
static t_stat tim_svc (UNIT *uptr)
{
update_interval(17*4096);
}
'''


class LocalSimulatorTests(unittest.TestCase):
    def test_timed_out_build_worker_is_reaped(self):
        processes = []
        original = subprocess.Popen

        def start(*args, **kwargs):
            process = original(*args, **kwargs)
            processes.append(process)
            return process

        with tempfile.TemporaryDirectory() as directory, patch.object(local_simulator.subprocess, 'Popen', start):
            with (Path(directory)/'build.log').open('wb') as log:
                with self.assertRaises(subprocess.TimeoutExpired):
                    local_simulator.run_build([sys.executable, '-c', 'import time; time.sleep(30)'],
                                              Path(directory), log, timeout=.05)
        self.assertEqual(len(processes), 1)
        self.assertIsNotNone(processes[0].returncode)

    def prepare(self, root):
        source = root/'original'
        (source/'PDP10').mkdir(parents=True)
        (source/'PDP10/pdp10_tim.c').write_bytes(SOURCE)
        calls = []

        def run(command, **kwargs):
            calls.append(command)
            if command[0] == 'git' and 'rev-parse' in command:
                return SimpleNamespace(stdout=local_simulator.SIMH_REVISION+'\n')
            if command[0] == 'git' and 'archive' in command:
                with tarfile.open(fileobj=kwargs['stdout'], mode='w') as archive:
                    entry = tarfile.TarInfo('PDP10/pdp10_tim.c')
                    entry.size = len(SOURCE)
                    archive.addfile(entry, io.BytesIO(SOURCE))
                return SimpleNamespace(returncode=0)
            self.assertEqual(command[0:2], ['make', 'pdp10'])
            self.assertIn('USEFUL_PACKAGES=', command)
            self.assertIn('OPTIONAL_PACKAGES=', command)
            binary = Path(kwargs['cwd'])/'BIN/pdp10'
            binary.parent.mkdir()
            binary.write_bytes(b'private built simulator')
            binary.chmod(0o700)
            return SimpleNamespace(returncode=0)

        return source, calls, run

    def test_build_does_not_modify_original_and_cache_is_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, calls, run = self.prepare(root)
            corrected = local_simulator.patched_timer(SOURCE.decode()).encode()
            with patch.object(local_simulator, 'ORIGINAL_TIMER_SHA256', hashlib.sha256(SOURCE).hexdigest()), \
                    patch.object(local_simulator, 'PATCHED_TIMER_SHA256', hashlib.sha256(corrected).hexdigest()):
                binary = local_simulator.ensure_simulator(source, root/'cache', runner=run)
                count = len(calls)
                self.assertEqual(local_simulator.ensure_simulator(source, root/'cache', runner=run), binary)
            self.assertEqual(len(calls), count)
            self.assertEqual((source/'PDP10/pdp10_tim.c').read_bytes(), SOURCE)
            self.assertEqual((root/'cache/source/PDP10/pdp10_tim.c').read_bytes(), corrected)

    def test_changed_cached_binary_is_rejected_without_rebuild(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, calls, run = self.prepare(root)
            corrected = local_simulator.patched_timer(SOURCE.decode()).encode()
            with patch.object(local_simulator, 'ORIGINAL_TIMER_SHA256', hashlib.sha256(SOURCE).hexdigest()), \
                    patch.object(local_simulator, 'PATCHED_TIMER_SHA256', hashlib.sha256(corrected).hexdigest()):
                binary = local_simulator.ensure_simulator(source, root/'cache', runner=run)
                binary.write_bytes(b'changed')
                count = len(calls)
                with self.assertRaisesRegex(ValueError, 'cache'):
                    local_simulator.ensure_simulator(source, root/'cache', runner=run)
            self.assertEqual(len(calls), count)
            self.assertEqual(binary.read_bytes(), b'changed')

    def test_build_cannot_target_the_original_source_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            with self.assertRaisesRegex(ValueError, 'source'):
                local_simulator.ensure_simulator(source, source/'private-build')

    def test_changed_cached_timer_source_is_retained_and_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, calls, run = self.prepare(root)
            corrected = local_simulator.patched_timer(SOURCE.decode()).encode()
            with patch.object(local_simulator, 'ORIGINAL_TIMER_SHA256', hashlib.sha256(SOURCE).hexdigest()), \
                    patch.object(local_simulator, 'PATCHED_TIMER_SHA256', hashlib.sha256(corrected).hexdigest()):
                local_simulator.ensure_simulator(source, root/'cache', runner=run)
                timer = root/'cache/source/PDP10/pdp10_tim.c'
                timer.write_bytes(b'local edit')
                count = len(calls)
                with self.assertRaisesRegex(ValueError, 'cache'):
                    local_simulator.ensure_simulator(source, root/'cache', runner=run)
            self.assertEqual(len(calls), count)
            self.assertEqual(timer.read_bytes(), b'local edit')
