import unittest
import json
from pathlib import Path
import tempfile
from unittest.mock import Mock, patch
from tests.integration_monitor_comparison import history_summary, run


class MonitorComparisonTests(unittest.TestCase):
    def test_failed_boot_records_failure_and_stops_without_next_disk(self):
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'probe'
            runtime=Mock()
            runtime.boot.side_effect=TimeoutError('private terminal buffer')
            def capture(*args):
                runtime.child=None
                return dict(pc='005005')
            with patch('tests.integration_monitor_comparison.sha256',return_value='fixture'), \
                    patch('tests.integration_monitor_comparison.install_image'), \
                    patch('tests.integration_monitor_comparison.Runtime',return_value=runtime), \
                    patch('tests.integration_monitor_comparison.capture',side_effect=capture):
                with self.assertRaisesRegex(RuntimeError,'without another boot'):
                    run(output,Path('/unused'),Path('/unused'),True)
            runtime.boot.assert_called_once()
            self.assertFalse((output/'boot-2').exists())
            text=(output/'report.json').read_text()
            self.assertNotIn('private terminal buffer',text)
            self.assertFalse(json.loads(text)['complete'])

    def test_history_summary_retains_predecessor_addresses_not_accumulators(self):
        text=('PC AC EA IR\n350715  123456701234  772322  CAME 15,772322\n'
              '005005  777777777777  005005  HALT 5005\n')
        result=history_summary(text)
        self.assertEqual(result['last_pcs'],['350715','005005'])
        self.assertEqual(result['halt_5005_seen'],True)
        self.assertNotIn('123456701234',str(result))
        self.assertNotIn('772322',str(result))

    def test_non_history_text_does_not_invent_failure_chain(self):
        result=history_summary('HALT instruction, PC: 005005\n')
        self.assertFalse(result['halt_5005_seen'])
        self.assertEqual(result['last_pcs'],[])
