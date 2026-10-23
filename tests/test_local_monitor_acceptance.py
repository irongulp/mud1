from pathlib import Path
import tempfile
import unittest

from tests.integration_local_monitor import record_simulator


class SimulatorEvidenceTests(unittest.TestCase):
    def test_restart_reuses_identical_immutable_binary_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            executable = output/'pdp10'
            executable.write_bytes(b'disposable simulator')
            record_simulator(output, executable)
            original = (output/'simulator.json').read_bytes()
            record_simulator(output, executable)
            self.assertEqual((output/'simulator.json').read_bytes(), original)

    def test_changed_binary_cannot_replace_the_original_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            executable = output/'pdp10'
            executable.write_bytes(b'first simulator')
            record_simulator(output, executable)
            original = (output/'simulator.json').read_bytes()
            executable.write_bytes(b'changed simulator')
            with self.assertRaisesRegex(ValueError, 'changed'):
                record_simulator(output, executable)
            self.assertEqual((output/'simulator.json').read_bytes(), original)
