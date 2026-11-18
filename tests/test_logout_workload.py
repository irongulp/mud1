import json
import unittest
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch
from tests import integration_logout_workload as workload
from tests.integration_logout_workload import classify


class WorkloadTests(unittest.TestCase):
    def test_first_warning_stops_before_restart_or_next_login(self):
        for outcome,count in [('reproduced-captured',1),('not-reproduced',3)]:
            with self.subTest(outcome=outcome),tempfile.TemporaryDirectory() as directory:
                result={'outcome':'cycle-complete' if count==3 else outcome}
                with patch.object(workload,'OUTPUT',Path(directory)), \
                     patch.object(workload,'invoke') as invoke, \
                     patch.object(workload,'setup_options',return_value=[]), \
                     patch.object(workload,'login',AsyncMock()) as login, \
                     patch.object(workload,'journal',return_value=[{'__CURSOR':'fixture'}]), \
                     patch.object(workload,'observe',return_value=(result,[])):
                    workload.run()
                self.assertEqual(login.await_count,count)
                self.assertEqual(invoke.call_count,count)
                report=json.loads((Path(directory)/'report.json').read_text())
                self.assertEqual(report['outcome'],outcome)

    def test_warning_is_not_success_even_with_later_logout(self):
        rows=['Terminal logout did not complete; check the guest job: connection=a stage=logout',
              'Terminal logout complete: connection=a recovered=False']
        self.assertEqual(classify(rows)['outcome'],'reproduced-awaiting-capture')

    def test_capture_requires_matching_connection_and_completed_census(self):
        warning='Terminal logout did not complete; check the guest job: connection=a stage=logout'
        for connection,completed,expected in (
                ('a',True,'reproduced-captured'),
                ('a',False,'reproduced-capture-failed'),
                ('b',True,'reproduced-awaiting-capture')):
            observation='Fixture post-timeout logout observation: '+json.dumps(
                dict(connection=connection,census=dict(completed=completed)))
            self.assertEqual(classify([warning,observation])['outcome'],expected)

    def test_no_warning_requires_completed_logout(self):
        self.assertEqual(classify([])['outcome'],'pending')
        self.assertEqual(classify(['Terminal logout complete: connection=a recovered=False'])['outcome'],
                         'cycle-complete')
