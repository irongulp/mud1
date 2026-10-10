import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import deploy


class MaintenanceTests(unittest.TestCase):
    def test_proxy_notice_is_independent_of_gateway_and_not_cached(self):
        config = deploy.nginx_config('mud.example', tls=True)
        self.assertIn('if (-f /etc/mud86/maintenance)', config)
        self.assertIn('The game is unavailable due to scheduled maintenance. Please try again later.', config)
        self.assertIn('Retry-After 900 always', config)
        self.assertIn('setTimeout', config)
        self.assertIn('900000', config)
        self.assertIn('location = /internal/maintenance', config)
        self.assertIn('deny all', config)

    def test_graceful_blocks_admission_before_stopping_gateway_then_game(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(deploy, 'CONFIG', Path(directory)), patch.object(deploy, 'run') as run:
            def check(*args):
                self.assertTrue((Path(directory) / 'maintenance').exists())
            run.side_effect = check
            deploy.maintenance('on', 'graceful')
            self.assertEqual(run.call_args_list[0].args, ('systemctl', 'stop', 'mud86-gateway.service'))
            self.assertEqual(run.call_args_list[1].args, ('systemctl', 'stop', 'mud86-runtime.service'))

    def test_wait_drains_before_stopping_and_interrupt_keeps_notice(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(deploy, 'CONFIG', Path(directory)), patch.object(deploy, 'run') as run, patch.object(deploy, 'maintenance_sessions', side_effect=[2, 1, 0]), patch.object(deploy.time, 'sleep'):
            deploy.maintenance('on', 'wait')
            self.assertEqual(run.call_count, 2)
            run.reset_mock()
            with patch.object(deploy, 'maintenance_sessions', side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt): deploy.maintenance('on', 'wait')
            run.assert_not_called()
            self.assertTrue((Path(directory) / 'maintenance').exists())

    def test_failed_start_keeps_maintenance_enabled(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(deploy, 'CONFIG', Path(directory)), patch.object(deploy, 'run', side_effect=RuntimeError('not ready')):
            flag = Path(directory) / 'maintenance'
            flag.touch()
            with self.assertRaises(RuntimeError): deploy.maintenance('off')
            self.assertTrue(flag.exists())

    def test_reopen_removes_flag_only_after_readiness(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(deploy, 'CONFIG', Path(directory)), patch.object(deploy, 'run') as run:
            flag = Path(directory) / 'maintenance'
            flag.touch()
            run.side_effect = lambda *args, **kwargs: self.assertTrue(flag.exists())
            deploy.maintenance('off')
            self.assertFalse(flag.exists())
            self.assertEqual(run.call_args_list[0].args, ('systemctl', 'start', 'mud86-runtime.service'))
            self.assertEqual(run.call_args_list[1].args, ('systemctl', 'start', 'mud86-gateway.service'))
            self.assertIn('tools.wait_gateway', run.call_args_list[2].args)

    def test_unavailable_session_count_does_not_stop_players(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(deploy, 'CONFIG', Path(directory)), patch.object(deploy, 'run') as run, patch.object(deploy, 'maintenance_sessions', side_effect=OSError('gateway unavailable')):
            with self.assertRaises(OSError): deploy.maintenance('on', 'wait')
            run.assert_not_called()
            self.assertTrue((Path(directory) / 'maintenance').exists())
