import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from tests import integration_logout_sequence as sequence


def rows(completed=4):
    result = []
    for index in range(4):
        result.append({'MESSAGE': f'Terminal session started: connection=c{index} style=original'})
        if index < completed:
            result.append({'MESSAGE': f'Terminal logout complete: connection=c{index} recovered=False'})
    return result


class SequenceTests(unittest.TestCase):
    def exercise(self, driver, journal, *, login=None, capture=None, clock=None):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(sequence, 'OUTPUT', Path(directory)), \
                 patch.object(sequence.deployment, 'run', driver), \
                 patch.object(sequence.deployment, 'invoke', Mock()) as invoke, \
                 patch.object(sequence.deployment, 'login', login or AsyncMock()) as admission, \
                 patch.object(sequence, 'journal', journal), \
                 patch.object(sequence, 'observe', capture or Mock()) as observer, \
                 patch.object(sequence, 'monotonic', clock or Mock(return_value=0)), \
                 patch.object(sequence, 'sleep') as sleep:
                sequence.run()
            report = json.loads((Path(directory) / 'report.json').read_text())
        return report, invoke, admission, observer, sleep

    def test_warning_after_second_login_fences_backup_and_next_login(self):
        failed = False

        async def login(*args, **kwargs):
            nonlocal failed
            failed = not kwargs.get('creating', False)

        def journal(cursor=None):
            if cursor is None:
                return [{'__CURSOR': 'anchor'}]
            return [{'MESSAGE': 'Terminal logout did not complete; check the guest job: connection=c1 stage=logout'}] if failed else []

        def driver(*args, **kwargs):
            sequence.deployment.invoke('fixture', 'install')
            asyncio.run(sequence.deployment.login('url', 'name', 'password', creating=True))
            sequence.deployment.invoke('fixture', 'editor')
            sequence.deployment.invoke('fixture', 'rerun')
            asyncio.run(sequence.deployment.login('url', 'name', 'password'))
            sequence.deployment.invoke('fixture', 'backup')
            self.fail('Continued after first warning')

        capture = Mock(return_value=({'outcome': 'reproduced-captured', 'connection': 'c1'}, []))
        report, invoke, login_mock, observer, sleep = self.exercise(
            driver, journal, login=AsyncMock(side_effect=login), capture=capture)
        self.assertEqual(report['outcome'], 'reproduced-captured')
        self.assertEqual([call.args[1] for call in invoke.call_args_list], ['install', 'editor', 'rerun'])
        self.assertEqual(login_mock.await_count, 2)
        observer.assert_called_once_with('anchor')
        sleep.assert_not_called()

    def test_healthy_path_retains_driver_order_without_intermediate_waits(self):
        def driver(*args, **kwargs):
            for index in range(4):
                asyncio.run(sequence.deployment.login('url', 'name', 'password', creating=index == 0))
                sequence.deployment.invoke('fixture', f'original-step-{index}')

        report, invoke, login, observer, sleep = self.exercise(
            driver, lambda cursor=None: rows() if cursor else [{'__CURSOR': 'anchor'}])
        self.assertEqual(report['outcome'], 'not-reproduced')
        self.assertEqual(login.await_count, 4)
        self.assertEqual([call.args[1] for call in invoke.call_args_list],
                         [f'original-step-{index}' for index in range(4)])
        observer.assert_not_called()
        sleep.assert_not_called()

    def test_fifth_login_is_rejected_before_dispatch(self):
        def driver(*args, **kwargs):
            for _ in range(5):
                asyncio.run(sequence.deployment.login('url', 'name', 'password'))

        report, _, login, _, _ = self.exercise(
            driver, lambda cursor=None: rows() if cursor else [{'__CURSOR': 'anchor'}])
        self.assertEqual(report['outcome'], 'experiment-error')
        self.assertEqual(login.await_count, 4)

    def test_earlier_success_does_not_hide_last_unconfirmed_cleanup(self):
        def driver(*args, **kwargs):
            for _ in range(4):
                asyncio.run(sequence.deployment.login('url', 'name', 'password'))

        report, _, _, _, sleep = self.exercise(
            driver, lambda cursor=None: rows(3) if cursor else [{'__CURSOR': 'anchor'}],
            clock=Mock(side_effect=[0, 100]))
        self.assertEqual(report['outcome'], 'cleanup-unconfirmed')
        sleep.assert_not_called()

    def test_management_error_is_retained_separately_from_logout_capture(self):
        def driver(*args, **kwargs):
            asyncio.run(sequence.deployment.login('url', 'name', 'password'))
            raise TimeoutError('fixture management failure')

        report, _, _, _, _ = self.exercise(
            driver, lambda cursor=None: [] if cursor else [{'__CURSOR': 'anchor'}])
        self.assertEqual(report['outcome'], 'experiment-error')
        self.assertEqual(report['driver_error_type'], 'TimeoutError')

    def test_warning_during_completed_host_operation_fences_next_operation(self):
        with tempfile.TemporaryDirectory() as directory:
            guard = sequence.Sequence()
            guard.cursor = 'anchor'
            warning = [{'MESSAGE': 'Terminal logout did not complete; check the guest job: connection=c1'}]
            original = Mock(return_value='completed operation')
            with patch.object(sequence, 'OUTPUT', Path(directory)), \
                 patch.object(sequence, 'journal', side_effect=[[], warning]), \
                 patch.object(sequence, 'observe', return_value=(
                     {'outcome': 'reproduced-capture-failed', 'connection': 'c1'}, warning)):
                with self.assertRaises(sequence.StopExperiment):
                    guard.invoke(original, 'fixture', 'backup')
            original.assert_called_once_with('fixture', 'backup')
            self.assertEqual(guard.report['outcome'], 'reproduced-capture-failed')

    def test_driver_error_does_not_erase_concurrent_logout_failure(self):
        failed = False

        def driver(*args, **kwargs):
            nonlocal failed
            asyncio.run(sequence.deployment.login('url', 'name', 'password'))
            failed = True
            raise TimeoutError('fixture management failure')

        def journal(cursor=None):
            if cursor is None:
                return [{'__CURSOR': 'anchor'}]
            return [{'MESSAGE': 'Terminal logout did not complete; check the guest job: connection=c1'}] if failed else []

        report, _, _, _, _ = self.exercise(driver, journal, capture=Mock(return_value=(
            {'outcome': 'reproduced-captured', 'connection': 'c1'}, [])))
        self.assertEqual(report['outcome'], 'reproduced-captured')
        self.assertEqual(report['driver_error_type'], 'TimeoutError')
