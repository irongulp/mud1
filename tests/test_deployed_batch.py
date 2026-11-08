from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from server.runtime import Runtime
from server.local_batch import BatchBootstrapError
from server.monitor_scope import MonitorBootstrapError
from tools import deploy
from server.runtime import OPERATOR_PROMPT


class DeployedBatchTests(unittest.TestCase):
    def test_guarded_shutdown_checks_semantic_queue_readiness_before_one_ksys(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime=Runtime(Path(directory),'/unused',monitor_scope=True,batch_preflight=True)
            runtime.booted=True
            runtime.control_prompt=OPERATOR_PROMPT
            runtime.child=Mock()
            with patch.object(runtime,'command',return_value='-- System Queues Listing --') as command:
                self.assertTrue(runtime.stop())
            self.assertEqual([c.args[0] for c in command.call_args_list],['show queues','set ksys now'])
            self.assertIn('The queues are empty',command.call_args_list[0].args[1])
            self.assertIn('System Queues Listing',command.call_args_list[0].args[1])

    def test_missing_queue_response_never_sends_ksys(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime=Runtime(Path(directory),'/unused',monitor_scope=True,batch_preflight=True)
            runtime.booted=True
            runtime.control_prompt=OPERATOR_PROMPT
            runtime.child=Mock()
            with patch.object(runtime,'command',side_effect=TimeoutError('no listing')) as command:
                self.assertFalse(runtime.stop())
            self.assertEqual([c.args[0] for c in command.call_args_list],['show queues'])

    def test_batch_requires_selected_scope_and_persists_on_rerun(self):
        self.assertFalse(deploy.selected_batch_preflight(None,{},False))
        self.assertTrue(deploy.selected_batch_preflight(True,{},True))
        self.assertTrue(deploy.selected_batch_preflight(None,{'batch_preflight':True},True))
        with self.assertRaises(ValueError): deploy.selected_batch_preflight(True,{},False)
        with self.assertRaises(ValueError): deploy.selected_batch_preflight(None,{'batch_preflight':'yes'},True)
        with self.assertRaises(ValueError): Runtime(Path('/unused'),'/unused',batch_preflight=True)

    def test_native_batch_execution_precedes_game_and_records_current_boot(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime=Runtime(Path(directory),'/unused',monitor_scope=True,batch_preflight=True)
            runtime.stopping.wait=Mock(return_value=False)
            scope=Mock(verified=True)
            scope.evidence=Path(directory)/('a'*32)
            scope.evidence.mkdir()
            order=[]
            def batch(machine,identity):
                order.append('batch')
                self.assertIs(machine,runtime)
                self.assertEqual(identity,scope.evidence.name)
                return dict(boot_id=identity,request=4)
            with patch('server.runtime.wait_listener'),patch('pexpect.spawn',return_value=Mock()), \
                    patch('server.runtime.MonitorBootstrap',return_value=scope), \
                    patch.object(runtime,'command',return_value=''), \
                    patch('server.runtime.execute_probe',side_effect=batch), \
                    patch('server.runtime.probe_game',side_effect=lambda *a:order.append('admit')):
                runtime.boot()
            self.assertEqual(order,['batch','admit'])
            self.assertTrue((scope.evidence/'batch-proof.json').is_file())

    def test_failed_probe_cannot_admit_or_boot_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime=Runtime(Path(directory),'/unused',monitor_scope=True,batch_preflight=True)
            runtime.stopping.wait=Mock(return_value=False)
            scope=Mock(verified=True,evidence=Path(directory)/('b'*32))
            with patch('server.runtime.wait_listener'),patch('pexpect.spawn',return_value=Mock()) as spawn, \
                    patch('server.runtime.MonitorBootstrap',return_value=scope), \
                    patch.object(runtime,'command',return_value=''),patch.object(runtime,'stop',return_value=True), \
                    patch('server.runtime.signal.signal'),patch('server.runtime.probe_game') as admit, \
                    patch('server.runtime.execute_probe',side_effect=BatchBootstrapError('uncertain')):
                with self.assertRaises(MonitorBootstrapError): runtime.run()
            spawn.assert_called_once()
            admit.assert_not_called()
