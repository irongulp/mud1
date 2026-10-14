"""Cold boot may recover; capture/build/import must never be replayed with it."""
from contextlib import contextmanager, ExitStack
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch

import pexpect
from server.runtime import BOOT_ATTEMPTS, Runtime
from tools import external_install


@contextmanager
def fixture(*, boot=None, build=None, capture=None, clean=True):
    with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
        state = Path(directory)
        (state / 'external').mkdir()
        (state / 'external/native-before-cutover.dsk').write_bytes(b'private fixture')
        prepared = state / 'prepared'
        prepared.mkdir()
        (prepared / 'MUD.TXT').write_text('fixture world\n')
        runtime = Runtime(state, '/unused')
        native = Mock()
        native.command.return_value = 'type mud.txt\r\nfixture world\r\n.'
        inspector = MagicMock()
        inspector.__enter__.return_value = native
        snapshot = SimpleNamespace(records={}, sha256='fixture')
        stack.enter_context(patch.object(external_install, 'Runtime', return_value=runtime))
        stack.enter_context(patch.object(external_install, 'database_config',
                                        return_value=(SimpleNamespace(namespace='fixture'), Mock())))
        stack.enter_context(patch.object(external_install, 'prepare_sources', return_value=prepared))
        stack.enter_context(patch.object(external_install, 'SnapshotInspector', return_value=inspector))
        stack.enter_context(patch.object(external_install, 'read_snapshot', return_value=snapshot))
        stack.enter_context(patch.object(external_install, 'write_snapshot'))
        stack.enter_context(patch.object(external_install, 'protect_bridge_terminals'))
        stack.enter_context(patch.object(external_install, 'verify_import'))
        stack.enter_context(patch.object(external_install, 'isolated_writer', return_value=MagicMock()))
        calls = {
            'boot': stack.enter_context(patch.object(runtime, 'boot', side_effect=boot)),
            'stop': stack.enter_context(patch.object(runtime, 'stop', return_value=clean)),
            'capture': stack.enter_context(patch.object(external_install, 'capture', return_value=snapshot,
                                                       side_effect=capture)),
            'build': stack.enter_context(patch.object(external_install, 'build_external', side_effect=build)),
            'import': stack.enter_context(patch.object(external_install, 'import_snapshot')),
        }
        stack.enter_context(patch('server.runtime.time.sleep'))
        yield state, calls


class CutoverStartupTests(unittest.TestCase):
    def test_failed_boot_recovered_before_single_capture_build_and_import(self):
        with fixture(boot=[pexpect.TIMEOUT('OPR stalled'), None]) as (state, calls):
            external_install.cutover(state, state, '/unused')
        self.assertEqual(calls['boot'].call_count, 2)
        self.assertEqual(calls['stop'].call_count, 2)
        for stage in ('capture', 'build', 'import'):
            calls[stage].assert_called_once()

    def test_exhausted_boot_never_reaches_capture(self):
        failure = pexpect.TIMEOUT('OPR stalled')
        with fixture(boot=failure, clean=False) as (state, calls), \
                self.assertRaises(pexpect.TIMEOUT) as raised:
            external_install.cutover(state, state, '/unused')
        self.assertIs(raised.exception, failure)
        self.assertEqual(calls['boot'].call_count, BOOT_ATTEMPTS)
        for stage in ('capture', 'build', 'import'):
            calls[stage].assert_not_called()

    def test_build_failure_is_not_retried_or_masked_by_unclean_shutdown(self):
        failure = ValueError('compile failed')
        with fixture(build=failure, clean=False) as (state, calls), \
                self.assertRaises(ValueError) as raised:
            external_install.cutover(state, state, '/unused')
        self.assertIs(raised.exception, failure)
        calls['boot'].assert_called_once()
        calls['build'].assert_called_once()
        calls['import'].assert_not_called()

    def test_capture_failure_is_not_retried(self):
        failure = ValueError('capture failed')
        with fixture(capture=failure, clean=False) as (state, calls), \
                self.assertRaises(ValueError) as raised:
            external_install.cutover(state, state, '/unused')
        self.assertIs(raised.exception, failure)
        calls['boot'].assert_called_once()
        calls['capture'].assert_called_once()
        calls['build'].assert_not_called()
        calls['import'].assert_not_called()

    def test_unclean_shutdown_blocks_import_after_successful_build(self):
        with fixture(clean=False) as (state, calls), self.assertRaisesRegex(RuntimeError, 'shutdown'):
            external_install.cutover(state, state, '/unused')
        calls['build'].assert_called_once()
        calls['import'].assert_not_called()
