import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.serve_external import StateLock, prepare_machine, load_local_config, PersonaBridge, local_tty_config


class ExternalLocalTests(unittest.TestCase):
    def test_terminal_stomper_disabled_without_changing_other_settings(self):
        original = 'ALL KSYS TEXT FILL:0 LC WIDTH:255\nTTY0-37: SPEED:9600\nCTY: GALOPR NO REMOTE ACCOUNT "SYSTEM"\nSTOMP ACCOUNT "SYSTEM"\n'
        changed = local_tty_config(original)
        self.assertNotIn('\nSTOMP ',changed)
        self.assertIn('CTY: GALOPR NO REMOTE ACCOUNT "SYSTEM"',changed)
        self.assertIn('TTY0-37: SPEED:9600',changed)
        self.assertEqual(local_tty_config(changed),changed)

    def test_unexpected_terminal_config_not_overwritten(self):
        with self.assertRaises(RuntimeError): local_tty_config('STOMP ACCOUNT "SYSTEM"\n')
    def test_state_lock_rejects_second_launcher(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with StateLock(root):
                with self.assertRaises(RuntimeError), StateLock(root): pass
            with StateLock(root): pass

    def test_disk_is_copied_once_and_running_source_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source'; source.mkdir()
            (source / 'guest.dsk').write_bytes(b'baseline')
            state = root / 'state'; state.mkdir()
            with patch('tools.serve_external.source_stopped', return_value=False):
                with self.assertRaises(RuntimeError): prepare_machine(state, source)
            with patch('tools.serve_external.source_stopped', return_value=True):
                machine = prepare_machine(state, source)
            (machine / 'guest.dsk').write_bytes(b'local progress')
            self.assertEqual(prepare_machine(state, source), machine)
            self.assertEqual((machine / 'guest.dsk').read_bytes(), b'local progress')
            self.assertEqual((source / 'guest.dsk').read_bytes(), b'baseline')

    def test_local_config_is_private_and_confined_to_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'database.json'
            config = {'database': 'mud86_read', 'user': 'persona_writer', 'password': 'secret',
                      'unix_socket': str(root / 'db/db.sock'), 'namespace': 'mud'}
            path.write_text(json.dumps(config)); path.chmod(0o600)
            self.assertEqual(load_local_config(root).user, 'persona_writer')
            config['unix_socket'] = '/some/other/database.sock'
            path.write_text(json.dumps(config))
            with self.assertRaises(RuntimeError): load_local_config(root)

    def test_idle_expiry_retires_owner_without_stopping_listener(self):
        bridge = PersonaBridge(None, {}, object())
        with patch('tools.serve_external.serve_personas', side_effect=[TimeoutError(), None]) as serve:
            bridge.worker(object())
        self.assertEqual(serve.call_count, 2)
