import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from tests import compare_batch_preflight as comparison


class BatchComparisonTests(unittest.TestCase):
    def test_setup_failure_stops_before_idle_or_login_and_retains_phase(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(comparison,'Path',side_effect=lambda _:Path(directory)), \
                    patch.object(comparison,'invoke',side_effect=AssertionError('setup failed')) as invoke, \
                    patch.object(comparison,'login',new_callable=AsyncMock) as login, \
                    patch.object(comparison.time,'sleep') as sleep:
                with self.assertRaises(AssertionError): comparison.run(False)
            invoke.assert_called_once()
            login.assert_not_called()
            sleep.assert_not_called()
            report=json.loads((Path(directory)/'report.json').read_text())
            self.assertFalse(report['complete'])
            self.assertEqual(report['phase'],'setup')

    def test_matched_workload_has_one_shutdown_and_no_restart_after_failure(self):
        for candidate in (False,True):
            with self.subTest(candidate=candidate), tempfile.TemporaryDirectory() as directory:
                calls=[]
                def invoke(container,*command,**kwargs):
                    calls.append(command)
                    if command[0]=='journalctl': return 'BATCON idle logout\n'
                    if command[:2]==('python3.12','-c') and 'shutdown.json' in command[2]:
                        return '{"clean":false}'
                    return ''
                with patch.object(comparison,'Path',side_effect=lambda _:Path(directory)), \
                        patch.object(comparison,'invoke',side_effect=invoke), \
                        patch.object(comparison,'login',new_callable=AsyncMock) as login, \
                        patch.object(comparison.time,'sleep') as sleep:
                    with self.assertRaisesRegex(AssertionError,'shutdown failed'): comparison.run(candidate)
                self.assertEqual(login.await_count,2)
                sleep.assert_called_once_with(660)
                self.assertEqual(sum(c[:2]==('systemctl','stop') for c in calls),1)
                self.assertFalse(any(c[:2]==('systemctl','start') for c in calls))
                report=json.loads((Path(directory)/'report.json').read_text())
                self.assertFalse(report['shutdown']['clean'])
