import json
from pathlib import Path
import tempfile
import unittest

from tests.deployment_boot_status import summarize


class BootStatusTests(unittest.TestCase):
    def test_public_summary_excludes_private_prompt_and_exception_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'attempt-a.json'
            path.write_text(json.dumps({'version': 1, 'attempt': 1, 'phase': 'OPR>',
                                        'error': 'TIMEOUT', 'booted': False, 'batch_ready': False,
                                        'pending_output': 'PRIVATE CONTROL TEXT',
                                        'exception': 'PRIVATE EXCEPTION TEXT'}))
            report = summarize(Path(directory))
            self.assertEqual(report['attempts'][0]['phase'], 'OPR>')
            self.assertNotIn('PRIVATE', json.dumps(report))

    def test_invalid_diagnostic_does_not_publish_its_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'attempt-b.json').write_text('{"phase": "PRIVATE", "error": "PRIVATE"}')
            report = summarize(Path(directory))
            self.assertEqual(report['invalid'], 1)
            self.assertNotIn('PRIVATE', json.dumps(report))

    def test_missing_directory_is_explicitly_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            report = summarize(Path(directory) / 'missing')
            self.assertEqual(report['attempts'], [])
