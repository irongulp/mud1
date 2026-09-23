import json
import io
from contextlib import redirect_stdout, redirect_stderr
import unittest
from unittest.mock import patch, MagicMock

from tools import inspect_game as inspect


class InspectionTests(unittest.TestCase):
    def test_personas_decode_saved_state_without_password_words(self):
        text = ('MVPER 1\r\nTOTAL 2\r\n'
                'PERSON Roy 7 1234 40 41 42 43 100 12 4 1 0\r\n'
                'DELETED\r\nEND 2\r\n')
        result = inspect.parse_personas(text)
        self.assertEqual(result['deleted'], 1)
        roy = result['personas'][0]
        self.assertEqual(roy['name'], 'Roy')
        self.assertEqual(roy['score'], 1234)
        self.assertEqual(roy['stamina_max'], 43)
        self.assertTrue(roy['password_set'])
        self.assertEqual(roy['last_play_guest_day'], 100)
        self.assertNotIn('password_word', json.dumps(result))

    def test_incomplete_corrupt_and_duplicate_personas_rejected(self):
        row = 'PERSON Roy 7 1234 40 41 42 43 100 12 4 1 0\n'
        for text in ('', 'MVPER 2\nTOTAL 0\nEND 0\n',
                     'MVPER 1\nTOTAL 1\n' + row,
                     'MVPER 1\nTOTAL 2\n' + row * 2 + 'END 2\n',
                     'MVPER 1\nTOTAL 1\nPERSON malformed\nEND 1\n',
                     'MVPER 1\nTOTAL 0\nEND 1\n', 'MVPER 1\nBUSY\n'):
            with self.subTest(text=text), self.assertRaises(inspect.InspectionError):
                inspect.parse_personas(text)

    def test_filename_validation_prevents_monitor_commands_and_binary_reads(self):
        self.assertEqual(inspect.text_filename('mud.wiz'), 'MUD.WIZ')
        for name in ('MUD..PM', 'MUD.PM', 'MUD.EXE', 'MUD.WIZ\rKJOB',
                     'DSKB:MUD.LOG', '../MUD.LOG', '*.LOG', 'A.TXT[1,2]'):
            with self.subTest(name=name), self.assertRaises(inspect.InspectionError):
                inspect.text_filename(name)

    def test_native_text_is_framed_not_confused_with_monitor_prompt(self):
        self.assertEqual(inspect.parse_text('MVTXT 1\nCHAR 46\nCHAR 10\nEND\n'), '.\n')
        word = sum(ord(char) << (7 * (4-i)) for i, char in enumerate('Hello'))
        self.assertEqual(inspect.parse_text(f'MVTXT 1\nDATA {word:o} 5\nEND\n'), 'Hello')
        for text in ('MVTXT 1\nCHAR 65\n', 'MVTXT 1\nMISSING\n',
                     'MVTXT 1\nCHAR 999\nEND\n', 'MVTXT 1\nLIMIT\n'):
            with self.assertRaises(inspect.InspectionError):
                inspect.parse_text(text)

    def test_journal_arguments_are_literal_and_failures_are_not_clean_reports(self):
        command = inspect.journal_command('runtime', since='1 week ago', lines=100)
        self.assertIn('mud86-runtime.service', command)
        self.assertIn('1 week ago', command)
        with patch('tools.inspect_game.subprocess.Popen', side_effect=OSError('missing')):
            with self.assertRaises(inspect.InspectionError):
                list(inspect.journal_entries('runtime'))

    def test_failed_journal_exit_never_prints_a_clean_result(self):
        process = MagicMock()
        process.stdout = io.StringIO('')
        process.wait.return_value = 1
        with patch('tools.inspect_game.subprocess.Popen', return_value=process), \
                redirect_stdout(io.StringIO()) as output, redirect_stderr(io.StringIO()):
            self.assertEqual(inspect.main(['errors']), 1)
        self.assertNotIn('No recognised', output.getvalue())

    def test_log_file_uses_historical_log_ppn(self):
        native = inspect.NativeInspector()
        with patch.object(native, 'command', side_effect=['', 'MVTXT 1\nEND\n']) as command:
            native.text('MUD.LOG', area='logs')
        self.assertTrue(command.call_args.args[0].endswith('002600002776'))

    def test_directory_metadata_retains_original_dates_and_double_dot_extension(self):
        output = ('directory dskb:*.*[2011,2776]\r\n'
                  'MUD     .PM     3  <022>   31-Feb-26    DSKB:   [2011,2776]\r\n'
                  'MVPER   EXE    40  <057>   18-Sep-26\r\n'
                  '  Total of 43 blocks in 2 files on DSKB: [2011,2776]\r\n.')
        native = inspect.NativeInspector()
        with patch.object(native, 'command', return_value=output):
            report = native.files()
        self.assertEqual(report['files'][0], {'name': 'MUD..PM', 'blocks': 3,
                                             'protection': '022', 'modified_guest_date': '31-Feb-26'})

    def test_following_errors_keeps_requested_context(self):
        entries = [{'MESSAGE': 'boot context'}, {'MESSAGE': 'Emulator exited unexpectedly'}]
        with patch('tools.inspect_game.journal_entries', return_value=iter(entries)), \
                redirect_stdout(io.StringIO()) as output:
            self.assertEqual(inspect.main(['errors', '--follow', '--json', '--context', '1']), 0)
        report = json.loads(output.getvalue())
        self.assertEqual(report['findings'][0]['context'][0]['message'], 'boot context')

    def test_systemd_manager_messages_belong_to_target_service(self):
        report = inspect.diagnose([{'_SYSTEMD_UNIT': 'init.scope', 'UNIT': 'mud86-runtime.service',
                                   'MESSAGE': "mud86-runtime.service: Failed with result 'exit-code'."}])
        self.assertEqual(report['findings'][0]['source'], 'mud86-runtime.service')

    def test_query_timeout_aborts_and_logs_out(self):
        native = inspect.NativeInspector()
        wire = MagicMock()
        native.connection = wire
        with patch.object(native, 'receive', side_effect=['\r\n.', 'Logged-off']):
            native.__exit__(inspect.InspectionError, inspect.InspectionError('timeout'), None)
        self.assertEqual([call.args[0] for call in wire.write.call_args_list], [b'\x03\x03', b'kjob\r'])
        wire.close.assert_called_once()

    def test_queries_do_not_install_or_create_personas(self):
        native = inspect.NativeInspector()
        with patch.object(native, 'command', return_value='MVPER 1\nTOTAL 0\nEND 0\n') as command:
            self.assertEqual(native.personas()['records'], 0)
        command.assert_called_once_with('run mvper')

    def test_persona_output_is_human_readable_and_json_is_explicit(self):
        with patch('tools.inspect_game.NativeInspector') as native:
            native.return_value.__enter__.return_value.personas.return_value = inspect.parse_personas(
                'MVPER 1\nTOTAL 1\nPERSON Viewtests 1 0 40 40 40 40 1 0 0 1 0\nEND 1\n')
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(inspect.main(['personas']), 0)
            self.assertIn('Score', output.getvalue())
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(inspect.main(['personas', '--json']), 0)
            self.assertEqual(json.loads(output.getvalue())['state'], 'saved')


class DiagnosticTests(unittest.TestCase):
    def entry(self, message, source='mud86-runtime.service', priority='6', stamp='1000000'):
        return {'MESSAGE': message, '_SYSTEMD_UNIT': source,
                'PRIORITY': priority, '__REALTIME_TIMESTAMP': stamp}

    def test_known_errors_and_warnings_group_with_coverage(self):
        entries = [self.entry('Emulator exited unexpectedly'),
                   self.entry('Emulator exited unexpectedly', stamp='2000000'),
                   self.entry('Retrying guest boot (2/3)'),
                   self.entry('WARNING:server.gateway:Terminal logout did not complete; check the guest job',
                              'mud86-gateway.service')]
        result = inspect.diagnose(entries)
        self.assertEqual(result['entries_scanned'], 4)
        self.assertEqual(len(result['findings']), 3)
        finding = result['findings'][0]
        self.assertEqual(finding['severity'], 'error')
        self.assertEqual(finding['count'], 2)
        self.assertNotEqual(finding['first_seen'], finding['last_seen'])
        self.assertTrue(finding['suggestion'])

    def test_normal_output_not_keyword_matched_and_unknown_diagnostics_reviewed(self):
        entries = [self.entry('KSYS processing completed'),
                   self.entry('0 errors detected'), self.entry('Error is a player name'),
                   self.entry('Terminal connection ended normally'),
                   self.entry('?UNFAMILIAR diagnostic')]
        result = inspect.diagnose(entries)
        self.assertEqual(len(result['findings']), 1)
        self.assertEqual(result['findings'][0]['severity'], 'review')

    def test_traceback_and_journal_priority_detected(self):
        result = inspect.diagnose([
            self.entry('Traceback (most recent call last):\n  File "x", line 1\nValueError: bad'),
            self.entry('Unexpected failure', priority='3'),
            self.entry('WARNING:server.gateway:Terminal connection ended: timed out',
                       'mud86-gateway.service')])
        self.assertEqual([f['severity'] for f in result['findings']], ['error', 'error', 'warning'])

    def test_verified_native_memory_fault_is_an_error(self):
        report = inspect.diagnose([self.entry('?Illegal memory reference at user PC 400020')])
        self.assertEqual(report['findings'][0]['severity'], 'error')
        self.assertEqual(report['findings'][0]['code'], 'native-memory-fault')

    def test_binary_journal_message_and_bad_metadata_do_not_crash(self):
        result = inspect.diagnose([self.entry(list(b'?Unknown'), stamp='bad', priority='bad')])
        self.assertEqual(result['findings'][0]['severity'], 'review')
        self.assertIsNone(result['findings'][0]['first_seen'])


if __name__ == '__main__':
    unittest.main()
