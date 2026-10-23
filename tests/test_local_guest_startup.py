from contextlib import contextmanager
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from server.monitor_scope import MonitorCompatibilityError
from tools.serve_external import start_guest
from server.local_guest import LocalGuest


class LocalGuestStartupTests(unittest.TestCase):
    @contextmanager
    def terminal_reboot_case(self):
        from tools import serve_external as launcher
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            evidence = state/'shutdown.json'
            evidence.write_text('{"clean":false}\n')
            first, second = MagicMock(), MagicMock()
            first.command.return_value = second.command.return_value = ''
            second.stop.return_value = True
            with patch.object(launcher, 'prepare_machine', return_value=state), \
                    patch.object(launcher, 'LocalDatabase'), patch.object(launcher, 'isolated_writer'), \
                    patch.object(launcher, 'start_guest', side_effect=[first]+[second]*(launcher.BOOT_ATTEMPTS*2)) as start, \
                    patch.object(launcher, 'protect_bridge_terminals', return_value=True), \
                    patch.object(launcher, 'prepare_batch') as batch, \
                    patch.object(launcher, 'NativeInspector'), patch.object(launcher, 'configure_reset_permissions'), \
                    patch.object(launcher, 'PersonaBridge') as bridge, \
                    patch.object(launcher, 'serve', new_callable=MagicMock) as serve, \
                    patch.object(launcher.asyncio, 'run'):
                yield SimpleNamespace(launcher=launcher, state=state, evidence=evidence,
                    first=first, second=second, start=start, batch=batch, bridge=bridge, serve=serve)

    def assert_terminal_reboot_aborts(self, case, *, stop_calls=1):
        with self.assertRaisesRegex(RuntimeError, 'did not confirm clean shutdown') as raised:
            case.launcher.run(case.state, case.state, 0)
        self.assertEqual(case.start.call_count, 1)
        self.assertEqual(case.first.stop.call_count, stop_calls)
        case.second.stop.assert_not_called()
        case.batch.assert_not_called()
        case.bridge.assert_not_called()
        case.serve.assert_not_called()
        self.assertFalse((case.state/'ready.json').exists())
        self.assertEqual(case.evidence.read_text(), '{"clean":false}\n')
        self.assertIsInstance(raised.exception, case.launcher.UnconfirmedShutdownError)
        return raised.exception

    def test_unconfirmed_terminal_shutdown_cannot_reboot_the_disk(self):
        with self.terminal_reboot_case() as case:
            case.first.stop.return_value = case.second.stop.return_value = False
            self.assert_terminal_reboot_aborts(case)

    def test_later_cleanup_success_cannot_override_failed_terminal_shutdown(self):
        with self.terminal_reboot_case() as case:
            case.first.stop.side_effect = [False, True]
            self.assert_terminal_reboot_aborts(case)

    def test_terminal_shutdown_exception_cannot_trigger_a_new_guest(self):
        with self.terminal_reboot_case() as case:
            failure = OSError('shutdown evidence unavailable')
            case.first.stop.side_effect = [failure, False]
            raised = self.assert_terminal_reboot_aborts(case, stop_calls=2)
            self.assertIs(raised.__cause__, failure)

    def test_confirmed_terminal_shutdown_allows_exactly_the_intended_reboot(self):
        with self.terminal_reboot_case() as case:
            case.first.stop.return_value = True
            case.launcher.run(case.state, case.state, 0)
            self.assertEqual(case.start.call_count, 2)
            case.first.stop.assert_called_once_with()
            case.batch.assert_called_once_with(case.second)
            self.assertEqual(case.bridge.call_args.args[0], case.second)
            self.assertEqual(case.serve.call_args.args[0], case.second)
            case.second.stop.assert_called()

    def test_boot_evidence_failure_preserves_nonretryable_monitor_error(self):
        guest = LocalGuest.__new__(LocalGuest)
        guest.child = MagicMock()
        guest.failure = None
        guest.scope = MagicMock()
        guest.scope.install_before_operator.side_effect = MonitorCompatibilityError('unsupported')
        guest.scope.record.side_effect = OSError('evidence unavailable')
        with patch('server.local_guest.time.sleep'), self.assertRaises(MonitorCompatibilityError):
            guest.boot()

    def setUp(self):
        simulator = patch('tools.serve_external.ensure_simulator', return_value=Path('/cache/pdp10'))
        simulator.start()
        self.addCleanup(simulator.stop)

    def test_verified_local_simulator_is_selected_before_guest_creation(self):
        from tools import serve_external as launcher
        from tools import benchmark_idle
        guarded = MagicMock(monitor_scope_verified=True)
        with patch.object(benchmark_idle, 'ROOT', Path('/assets')), \
                patch.object(launcher, 'ensure_simulator', return_value=Path('/cache/pdp10')) as ensure, \
                patch.object(launcher, 'private_emulator') as create, \
                patch.object(launcher, 'LocalGuest', return_value=guarded):
            start_guest(Path('/private/test-machine'), {6: 1234, 7: 1235})
        ensure.assert_called_once_with(Path('/assets/upstream/simh'), launcher.ROOT/'build/local-simh')
        create.assert_called_once_with(Path('/private/test-machine'), {6: 1234, 7: 1235},
                                       reuse=True, executable=Path('/cache/pdp10'))

    def test_invalid_simulator_cache_cannot_spawn_a_guest(self):
        from tools import serve_external as launcher
        with patch.object(launcher, 'ensure_simulator', side_effect=ValueError('changed cache')), \
                patch.object(launcher, 'private_emulator') as create, patch.object(launcher, 'LocalGuest'):
            with self.assertRaisesRegex(ValueError, 'cache'):
                start_guest(Path('/private/test-machine'), {6: 1234, 7: 1235})
        create.assert_not_called()

    def test_invalid_simulator_cache_is_not_retried_by_launcher(self):
        from tools import serve_external as launcher
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            with patch.object(launcher, 'prepare_machine', return_value=state), \
                    patch.object(launcher, 'LocalDatabase'), patch.object(launcher, 'isolated_writer'), \
                    patch.object(launcher, 'ensure_simulator', side_effect=ValueError('changed cache')) as ensure, \
                    patch.object(launcher, 'private_emulator') as create:
                with self.assertRaisesRegex(ValueError, 'cache'):
                    launcher.run(state, state, 0)
            self.assertEqual(ensure.call_count, 1)
            create.assert_not_called()

    def test_stopped_guest_cannot_reuse_an_old_verified_marker(self):
        guest = LocalGuest.__new__(LocalGuest)
        guest.booted, guest.stopped = True, True
        guest.scope = MagicMock(verified=True)
        guest.child = MagicMock()
        guest.child.isalive.return_value = False
        self.assertFalse(guest.monitor_scope_verified)

    def test_guest_is_not_returned_until_monitor_installation_is_verified(self):
        raw = MagicMock()
        guarded = MagicMock(monitor_scope_verified=False)
        with patch('tools.serve_external.private_emulator', return_value=raw), \
                patch('tools.serve_external.LocalGuest', return_value=guarded):
            with self.assertRaisesRegex(RuntimeError, 'monitor'):
                start_guest(Path('/private/test-machine'), {6: 1234, 7: 1235})
        guarded.boot.assert_called_once_with()
        guarded.stop.assert_called_once_with()

    def test_success_preserves_the_existing_machine_and_ports(self):
        raw = MagicMock()
        guarded = MagicMock(monitor_scope_verified=True)
        with patch('tools.serve_external.private_emulator', return_value=raw) as create, \
                patch('tools.serve_external.LocalGuest', return_value=guarded) as wrap:
            actual = start_guest(Path('/private/test-machine'), {6: 1234, 7: 1235})
        create.assert_called_once_with(Path('/private/test-machine'), {6: 1234, 7: 1235}, reuse=True,
                                       executable=Path('/cache/pdp10'))
        wrap.assert_called_once_with(raw)
        self.assertIs(actual, guarded)

    def test_failed_boot_closes_owned_emulator_and_preserves_the_failure(self):
        guarded = MagicMock()
        guarded.boot.side_effect = MonitorCompatibilityError('unsupported monitor')
        with patch('tools.serve_external.private_emulator'), \
                patch('tools.serve_external.LocalGuest', return_value=guarded):
            with self.assertRaises(MonitorCompatibilityError):
                start_guest(Path('/private/test-machine'), {6: 1234, 7: 1235})
        guarded.stop.assert_called_once_with()

    def test_cleanup_error_cannot_hide_an_incompatible_monitor(self):
        guarded = MagicMock()
        guarded.boot.side_effect = MonitorCompatibilityError('unsupported monitor')
        guarded.stop.side_effect = OSError('evidence write failed')
        with patch('tools.serve_external.private_emulator'), \
                patch('tools.serve_external.LocalGuest', return_value=guarded):
            with self.assertRaises(MonitorCompatibilityError):
                start_guest(Path('/private/test-machine'), {6: 1234, 7: 1235})

    def test_known_incompatible_monitor_is_not_retried_or_admitted(self):
        from tools import serve_external as launcher
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            with patch.object(launcher, 'prepare_machine', return_value=state), \
                    patch.object(launcher, 'LocalDatabase'), patch.object(launcher, 'isolated_writer'), \
                    patch.object(launcher, 'reserve_ports', return_value={6: 1234, 7: 1235}), \
                    patch.object(launcher, 'start_guest', side_effect=MonitorCompatibilityError('unsupported')) as start, \
                    patch.object(launcher, 'PersonaBridge') as bridge, patch.object(launcher, 'serve') as serve:
                with self.assertRaises(MonitorCompatibilityError):
                    launcher.run(state, state, 0)
        self.assertEqual(start.call_count, 1)
        bridge.assert_not_called()
        serve.assert_not_called()

    def test_failed_batch_probe_is_not_retried_or_admitted(self):
        from tools import serve_external as launcher
        from server.local_batch import BatchBootstrapError
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            machine = MagicMock()
            machine.command.return_value = ''
            with patch.object(launcher, 'prepare_machine', return_value=state), \
                    patch.object(launcher, 'LocalDatabase'), patch.object(launcher, 'isolated_writer'), \
                    patch.object(launcher, 'start_guest', return_value=machine) as start, \
                    patch.object(launcher, 'protect_bridge_terminals', return_value=False), \
                    patch.object(launcher, 'prepare_batch', side_effect=BatchBootstrapError('uncertain')), \
                    patch.object(launcher, 'NativeInspector'), patch.object(launcher, 'configure_reset_permissions'), \
                    patch.object(launcher, 'PersonaBridge') as bridge, \
                    patch.object(launcher, 'serve', new_callable=MagicMock) as serve, patch.object(launcher.asyncio, 'run'):
                with self.assertRaises(BatchBootstrapError):
                    launcher.run(state, state, 0)
            self.assertEqual(start.call_count, 1)
            bridge.assert_not_called()
            serve.assert_not_called()


class LocalAdmissionGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_server_cannot_start_without_current_boot_batch_readiness(self):
        from tools import serve_external as launcher
        guest = MagicMock(monitor_scope_verified=True, batch_ready=False)
        with tempfile.TemporaryDirectory() as directory, patch.object(launcher.web, 'AppRunner') as runner:
            runner.return_value.setup.side_effect = AssertionError('HTTP setup was attempted')
            runner.return_value.cleanup = AsyncMock()
            with self.assertRaisesRegex(RuntimeError, 'batch'):
                await launcher.serve(guest, MagicMock(), Path(directory), 0)
            runner.assert_not_called()

    async def test_http_server_cannot_start_with_an_uncorrected_guest(self):
        from tools import serve_external as launcher
        guest = MagicMock(monitor_scope_verified=False)
        with tempfile.TemporaryDirectory() as directory, patch.object(launcher.web, 'AppRunner') as runner:
            runner.return_value.setup.side_effect = AssertionError('HTTP setup was attempted')
            with self.assertRaisesRegex(RuntimeError, 'monitor'):
                await launcher.serve(guest, MagicMock(), Path(directory), 0)
            runner.assert_not_called()
