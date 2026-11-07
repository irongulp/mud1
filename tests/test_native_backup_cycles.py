from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from tests.integration_deployment import backup_cycles


class NativeBackupCyclesTests(unittest.TestCase):
    def test_failed_backup_stops_without_another_cycle_or_login(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('tests.integration_deployment.invoke',side_effect=AssertionError('unclean')) as invoke, \
                    patch('tests.integration_deployment.saved_player',new_callable=AsyncMock) as login:
                with self.assertRaisesRegex(AssertionError,'unclean'):
                    backup_cycles('fixture','http://127.0.0.1',Path(directory),3)
            invoke.assert_called_once()
            login.assert_not_called()

    def test_bounded_success_checks_saved_login_after_each_distinct_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('tests.integration_deployment.invoke',return_value='backup') as invoke, \
                    patch('tests.integration_deployment.saved_player',new_callable=AsyncMock,return_value=6) as login:
                result=backup_cycles('fixture','http://127.0.0.1',Path(directory),3)
            self.assertEqual(result,[6,6,6])
            self.assertEqual(invoke.call_count,3)
            self.assertEqual(login.await_count,3)

    def test_cycle_count_is_bounded_before_any_command(self):
        with patch('tests.integration_deployment.invoke') as invoke:
            for count in (0,4):
                with self.assertRaises(ValueError): backup_cycles('fixture','unused',Path('/unused'),count)
        invoke.assert_not_called()
