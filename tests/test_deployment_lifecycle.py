"""Deployment success includes genuine final shutdown, not just earlier checks."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from tests.deployment_lifecycle import Lifecycle


class LifecycleTests(unittest.TestCase):
    def test_unclean_final_shutdown_fails_even_after_successful_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = Lifecycle(Path(directory), native_only=True)
            runner.containers = ['fixture']
            runner.execute = Mock(return_value='{"clean": false}\n')
            with self.assertRaisesRegex(RuntimeError, 'shutdown.*fixture'):
                runner.finish()
            self.assertFalse(runner.report['complete'])

    def test_missing_or_non_boolean_clean_marker_is_not_success(self):
        for marker in ('', '{"clean": "true"}', '{"clean": 1}'):
            with self.subTest(marker=marker), tempfile.TemporaryDirectory() as directory:
                runner = Lifecycle(Path(directory), native_only=True)
                runner.containers = ['fixture']
                runner.execute = Mock(return_value=marker)
                with self.assertRaises((RuntimeError, ValueError)):
                    runner.finish()
                self.assertFalse(runner.report['complete'])

    def test_each_container_stops_gateway_before_runtime_and_checks_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'results'
            runner = Lifecycle(output)
            runner.containers = ['native', 'external']
            runner.execute = Mock(return_value='{"clean": true}\n')
            runner.finish()
            calls = [call.args[0] for call in runner.execute.call_args_list]
            for container in runner.containers:
                commands = [command for command in calls if container in command]
                self.assertEqual(commands[0][-3:], ['systemctl', 'stop', 'mud86-gateway.service'])
                self.assertEqual(commands[1][-3:], ['systemctl', 'stop', 'mud86-runtime.service'])
                self.assertIn('shutdown.json', ' '.join(commands[2]))
            self.assertTrue(runner.report['complete'])

    def test_failed_stage_still_collects_evidence_and_cannot_publish_success(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'results'
            runner = Lifecycle(output)
            runner.prepare = Mock()
            runner.stages = Mock(side_effect=RuntimeError('stage failed'))
            runner.diagnostics = Mock()
            runner.finish = Mock()
            with self.assertRaisesRegex(RuntimeError, 'stage failed'):
                runner.run()
            runner.diagnostics.assert_called_once()
            runner.finish.assert_called_once()
            self.assertFalse(json.loads((output / 'report.json').read_text())['complete'])
