"""Publish validated boot metadata only; private console excerpts stay private."""
from itertools import islice
import json
from pathlib import Path
import re

from server.runtime import BOOT_ATTEMPTS, BOOT_PROMPTS

MAX_RECORDS = 64
MAX_RECORD_BYTES = 48 * 1024
PHASES = BOOT_PROMPTS | {'listener', 'spawn', 'private-readiness', 'ready', None}


def summarize(directory):
    paths = list(islice(directory.glob('attempt-*.json'), MAX_RECORDS + 1))
    report = {'version': 1, 'attempts': [], 'invalid': 0, 'truncated': len(paths) > MAX_RECORDS}
    for path in paths[:MAX_RECORDS]:
        try:
            with path.open('rb') as stream:
                raw = stream.read(MAX_RECORD_BYTES + 1)
            if len(raw) > MAX_RECORD_BYTES:
                raise ValueError('oversized record')
            record = json.loads(raw)
            if (record.get('version') != 1 or type(record.get('attempt')) is not int
                    or not 1 <= record['attempt'] <= BOOT_ATTEMPTS or 'phase' not in record
                    or record['phase'] not in PHASES
                    or not isinstance(record.get('error'), str)
                    or not re.fullmatch(r'[A-Za-z_]{1,64}', record['error'])
                    or any(type(record.get(field)) is not bool for field in ('booted', 'batch_ready'))):
                raise ValueError('invalid record')
            report['attempts'].append({key: record[key] for key in
                                       ('attempt', 'phase', 'error', 'booted', 'batch_ready')})
        except (OSError, ValueError, TypeError, AttributeError):
            report['invalid'] += 1
    return report


if __name__ == '__main__':
    print(json.dumps(summarize(Path('/var/lib/mud86/boot-diagnostics')), indent=2))
