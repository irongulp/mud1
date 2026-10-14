import fcntl
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import external_cutover


class CutoverEntrypointTests(unittest.TestCase):
    def test_inherited_installer_lease_covers_cutover(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            (state / 'shutdown.json').write_text('{"clean": true}\n')
            with (state / 'runtime.lock').open('a') as parent:
                fcntl.flock(parent, fcntl.LOCK_EX | fcntl.LOCK_NB)
                args = ['external_cutover', '--state', directory, '--config-dir', directory,
                        '--simh', '/unused', '--runtime-lock-fd', str(parent.fileno())]
                def cutover(*args, **kwargs):
                    self.assertEqual(kwargs['runtime_lock_fd'], parent.fileno())
                    with (state / 'runtime.lock').open('a') as competing, self.assertRaises(BlockingIOError):
                        fcntl.flock(competing, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with patch('sys.argv', args), patch.object(external_cutover, 'cutover', side_effect=cutover) as call:
                    external_cutover.main()
                call.assert_called_once()

    def test_direct_entrypoint_refuses_unclean_disk_before_cutover(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            (state / 'shutdown.json').write_text('{"clean": false}\n')
            args = ['external_cutover', '--state', directory, '--config-dir', directory, '--simh', '/unused']
            with patch('sys.argv', args), patch.object(external_cutover, 'cutover') as call, \
                    self.assertRaisesRegex(RuntimeError, 'confirmed stopped'):
                external_cutover.main()
            call.assert_not_called()
