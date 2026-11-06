from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch

from server.runtime import Runtime
from server.monitor_scope import MonitorBootstrapError


class RuntimeScopeTests(unittest.TestCase):
    def test_scope_installs_before_admission_preserving_utc_and_external_ports(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime=Runtime(Path(directory),'/fixture',persona_config='/config',monitor_scope=True)
            runtime.stopping.wait=Mock(return_value=False)
            child=Mock()
            scope=Mock(verified=True)
            events=[]
            scope.arm_from_loader.side_effect=lambda:events.append('arm')
            scope.install_before_operator.side_effect=lambda *a:events.append('install')
            bridge=MagicMock()
            ports={6:32106,7:32107}
            def bridge_factory(machine,actual,store):
                self.assertEqual(actual,ports)
                events.append('bridge')
                return bridge
            def command(text,*a,**k):
                events.append(text)
                return ''
            clock=datetime(2026,11,6,21,37,19,tzinfo=timezone.utc)
            with patch('server.runtime.wait_listener'),patch('pexpect.spawn',return_value=child), \
                    patch('server.runtime.MonitorBootstrap',return_value=scope) as factory, \
                    patch('server.runtime.datetime') as date,patch.object(runtime,'command',side_effect=command), \
                    patch('server.persona_bridge.reserve_ports',return_value=ports), \
                    patch('server.persona_bridge.PersonaBridge',side_effect=bridge_factory), \
                    patch('tools.persona_migrate.load_config',return_value={}), \
                    patch('tools.persona_writes.isolated_writer',return_value=Mock()), \
                    patch('tools.external_guest.probe_external',side_effect=lambda *a:events.append('admit')):
                date.now.return_value=clock
                runtime.boot()
                runtime.boot()
                date.now.assert_called_with(timezone.utc)
            self.assertEqual(factory.call_count,2)
            self.assertEqual(events,['arm','install','exit','systat','bridge','admit']*2)
            sent=[c.args[0] for c in child.send.call_args_list]
            self.assertEqual(sent.count('/tm02\r'),2)
            self.assertIn('11-06-2026\r',sent)
            self.assertIn('213719\r',sent)

    def test_unsupported_or_unverified_scope_never_admits_or_boot_retries(self):
        for error in (MonitorBootstrapError('unsupported'),None):
            with self.subTest(error=error),tempfile.TemporaryDirectory() as directory:
                runtime=Runtime(Path(directory),'/fixture',monitor_scope=True)
                runtime.stopping.wait=Mock(return_value=False)
                scope=Mock(verified=False)
                scope.install_before_operator.side_effect=error
                with patch('server.runtime.wait_listener'),patch('pexpect.spawn',return_value=Mock()) as spawn, \
                        patch('server.runtime.MonitorBootstrap',return_value=scope), \
                        patch('server.runtime.probe_game') as admit,patch.object(runtime,'stop',return_value=False), \
                        patch('server.runtime.signal.signal'):
                    with self.assertRaises(MonitorBootstrapError): runtime.run()
                spawn.assert_called_once()
                admit.assert_not_called()

    def test_default_boot_does_not_apply_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime=Runtime(Path(directory),'/fixture')
            runtime.stopping.wait=Mock(return_value=False)
            with patch('server.runtime.wait_listener'),patch('pexpect.spawn',return_value=Mock()), \
                    patch('server.runtime.MonitorBootstrap') as scope,patch.object(runtime,'command',return_value=''), \
                    patch('server.runtime.probe_game') as admit:
                runtime.boot()
            scope.assert_not_called()
            admit.assert_called_once_with(runtime.port)

    def test_bootstrap_arming_error_cannot_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime=Runtime(Path(directory),'/fixture',monitor_scope=True)
            scope=Mock(verified=False)
            scope.arm_from_loader.side_effect=TimeoutError('loader boundary')
            with patch('server.runtime.wait_listener'),patch('pexpect.spawn',return_value=Mock()) as spawn, \
                    patch('server.runtime.MonitorBootstrap',return_value=scope), \
                    patch.object(runtime,'stop',return_value=False),patch('server.runtime.signal.signal'):
                with self.assertRaises(TimeoutError): runtime.run()
            spawn.assert_called_once()

    def test_failed_bootstrap_cleanup_uses_its_owned_simulator_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime=Runtime(Path(directory),'/fixture',monitor_scope=True)
            runtime.child=Mock()
            runtime.scope=Mock(verified=False)
            runtime.scope.console.at_prompt=True
            child=runtime.child
            self.assertFalse(runtime.stop())
            child.sendcontrol.assert_not_called()
            child.send.assert_called_once_with('quit\r')
            child.expect_exact.assert_called_once_with('Goodbye')
