import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch

from server.runtime import Runtime
from server.local_batch import BatchBootstrapError


class RuntimeBatchTests(unittest.TestCase):
    def test_external_boot_preserves_ports_and_precedes_bridge_with_current_boot_probe(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Runtime(Path(directory), '/fixture', persona_config='/config', batch_preflight=True)
            runtime.stopping.wait = Mock(return_value=False)
            ports = {6:32006,7:32007}
            events, identities = [], []
            def probe(machine, identity):
                identities.append(identity)
                events.append('batch')
                return dict(boot_id=identity,request=7)
            bridge = MagicMock()
            def start_bridge(machine, actual_ports, store):
                self.assertEqual(actual_ports, ports)
                events.append('bridge')
                return bridge
            with patch('server.runtime.wait_listener'), patch('pexpect.spawn', return_value=Mock()), \
                    patch.object(runtime,'command',return_value=''), \
                    patch('server.persona_bridge.reserve_ports',return_value=ports), \
                    patch('server.persona_bridge.PersonaBridge',side_effect=start_bridge), \
                    patch('tools.persona_migrate.load_config',return_value={}), \
                    patch('tools.persona_writes.isolated_writer',return_value=Mock()), \
                    patch('tools.external_guest.probe_external',side_effect=lambda *a:events.append('admit')), \
                    patch('server.runtime.execute_probe',side_effect=probe):
                runtime.boot()
                runtime.boot()
            self.assertEqual(events,['batch','bridge','admit']*2)
            self.assertNotEqual(*identities)
            records=list(Path(directory).glob('batch-boots/*/proof.json'))
            self.assertEqual(len(records),2)
            self.assertEqual({json.loads(p.read_text())['boot_id'] for p in records},set(identities))

    def test_failed_probe_has_no_admission_or_boot_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime=Runtime(Path(directory),'/fixture',batch_preflight=True)
            runtime.stopping.wait=Mock(return_value=False)
            with patch('server.runtime.wait_listener'), patch('pexpect.spawn',return_value=Mock()) as spawn, \
                    patch.object(runtime,'command',return_value=''), patch.object(runtime,'stop',return_value=True), \
                    patch('server.runtime.signal.signal'), patch('server.runtime.probe_game') as admit, \
                    patch('server.runtime.execute_probe',side_effect=BatchBootstrapError('uncertain')):
                with self.assertRaises(BatchBootstrapError): runtime.run()
            spawn.assert_called_once()
            admit.assert_not_called()

    def test_default_boot_retains_existing_native_admission(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime=Runtime(Path(directory),'/fixture')
            runtime.stopping.wait=Mock(return_value=False)
            with patch('server.runtime.wait_listener'), patch('pexpect.spawn',return_value=Mock()), \
                    patch.object(runtime,'command',return_value=''), patch('server.runtime.execute_probe') as probe, \
                    patch('server.runtime.probe_game') as admit:
                runtime.boot()
            probe.assert_not_called()
            admit.assert_called_once_with(runtime.port)
