import unittest
import tempfile
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch
from tests import integration_healthy_census as control
from tests.integration_healthy_census import verify_job


class HealthyCensusTests(unittest.TestCase):
    def test_matches_exact_line_ppn_and_program(self):
        text=' 13  2653,2653    2      MUD    10+31   SL  0 $\n'
        self.assertEqual(verify_job(text,2),13)
        for bad in (text.replace('    2 ', '    12 '),
                    text.replace('2653,2653','1,2'),
                    text.replace('MUD','LOGIN'),
                    text+text):
            with self.subTest(bad=bad),self.assertRaises(ValueError):
                verify_job(bad,2)


class HealthyControlTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_census_is_not_success_and_cleanup_still_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            reader=Mock(readuntil=AsyncMock(return_value=b'By what name shall I call you?'))
            writer=Mock()
            async def wake(reader,writer,*,progress):
                progress['line']=2
            with patch.object(control,'BASE',Path(directory)), \
                 patch.object(control.gateway.telnetlib3,'open_connection',AsyncMock(return_value=(reader,writer))), \
                 patch.object(control.gateway,'wake_monitor',wake), \
                 patch.object(control,'request_census',AsyncMock(return_value={'outcome':'already-requested'})) as census, \
                 patch.object(control.gateway,'logout_guest',AsyncMock(return_value=True)) as logout:
                with self.assertRaises(RuntimeError):
                    await control.run()
            writer.write.assert_called_once_with('login mudguest\r')
            writer.close.assert_called_once()
            census.assert_awaited_once()
            logout.assert_awaited_once()
            self.assertFalse(json.loads((Path(directory)/'healthy-report.json').read_text())['complete'])
