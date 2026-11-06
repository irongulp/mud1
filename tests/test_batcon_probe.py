import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from tools.batcon_diagnostics import ALLOCATION_FIRST, ALLOCATION_LAST, ProbeRuntime, history_summary, job_summary, run
from tools.guest_control import ControlError
from tests.integration_external_deployment import shutdown_cycles


class BatconProbeTests(unittest.TestCase):
    def test_default_admission_does_not_run_candidate_preflight(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = ProbeRuntime(Path(directory), '/unused')
            with patch.dict('os.environ', {}, clear=True), \
                    patch('tools.batcon_diagnostics.execute_probe') as execute, \
                    patch('server.runtime.Runtime.admit') as admit:
                runtime.admit()
            execute.assert_not_called()
            admit.assert_called_once()

    def test_failed_batch_probe_cannot_be_boot_retried_by_runtime(self):
        from server.local_batch import BatchBootstrapError
        with tempfile.TemporaryDirectory() as directory:
            runtime = ProbeRuntime(Path(directory), '/unused')
            with patch.dict('os.environ', {'MUD86_BATCON_WARMUP':'1'}), \
                    patch('tools.batcon_diagnostics.execute_probe', side_effect=BatchBootstrapError('unconfirmed')), \
                    patch.object(runtime, 'boot', side_effect=runtime.admit) as boot, \
                    patch('server.runtime.signal.signal'), patch('server.runtime.Runtime.admit') as admit:
                with self.assertRaises(BatchBootstrapError): runtime.run()
            boot.assert_called_once()
            admit.assert_not_called()

    def test_warmup_executes_before_admission_and_failure_cannot_admit_or_retry(self):
        from server.local_batch import BatchBootstrapError
        for failing in (False, True):
            with self.subTest(failing=failing), tempfile.TemporaryDirectory() as directory:
                runtime = ProbeRuntime(Path(directory), '/unused')
                order = []
                def execute(machine, boot_id):
                    order.append('batch')
                    if failing: raise BatchBootstrapError('no execution proof')
                    return {'boot_id':boot_id,'request':7}
                with patch.dict('os.environ', {'MUD86_BATCON_WARMUP':'1'}), \
                        patch('tools.batcon_diagnostics.execute_probe', side_effect=execute), \
                        patch('server.runtime.Runtime.admit', side_effect=lambda:order.append('admit')):
                    if failing:
                        with self.assertRaises(BatchBootstrapError): runtime.admit()
                    else:
                        runtime.admit()
                self.assertEqual(order, ['batch'] if failing else ['batch','admit'])
                self.assertEqual(runtime.stopping.is_set(), failing)

    def test_external_cycle_stops_on_unclean_marker_without_restarting(self):
        from unittest.mock import AsyncMock
        observations = []
        with patch('tests.integration_external_deployment.login', new_callable=AsyncMock), \
                patch('tests.integration_external_deployment.invoke', side_effect=['', '{"clean": false}']) as invoke:
            with self.assertRaisesRegex(AssertionError, 'not clean'):
                shutdown_cycles('fixture', 'http://127.0.0.1:48080', 'Fixture', 'testpass', 3, observations)
        self.assertEqual(len(observations), 1)
        self.assertFalse(observations[0]['clean'])
        self.assertEqual(invoke.call_count, 2)
        self.assertEqual(invoke.call_args_list[0].args, ('fixture', 'systemctl', 'stop', 'mud86-runtime.service'))

    def test_external_cycles_restart_only_between_confirmed_clean_stops(self):
        from unittest.mock import AsyncMock
        observations = []
        def invoke(container, *command):
            return '{"clean": true}' if command[0] == 'python3.12' else ''
        with patch('tests.integration_external_deployment.login', new_callable=AsyncMock) as login, \
                patch('tests.integration_external_deployment.invoke', side_effect=invoke) as command:
            shutdown_cycles('fixture', 'http://127.0.0.1:48080', 'Fixture', 'testpass', 2, observations)
        self.assertEqual([item['clean'] for item in observations], [True, True])
        self.assertEqual(login.await_count, 2)
        starts = [call for call in command.call_args_list if call.args[1:] == ('mud86ctl', 'start')]
        self.assertEqual(len(starts), 1)

    def test_pending_ksys_is_sampled_early_with_one_original_deadline(self):
        import pexpect
        with tempfile.TemporaryDirectory() as directory:
            runtime = ProbeRuntime(Path(directory), '/unused')
            runtime.child = Mock(before='Event KSYS queued\nOPR>')
            original = Mock(side_effect=[pexpect.TIMEOUT('pending'), 0])
            with patch.object(runtime, 'sample_kernel', return_value='') as sample, \
                    patch('tools.batcon_diagnostics.time.monotonic', side_effect=[0, 11]):
                self.assertEqual(runtime.wait_shutdown(original, 'KSYS processing completed', timeout=90), 0)
            self.assertEqual([call.kwargs['timeout'] for call in original.call_args_list], [10, 79])
            sample.assert_called_once_with('early')
            runtime.child.send.assert_not_called()

    def test_native_completion_during_sampling_is_not_lost_or_replayed(self):
        import pexpect
        with tempfile.TemporaryDirectory() as directory:
            runtime = ProbeRuntime(Path(directory), '/unused')
            runtime.child = Mock(before='Event KSYS queued\nOPR>')
            original = Mock(side_effect=pexpect.TIMEOUT('pending'))
            native = '\r\n17:00:00          -- KSYS processing completed --\r\nOPR>'
            with patch.object(runtime, 'sample_kernel', return_value=native):
                self.assertEqual(runtime.wait_shutdown(original, 'KSYS processing completed', timeout=90), 0)
            original.assert_called_once()
            self.assertIn(native, runtime.child.before)
            self.assertEqual(runtime.child.after, 'KSYS processing completed')
            runtime.child.send.assert_not_called()

    def test_capture_keeps_raw_data_private_and_checks_code_before_reading_counts(self):
        for compatible, accumulator in ((True, 1), (True, 5), (False, 1)):
            with self.subTest(compatible=compatible, accumulator=accumulator), tempfile.TemporaryDirectory() as directory:
                runtime = ProbeRuntime(Path(directory), '/unused')
                runtime.child = Mock(before='Event KSYS queued\nBATCON failed to startup\nprivate payload')
                saved_log = runtime.child.logfile_read
                console = Mock(at_prompt=True)
                console.register.return_value = 0
                console.command.return_value = '531142  123456701234  012345  MOVE 1,23456\n'
                code = dict.fromkeys(range(ALLOCATION_FIRST, ALLOCATION_LAST+1), 0)
                for offset in range(5):
                    code[ALLOCATION_FIRST+offset] = ((0o200 if offset == 0 else 0o270) << 27
                        | accumulator << 23 | 0o100+offset)
                if not compatible:
                    code[ALLOCATION_FIRST] = 0
                def words(first, last=None):
                    self.assertIsNone(runtime.child.logfile_read)
                    return code if last is not None else {first: 7}
                console.words.side_effect = words
                with patch('tools.batcon_diagnostics.SimulatorConsole', return_value=console), \
                        patch('tools.batcon_diagnostics.time.sleep'), \
                        patch('server.runtime.Runtime.command', return_value='Status of KS10'):
                    runtime.capture_failure()
                self.assertIs(runtime.child.logfile_read, saved_log)
                self.assertNotIn('private payload', json.dumps(runtime.probe))
                self.assertNotIn('123456701234', json.dumps(runtime.probe))
                self.assertEqual(len(runtime.probe['allocation_page_counts']), 5 if compatible else 0)
                self.assertEqual(console.words.call_count, 6 if compatible else 1)
                for path in runtime.capture_directory.glob('*.private.json'):
                    self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertIn('private payload', (runtime.capture_directory/'ksys-response.private.json').read_text())

    def test_failed_boot_publishes_summary_and_never_attempts_another_boot(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'probe'
            runtime = Mock(probe={})
            runtime.boot.side_effect = TimeoutError('private terminal payload')
            def stop():
                runtime.child = None
                return False
            runtime.stop.side_effect = stop
            with patch('tools.batcon_diagnostics.ProbeRuntime', return_value=runtime), \
                    patch('tools.batcon_diagnostics.install_image'), \
                    patch('tools.batcon_diagnostics.sha256', return_value='fixture'):
                with self.assertRaisesRegex(RuntimeError, 'probe failed'):
                    run(output, Path('/unused'), Path('/unused'), boots=3)
            summary = (output/'summary-1.json').read_text()
            self.assertIn('TimeoutError', summary)
            self.assertNotIn('private terminal payload', summary)
            self.assertFalse((output/'boot-2').exists())
            runtime.boot.assert_called_once()
            runtime.stop.assert_called_once()

    def test_failed_configuration_stop_never_reboots_or_stops_twice(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'probe'
            runtime = Mock(probe={})
            def stop():
                runtime.child = None
                return False
            runtime.stop.side_effect = stop
            with patch('tools.batcon_diagnostics.ProbeRuntime', return_value=runtime), \
                    patch('tools.batcon_diagnostics.install_image'), \
                    patch('tools.batcon_diagnostics.sha256', return_value='fixture'), \
                    patch('tools.batcon_diagnostics.protect_bridge_terminals', return_value=True):
                with self.assertRaisesRegex(RuntimeError, 'probe failed'):
                    run(output, Path('/unused'), Path('/unused'), boots=3)
            runtime.boot.assert_called_once()
            runtime.stop.assert_called_once()
            observation = json.loads((output/'summary-1.json').read_text())['observations'][0]
            self.assertFalse(observation['configuration_shutdown_clean'])
            self.assertFalse(observation['clean'])

    def test_history_summary_contains_addresses_counts_but_no_operand_data(self):
        history = ('PC       AC       ea       IR\n'
                   '531142  123456701234  012345  MOVE 1,23456\n'
                   '531155  777777777777  012345  PUSHJ 17,531053\n'
                   '531142  654321076543  012345  MOVE 1,23456\n')
        result = history_summary(history)
        self.assertEqual(result['samples'], 3)
        self.assertEqual(result['top_pcs'][0], {'pc': '531142', 'count': 2})
        self.assertEqual(result['allocation_wait_samples'], 3)
        self.assertNotIn('123456701234', str(result))
        self.assertNotIn('MOVE', str(result))

    def test_job_summary_requires_whole_census_and_identifies_startup_stub(self):
        status = ('Status of KS10\n3 Jobs in use out of 35.\n'
                  'Job    Who     Line#    What   Size(P)  State   Run Time\n'
                  ' 1    [OPR]     DET41   BATCON  5        RN      83\n'
                  ' 3    [OPR]     CTY     SYSTAT  22+SPY   RN       0\n'
                  ' 9    [OPR]     DET41   QUASAR  115+40   SL       0\n'
                  'High Segments:\nNo busy devices\nSystem File Structures:\nTotal Free 1234\n')
        result = job_summary(status)
        self.assertTrue(result['complete'])
        self.assertEqual(result['batcon'], [{'job': 1, 'pages': 5, 'state': 'RN'}])
        self.assertFalse(job_summary(status.replace('3 Jobs', '4 Jobs'))['complete'])
        self.assertFalse(job_summary(status.split('High Segments:')[0])['complete'])

    def test_submitted_ksys_failure_captures_once_without_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = ProbeRuntime(Path(directory), '/unused')
            runtime.child = Mock(before='Event KSYS queued\nBATCON failed to startup\nOPR>')
            with patch('server.runtime.Runtime.command', side_effect=TimeoutError('private buffer')) as command, \
                    patch.object(runtime, 'capture_failure') as capture:
                with self.assertRaises(TimeoutError):
                    runtime.command('set ksys now')
            command.assert_called_once()
            capture.assert_called_once()

    def test_unsubmitted_echo_failure_does_not_claim_batcon_startup_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = ProbeRuntime(Path(directory), '/unused')
            runtime.child = Mock(before='stale BATCON failed to startup')
            error = ControlError('bad echo', input_started=True, submitted=False)
            with patch('server.runtime.Runtime.command', side_effect=error), \
                    patch.object(runtime, 'capture_failure') as capture:
                with self.assertRaises(ControlError):
                    runtime.command('set ksys now')
            capture.assert_not_called()

    def test_diagnostic_error_never_replaces_original_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = ProbeRuntime(Path(directory), '/unused')
            runtime.child = Mock(before='Event KSYS queued')
            with patch('server.runtime.Runtime.command', side_effect=TimeoutError('original')), \
                    patch.object(runtime, 'capture_failure', side_effect=OSError('capture failed')):
                with self.assertRaisesRegex(TimeoutError, 'original'):
                    runtime.command('set ksys now')
            self.assertEqual(runtime.probe['capture_error_type'], 'OSError')

    def test_summary_write_failure_does_not_replace_ksys_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = ProbeRuntime(Path(directory), '/unused')
            runtime.child = Mock(before='Event KSYS queued')
            runtime.capture_directory.mkdir(parents=True)
            with patch('server.runtime.Runtime.command', side_effect=TimeoutError('original')), \
                    patch.object(runtime, 'capture_failure'), \
                    patch('tools.batcon_diagnostics.private_json', side_effect=OSError('disk full')):
                with self.assertRaisesRegex(TimeoutError, 'original'):
                    runtime.command('set ksys now')
            self.assertEqual(runtime.probe['capture_publish_error_type'], 'OSError')

    def test_runtime_entry_point_preserves_backend_and_transport_arguments(self):
        import argparse
        from server.runtime import main
        args = argparse.Namespace(state=Path('/private/state'), simh=Path('/private/pdp10'),
                                  port=32123, idle=False, persona_config='/private/personas.json')
        runtime_class = Mock()
        with patch('server.runtime.argparse.ArgumentParser.parse_args', return_value=args):
            main(runtime_class=runtime_class)
        runtime_class.assert_called_once_with(args.state.resolve(), args.simh.resolve(),
                                             args.port, args.idle, args.persona_config)
        runtime_class.return_value.run.assert_called_once()
