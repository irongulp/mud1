import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools.ksys_capture import capture, log_name, summarize
from server.runtime import Runtime, OPERATOR_PROMPT

RESPONSE='''Event KSYS queued, request #9
 8:48:21 Batch-Stream 32 -- KSYS stream started --
 8:48:21 Batch-Stream 32 -- Begin --
                Log file:     DSKB:B10335.LOG[3,3]
'''


class KsysCaptureTests(unittest.TestCase):
    def test_capture_cannot_promote_or_replay_failed_shutdown(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime=Runtime(Path(directory),'/unused')
            runtime.child=Mock(before=RESPONSE)
            runtime.booted=True
            runtime.control_prompt=OPERATOR_PROMPT
            with patch.dict('os.environ',{'MUD86_KSYS_CAPTURE':'1'}), \
                    patch.object(runtime,'command',side_effect=TimeoutError()) as command, \
                    patch('tools.ksys_capture.capture',side_effect=OSError('capture failed')) as observed:
                self.assertFalse(runtime.stop())
            command.assert_called_once()
            observed.assert_called_once_with(runtime,RESPONSE)
            self.assertFalse(json.loads((Path(directory)/'shutdown.json').read_text())['clean'])

    def test_requires_one_exact_native_log_and_confirmed_stream(self):
        self.assertEqual(log_name(RESPONSE),'DSKB:B10335.LOG[3,3]')
        for text in ('',RESPONSE.replace('KSYS stream started','other stream'),
                     RESPONSE.replace('[3,3]','[1,2]'),RESPONSE.replace('B10335','../bad'),
                     RESPONSE+'Log file: DSKB:B12345.LOG[3,3]\n'):
            self.assertIsNone(log_name(text))

    def test_summary_does_not_publish_arguments_or_arbitrary_terminal_text(self):
        result=summarize('''8:48:21 BATCH .ATTACH 12
8:48:21 USER secret-password
8:48:22 MONITR .KJOB
8:48:23 USER ?LGNERR private account details
''','12 Jobs in use out of 35.\n12 2011,2776 0 LOGIN 10+31 SL 2\n')
        self.assertNotIn('secret',json.dumps(result))
        self.assertNotIn('private account',json.dumps(result))
        self.assertEqual(result['commands'],['ATTACH','KJOB'])
        self.assertEqual(result['error_codes'],['LGNERR'])
        self.assertEqual(result['jobs'][0]['program'],'LOGIN')

    def test_capture_reads_once_keeps_private_buffers_out_of_journal_and_no_ksys(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime=Mock(state=Path(directory))
            child=runtime.child
            old_log=child.logfile_read
            def command(text,**kwargs):
                self.assertIsNone(child.logfile_read)
                return 'private text'
            runtime.command.side_effect=command
            capture(runtime,RESPONSE)
            self.assertEqual([c.args[0] for c in runtime.command.call_args_list],
                             ['systat','type DSKB:B10335.LOG[3,3]'])
            self.assertIs(child.logfile_read,old_log)
            files=list(Path(directory).glob('ksys-failures/*/raw.json'))
            self.assertEqual(len(files),1)
            self.assertEqual(files[0].stat().st_mode & 0o777,0o600)
            self.assertIn('private text',files[0].read_text())
            self.assertNotIn('private text',files[0].with_name('summary.json').read_text())

    def test_unconfirmed_stream_never_sends_diagnostic_input(self):
        runtime=Mock()
        capture(runtime,'unconfirmed')
        runtime.child.send.assert_not_called()
        runtime.command.assert_not_called()
