import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, Mock

from tests.logout_timing import observe_timed_logout


REPORT = (b'kjob\r\nprivate name\r\nLogged-off TTY0\r\n'
          b'Runtime: 0\r\nDisk Reads:1, Writes:2, Blocks saved:0\r\n\r\n.')


class TimingTests(unittest.IsolatedAsyncioTestCase):
    async def test_passive_only_waits_through_comparison_window_without_census(self):
        reader, writer, emit = asyncio.StreamReader(), Mock(), Mock()
        reader.feed_data(b'kjob\r\n')
        original = AsyncMock(return_value=False)
        task = asyncio.create_task(observe_timed_logout(
            original, reader, writer, emit=emit, passive_only=True,
            seconds=.02, request_seconds=.2, connection_id='passive'))
        await asyncio.sleep(.04)
        self.assertFalse(task.done())
        reader.feed_data(REPORT[6:])
        self.assertFalse(await task)
        original.assert_awaited_once_with(reader, writer, connection_id='passive')
        writer.write.assert_not_called()
        writer.close.assert_not_called()
        record = emit.call_args.args[0]
        self.assertEqual(record['timing_mode'], 'passive-only')
        self.assertAlmostEqual(record['passive_seconds'], .22)
        self.assertEqual(record['census'], dict(outcome='disabled-passive-only'))
        self.assertNotIn('census_requested_at', record)
        self.assertTrue(record['late_complete'])
        self.assertNotIn('private name', json.dumps(record))

    async def test_passive_only_default_budget_is_22_and_success_skips_observation(self):
        for success in (False, True):
            reader, writer, emit = asyncio.StreamReader(), Mock(), Mock()
            reader.feed_data(REPORT)
            result = await observe_timed_logout(
                AsyncMock(return_value=success), reader, writer, emit=emit, passive_only=True)
            self.assertEqual(result, success)
            writer.write.assert_not_called()
            if success:
                emit.assert_not_called()
            else:
                self.assertEqual(emit.call_args.args[0]['passive_seconds'], 22)

    async def test_passive_only_rejects_census_before_original_or_input(self):
        original, census, writer = AsyncMock(), AsyncMock(), Mock()
        with self.assertRaises(ValueError):
            await observe_timed_logout(original, asyncio.StreamReader(), writer,
                                       emit=Mock(), passive_only=True, census=census)
        original.assert_not_awaited()
        census.assert_not_awaited()
        writer.write.assert_not_called()

    async def test_passive_only_silence_times_out_and_reaps_reader(self):
        reader, emit, writer = asyncio.StreamReader(), Mock(), Mock()
        started = time.monotonic()
        self.assertFalse(await observe_timed_logout(
            AsyncMock(return_value=False), reader, writer, emit=emit, passive_only=True,
            seconds=.01, request_seconds=.02))
        self.assertLess(time.monotonic() - started, .3)
        record = emit.call_args.args[0]
        self.assertEqual(record['outcome'], 'timeout')
        self.assertEqual(record['census'], dict(outcome='disabled-passive-only'))
        self.assertNotIn('first_new_data_at', record)
        self.assertFalse(record['late_complete'])
        writer.write.assert_not_called()
        reader.feed_data(b'x')
        self.assertEqual(await reader.read(1), b'x')

    def test_passive_only_installed_launcher_selects_mode_and_rejects_census(self):
        checkout = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            release = Path(directory).resolve()
            for name in ('server', 'tools'):
                (release / name).symlink_to(checkout / name, target_is_directory=True)
            for census in ('0', '1'):
                environment = dict(os.environ, PYTHONPATH=str(release),
                                   MUD86_LOGOUT_TIMING='1', MUD86_LOGOUT_PASSIVE_ONLY='1',
                                   MUD86_LOGOUT_CENSUS=census)
                result = subprocess.run(
                    [sys.executable, '-c',
                     'import sys,runpy,asyncio;from unittest.mock import AsyncMock,Mock;'
                     'sys.path.insert(0,sys.argv[1]);import logout_timing;from server import gateway;'
                     'probe=AsyncMock(return_value=False);logout_timing.observe_timed_logout=probe;'
                     'gateway.main=lambda:asyncio.run(gateway.logout_guest(Mock(),Mock()));'
                     'runpy.run_path(sys.argv[1]+"/logout_observer.py",run_name="__main__");'
                     'assert probe.await_count==1;'
                     'assert probe.call_args.kwargs["passive_only"] is True;'
                     'assert probe.call_args.kwargs["census"] is None;'
                     'assert "tests" not in sys.modules',
                     str(checkout / 'tests')],
                    cwd=release, env=environment, capture_output=True, text=True, timeout=15)
                if census == '0':
                    self.assertEqual(result.returncode, 0, result.stderr)
                else:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('Passive-only observation forbids census', result.stderr)

    def test_fixture_imports_from_installed_release_without_tests_package(self):
        checkout = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            release = Path(directory).resolve()
            for name in ('server', 'tools'):
                (release / name).symlink_to(checkout / name, target_is_directory=True)
            environment = dict(os.environ, PYTHONPATH=str(release),
                               MUD86_LOGOUT_TIMING='1', MUD86_LOGOUT_CENSUS='1')
            result = subprocess.run(
                [sys.executable, '-c',
                 'import sys; sys.path.insert(0, sys.argv[1]); '
                 'import logout_timing; import server.gateway; '
                 'assert server.gateway.__file__.startswith(sys.argv[2]), server.gateway.__file__; '
                 'assert "tests" not in sys.modules; '
                 'import runpy; from pathlib import Path; '
                 'launcher = str(Path(sys.argv[1]) / "logout_observer.py"); '
                 'sys.argv = [launcher, "--help"]; runpy.run_path(launcher, run_name="__main__")',
                 str(checkout / 'tests'), str(release)],
                cwd=release, env=environment, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)

    async def test_passive_completion_skips_census_and_preserves_failure(self):
        reader = asyncio.StreamReader()
        reader.feed_data(b'kjob\r\n')
        writer, emit, census = Mock(), Mock(), AsyncMock()
        task = asyncio.create_task(observe_timed_logout(
            AsyncMock(return_value=False), reader, writer, emit=emit, census=census,
            seconds=.1, request_seconds=.1, connection_id='test'))
        await asyncio.sleep(.01)
        reader.feed_data(REPORT[6:])
        self.assertFalse(await task)
        census.assert_not_awaited()
        writer.write.assert_not_called()
        record = emit.call_args.args[0]
        self.assertTrue(record['late_complete'])
        self.assertEqual(record['census']['outcome'], 'not-requested-passive-complete')
        self.assertGreaterEqual(record['prompt_observed_at'], record['first_new_data_at'])
        self.assertNotIn('private name', json.dumps(record))

    async def test_reader_observes_completion_while_census_is_still_running(self):
        reader = asyncio.StreamReader()
        reader.feed_data(b'kjob\r\n')
        started = time.monotonic()
        emit, writer = Mock(), Mock()

        async def census(*args):
            # The initial silent interval precedes any request.
            self.assertGreaterEqual(time.monotonic() - started, .02)
            before = time.monotonic()
            reader.feed_data(REPORT[6:30])
            await asyncio.sleep(.01)
            reader.feed_data(REPORT[30:])
            await asyncio.sleep(.02)
            return dict(completed=True, cty_first_write_before=before,
                        command_returned_at=time.monotonic())

        self.assertFalse(await observe_timed_logout(
            AsyncMock(return_value=False), reader, writer, emit=emit, census=census,
            seconds=.02, request_seconds=.2))
        record = emit.call_args.args[0]
        self.assertTrue(record['late_complete'])
        self.assertLess(record['prompt_observed_at'], record['census']['command_returned_at'])
        self.assertGreaterEqual(record['first_new_data_at'], record['census']['cty_first_write_before'])
        writer.write.assert_not_called()

    async def test_eof_or_unexpected_prompt_ends_passive_phase_without_input(self):
        for payload in (b'', b'\r\n.'):
            with self.subTest(payload=payload):
                reader = asyncio.StreamReader()
                reader.feed_data(payload)
                reader.feed_eof()
                census, emit = AsyncMock(), Mock()
                self.assertFalse(await observe_timed_logout(
                    AsyncMock(return_value=False), reader, Mock(), emit=emit, census=census,
                    seconds=.02, request_seconds=.02))
                census.assert_not_awaited()
                self.assertFalse(emit.call_args.args[0]['late_complete'])

    async def test_silent_request_is_bounded_and_cancelled_without_extra_input(self):
        reader, emit, writer = asyncio.StreamReader(), Mock(), Mock()
        census = AsyncMock(side_effect=lambda *args: None)
        cancelled = asyncio.Event()

        async def stalled(*args):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        census.side_effect = stalled
        started = time.monotonic()
        self.assertFalse(await observe_timed_logout(
            AsyncMock(return_value=False), reader, writer, emit=emit, census=census,
            seconds=.01, request_seconds=.02))
        self.assertLess(time.monotonic() - started, .3)
        self.assertTrue(cancelled.is_set())
        self.assertEqual(emit.call_args.args[0]['outcome'], 'timeout')
        census.assert_awaited_once()
        writer.write.assert_not_called()

    async def test_cancellation_reaps_reader_and_emits_original_failure(self):
        for passive_only in (False, True):
            with self.subTest(passive_only=passive_only):
                reader, emit, writer = asyncio.StreamReader(), Mock(), Mock()
                task = asyncio.create_task(observe_timed_logout(
                    AsyncMock(return_value=False), reader, writer, emit=emit,
                    census=None if passive_only else AsyncMock(), passive_only=passive_only,
                    seconds=1, request_seconds=1))
                await asyncio.sleep(.01)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                self.assertEqual(emit.call_args.args[0]['outcome'], 'cancelled')
                writer.write.assert_not_called()
                # A new independent read must not collide with a leaked read waiter.
                reader.feed_data(b'x')
                self.assertEqual(await reader.read(1), b'x')
