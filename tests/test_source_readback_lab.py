import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from tests.integration_source_readback import TraceConnection, evidence_summary


class SourceReadbackLabTests(unittest.TestCase):
    def test_trace_budget_does_not_truncate_the_actual_transport(self):
        connection = Mock()
        connection.read_until.return_value = b'0123456789'
        with tempfile.TemporaryDirectory() as directory:
            trace = TraceConnection(connection, Path(directory), limit=4)
            self.assertEqual(trace.read_until(b'END', 1), b'0123456789')
            trace.close_trace()
            self.assertEqual((Path(directory) / 'received.bin').read_bytes(), b'0123')
            self.assertTrue(trace.truncated)
            self.assertEqual(trace.received_bytes, 10)
        connection.read_until.assert_called_once_with(b'END', 1)

    def test_private_events_do_not_contain_raw_output(self):
        connection = Mock()
        connection.read_until.return_value = b'PRIVATE OUTPUT'
        with tempfile.TemporaryDirectory() as directory:
            trace = TraceConnection(connection, Path(directory))
            trace.read_until(b'END', 1)
            trace.close_trace()
            records = [json.loads(line) for line in (Path(directory) / 'events.jsonl').read_text().splitlines()]
            self.assertNotIn('PRIVATE OUTPUT', json.dumps(records))
            self.assertEqual(records[0]['size'], len(b'PRIVATE OUTPUT'))

    def test_complete_source_without_exact_marker_is_distinguishable(self):
        expected = 'first\nlast\n'
        received = b'type rdtest.bcl\r\nfirst\nlast\n\r\n.'
        report = evidence_summary(received, expected, b'last\r\n')
        self.assertTrue(report['monitor_boundary_seen'])
        self.assertTrue(report['normalized_source_matches'])
        self.assertFalse(report['expected_marker_seen'])

    def test_incomplete_source_cannot_be_claimed_complete(self):
        report = evidence_summary(b'type rdtest.bcl\r\nfirst\r\n.', 'first\nlast\n', b'last\r\n')
        self.assertFalse(report['normalized_source_matches'])
        self.assertFalse(report['expected_marker_seen'])
