import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from server.runtime import Runtime, MONITOR_PROMPT


class BatchProofTests(unittest.TestCase):
    name = 'mbabcd'
    nonce = 'A' * 32

    def test_invalid_deadline_never_opens_a_guest_connection(self):
        from tools import batch_readiness as batch
        for timeout in (0, -1, float('inf'), float('nan')):
            with self.subTest(timeout=timeout), patch.object(batch, 'BatchInspector') as factory:
                with self.assertRaises(ValueError):
                    batch.ensure_batch_ready(2020, timeout=timeout)
                factory.assert_not_called()

    def log(self):
        return ('  Job MBABCD Req #6 for RICHARD [2011,2776] in stream 0\n'
                '  Control file: DSKB:MBABCD.CTL[2011,2776]\n'
                '  Log file:     DSKB:MBABCD.LOG[2011,2776]\n'
                '22:58:59 MONITR .type mbabcd.txt\n'
                '22:58:59 USER   MUD86 BATCH READY ' + self.nonce + '\n'
                '22:58:59 BATCH  .KJOB/BATCH\n'
                '22:58:59 USER   Logged-off TTY43 at 22:59\n'
                '22:58:59 USER   Disk Reads:1, Writes:2, Blocks saved:7220\n')

    def test_proof_requires_execution_and_logout_for_current_request(self):
        from tools.batch_readiness import probe_completed
        self.assertTrue(probe_completed(self.log(), self.name, 6, self.nonce))
        variants = [self.log().replace('Req #6', 'Req #7'),
                    self.log().replace(self.nonce, 'B' * 32),
                    self.log().replace('USER   MUD86', 'MONITR MUD86'),
                    self.log().split('22:58:59 BATCH')[0],
                    self.log().replace('RICHARD [2011,2776]', 'OPR [1,2]'),
                    self.log() + self.log()]
        for value in variants:
            with self.subTest(value=value):
                self.assertFalse(probe_completed(value, self.name, 6, self.nonce))

    def test_vt100_tabbed_log_has_the_same_proof_as_text_terminal(self):
        from tools.batch_readiness import probe_completed
        text = self.log().replace('  Job', '\tJob').replace('  Control', '\tControl')
        text = text.replace('  Log', '\tLog').replace('USER   ', 'USER\t').replace('BATCH  ', 'BATCH\t')
        self.assertTrue(probe_completed(text, self.name, 6, self.nonce))
        self.assertFalse(probe_completed(text.replace(self.nonce, 'B' * 32), self.name, 6, self.nonce))

    def test_queued_message_is_not_readiness_and_names_are_bound(self):
        from tools.batch_readiness import parse_submission, probe_completed, BatchReadinessError
        text = '[Batch job MBABCD queued, request #6, limit 0:05:00]'
        self.assertEqual(parse_submission(text, self.name), 6)
        self.assertFalse(probe_completed(text, self.name, 6, self.nonce))
        for bad in (text.replace('MBABCD', 'OTHER'), text + '\n' + text, '?Queue unavailable'):
            with self.assertRaises(BatchReadinessError):
                parse_submission(bad, self.name)

    def test_files_are_unique_and_failure_preserves_the_probe(self):
        from tools import batch_readiness as batch
        native = Mock()
        native.__enter__ = Mock(return_value=native)
        native.__exit__ = Mock(return_value=False)
        native.command.side_effect = ['%WLDNSF No such files as mbabcd.*\r\n.',
                                     '[Batch job MBABCD queued, request #6, limit 0:05:00]',
                                     RuntimeError('transport failed')]
        with patch.object(batch, 'BatchInspector', return_value=native), \
                patch.object(batch, 'new_name', return_value='mbabcd'), \
                patch.object(batch, 'put_text'):
            with self.assertRaises(RuntimeError):
                batch.ensure_batch_ready(2020)
        self.assertFalse(any(c.args[0].startswith('delete ') for c in native.command.call_args_list))

    def test_success_does_not_overwrite_collision_and_deletes_only_owned_files(self):
        from tools import batch_readiness as batch
        native = Mock()
        native.__enter__ = Mock(return_value=native)
        native.__exit__ = Mock(return_value=False)
        native.command.side_effect = ['EXISTING FILE', '%WLDNSF No such files as mbabcd.*\r\n.',
            '[Batch job MBABCD queued, request #6, limit 0:05:00]', '[The queues are empty]',
            'MBABCD LOG', self.log(), '.', '.', '.']
        with patch.object(batch, 'BatchInspector', return_value=native), \
                patch.object(batch, 'new_name', side_effect=['mbffff', 'mbabcd']), \
                patch.object(batch.secrets, 'token_hex', return_value=self.nonce), \
                patch.object(batch, 'put_text') as put:
            self.assertEqual(batch.ensure_batch_ready(2020), {'name':'mbabcd','request':6})
        self.assertEqual([c.args[1] for c in put.call_args_list], ['mbabcd.txt','mbabcd.ctl'])
        self.assertEqual([c.args[0] for c in native.command.call_args_list if c.args[0].startswith('delete ')],
                         ['delete mbabcd.ctl','delete mbabcd.txt','delete mbabcd.log'])
        submitted = next(c.args[0] for c in native.command.call_args_list if c.args[0].startswith('submit '))
        self.assertIn('/output:nolog', submitted)
        self.assertIn('/norestart', submitted)

    def test_active_batch_log_is_not_read_before_request_leaves_queue(self):
        from tools import batch_readiness as batch
        native = Mock()
        native.__enter__ = Mock(return_value=native)
        native.__exit__ = Mock(return_value=False)
        queries = [0]
        def command(text):
            if text == 'directory mbabcd.*': return '%WLDNSF No such files as mbabcd.*\r\n.'
            if text == 'submit mbabcd/list:all':
                queries[0] += 1
                return '[The queues are empty]' if queries[0] >= 3 else 'MBABCD still queued or running'
            if text.startswith('submit '): return '[Batch job MBABCD queued, request #6, limit 0:05:00]'
            if text == 'type mbabcd.log':
                self.assertGreaterEqual(queries[0], 3, 'TYPE raced the active log writer')
                return self.log()
            return 'MBABCD LOG'
        native.command.side_effect = command
        with patch.object(batch, 'BatchInspector', return_value=native), \
                patch.object(batch, 'new_name', return_value='mbabcd'), \
                patch.object(batch.secrets, 'token_hex', return_value=self.nonce), \
                patch.object(batch, 'put_text'), patch.object(batch.time, 'sleep'):
            self.assertEqual(batch.ensure_batch_ready(2020)['request'], 6)

    def test_queued_but_unexecuted_probe_is_bounded_and_retained(self):
        from tools import batch_readiness as batch
        now = [0.0]
        native = Mock()
        native.__enter__ = Mock(return_value=native)
        native.__exit__ = Mock(return_value=False)
        def command(text):
            if text.startswith('submit '):
                return '[Batch job MBABCD queued, request #6, limit 0:05:00]'
            return '%WLDNSF No such files as ' + text.split(' ',1)[1] + '\r\n.'
        native.command.side_effect = command
        def sleep(seconds): now[0] += seconds
        with patch.object(batch, 'BatchInspector', return_value=native), \
                patch.object(batch, 'new_name', return_value='mbabcd'), patch.object(batch, 'put_text'), \
                patch.object(batch.time, 'monotonic', side_effect=lambda: now[0]), \
                patch.object(batch.time, 'sleep', side_effect=sleep):
            with self.assertRaises(batch.BatchReadinessError):
                batch.ensure_batch_ready(2020, timeout=1)
        self.assertLessEqual(now[0], 1)
        self.assertFalse(any(c.args[0].startswith('delete ') for c in native.command.call_args_list))


class RuntimeBatchTests(unittest.TestCase):
    def test_drain_requires_both_native_stream_acknowledgements(self):
        for streams in (('0', '1'), ('1', '0'), ('0', '0')):
            with self.subTest(streams=streams):
                machine = Runtime(Path('/unused'), '/unused')
                machine.child = Mock(before='')
                machine.control_prompt = 'OPR>'
                frames = iter(streams)
                def acknowledge(*args, **kwargs):
                    try:
                        stream = next(frames)
                    except StopIteration:
                        raise TimeoutError('missing stream shutdown')
                    machine.child.after = '\r\n12:00:00        Batch-Stream ' + stream + '  -- Shutdown --\r\n'
                machine.child.expect.side_effect = acknowledge
                table = '\nJob Who Line# What Size(P) State Run Time\n 3 [OPR] CTY SYSTAT 22 RN 0\nHigh Segments:\n'
                def command_result(text, *args, **kwargs):
                    return table if text == 'systat' else 'shutdown batch-stream 0:1\r\nOPR>'
                with patch.object(machine, 'command', side_effect=command_result) as command:
                    if streams == ('0', '0'):
                        with self.assertRaises(TimeoutError):
                            machine.drain_batch()
                        self.assertIsNone(machine.control_prompt)
                    else:
                        machine.drain_batch()
                        self.assertEqual(machine.control_prompt, 'OPR>')
                        machine.child.expect_exact.assert_called_once()
                    self.assertEqual(sum(call.args[0].startswith('shutdown') for call in command.call_args_list), 1)

    def test_batch_pty_job_must_disappear_after_shutdown_acknowledgement(self):
        from server.runtime import batch_pty_jobs
        table = '\nJob Who Line# What Size(P) State Run Time\n 2 2011,2776 P0J12 10 ^C 0 $\nHigh Segments:\n'
        self.assertEqual(batch_pty_jobs(table), [2])
        self.assertEqual(batch_pty_jobs(table.replace('P0J12', '1')), [])
        with self.assertRaises(RuntimeError):
            batch_pty_jobs('incomplete SYSTAT output')

    def test_browser_terminal_setup_requires_clean_reboot_before_admission(self):
        with tempfile.TemporaryDirectory() as directory:
            machine = Runtime(Path(directory), '/unused', browser_terminals=True)
            events = []
            def prepare(runtime):
                events.append('prepare')
                return events.count('prepare') == 1
            with patch('server.runtime.wait_listener'), patch('pexpect.spawn'), \
                    patch.object(machine.stopping, 'wait', return_value=False), \
                    patch.object(machine, 'command', return_value=''), \
                    patch('tools.terminal_config.protect_bridge_terminals', side_effect=prepare), \
                    patch('server.runtime.probe_game', side_effect=lambda port: events.append('game')), \
                    patch.object(machine, 'verify_batch', side_effect=lambda: events.append('batch')), \
                    patch.object(machine, 'stop', side_effect=lambda: events.append('stop') or True):
                machine.boot()
            self.assertEqual(events, ['prepare', 'batch', 'stop', 'prepare', 'game', 'batch'])

    def test_failed_terminal_setup_shutdown_never_admits_players(self):
        with tempfile.TemporaryDirectory() as directory:
            machine = Runtime(Path(directory), '/unused', browser_terminals=True)
            with patch('server.runtime.wait_listener'), patch('pexpect.spawn'), \
                    patch.object(machine.stopping, 'wait', return_value=False), \
                    patch.object(machine, 'command'), \
                    patch('tools.terminal_config.protect_bridge_terminals', return_value=True), \
                    patch.object(machine, 'verify_batch'), patch.object(machine, 'stop', return_value=False), \
                    patch('server.runtime.probe_game') as game, self.assertRaises(RuntimeError):
                machine.boot()
            game.assert_not_called()

    def test_batch_check_follows_private_transport_probe_and_blocks_readiness(self):
        with tempfile.TemporaryDirectory() as directory:
            machine = Runtime(Path(directory), '/unused')
            machine.stopping = Mock()
            machine.stopping.is_set.return_value = False
            machine.stopping.wait.return_value = False
            events = []
            def fail_batch():
                events.append('batch')
                raise RuntimeError('no batch')
            with patch('server.runtime.wait_listener'), patch('pexpect.spawn'), \
                    patch.object(machine, 'command'), \
                    patch('server.runtime.probe_game', side_effect=lambda port: events.append('game')), \
                    patch.object(machine, 'verify_batch', side_effect=fail_batch), \
                    self.assertRaises(RuntimeError):
                machine.boot()
            self.assertFalse(machine.batch_ready)
            self.assertEqual(events, ['game', 'batch'])

    def test_shutdown_checks_batch_before_requesting_ksys(self):
        with tempfile.TemporaryDirectory() as directory:
            machine = Runtime(Path(directory), '/unused')
            machine.child = Mock(before='', after='sim>')
            machine.booted = machine.batch_ready = True
            machine.control_prompt = MONITOR_PROMPT
            events = []
            def command(text, prompt, **kwargs):
                events.append(text)
                machine.control_prompt = prompt
                return prompt
            with patch.object(machine, 'verify_batch', side_effect=lambda: events.append('batch-ready')), \
                    patch.object(machine, 'drain_batch', side_effect=lambda **kwargs: events.append('batch-drained')), \
                    patch.object(machine, 'command', side_effect=command):
                self.assertTrue(machine.stop())
            self.assertEqual(events, ['batch-ready', 'r opr', 'batch-drained', 'set ksys now'])
            self.assertTrue(json.loads((Path(directory)/'shutdown.json').read_text())['clean'])

    def test_failed_batch_check_cannot_publish_clean_backup_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            machine = Runtime(Path(directory), '/unused')
            machine.child = Mock()
            machine.booted = machine.batch_ready = True
            machine.control_prompt = MONITOR_PROMPT
            def command(text, prompt, **kwargs):
                machine.control_prompt = prompt
                return prompt
            with patch.object(machine, 'verify_batch', side_effect=RuntimeError('batch unavailable')), \
                    patch.object(machine, 'drain_batch'), \
                    patch.object(machine, 'command', side_effect=command):
                self.assertFalse(machine.stop())
            self.assertFalse(json.loads((Path(directory)/'shutdown.json').read_text())['clean'])

    def test_unconfirmed_batch_drain_blocks_ksys_and_clean_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            machine = Runtime(Path(directory), '/unused')
            machine.child = Mock()
            machine.booted = machine.batch_ready = True
            machine.control_prompt = MONITOR_PROMPT
            with patch.object(machine, 'verify_batch'), \
                    patch.object(machine, 'drain_batch', side_effect=TimeoutError('missing acknowledgement')), \
                    patch.object(machine, 'command') as commands:
                self.assertFalse(machine.stop())
            self.assertNotIn('set ksys now', [call.args[0] for call in commands.call_args_list])
            self.assertFalse(json.loads((Path(directory)/'shutdown.json').read_text())['clean'])
