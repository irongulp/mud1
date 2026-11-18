"""One original external lifecycle, with first-warning fences at driver boundaries."""
import json
from pathlib import Path
import re
from time import monotonic, sleep
from unittest.mock import patch

from tests import integration_external_deployment as deployment
from tests.integration_logout_workload import (
    CONTAINER, URL, OBSERVATION_SECONDS, POLL_SECONDS, classify, journal, observe,
)

MAX_LOGINS = 4
OUTPUT = Path('runtime/logout-sequence')


class StopExperiment(Exception):
    pass


class Sequence:
    def __init__(self):
        self.cursor = None
        self.rows = []
        self.logins = 0
        self.report = dict(outcome='not-started', max_logins=MAX_LOGINS,
                           phase='install', workload='original-external-sequence')

    def check(self):
        if self.cursor is None:
            return
        self.rows = journal(self.cursor)
        result = classify([row['MESSAGE'] for row in self.rows])
        if result['outcome'] == 'reproduced-awaiting-capture':
            result, self.rows = observe(self.cursor)
        if result['outcome'].startswith('reproduced'):
            self.report.update(result)
            raise StopExperiment

    def invoke(self, original, *args, **kwargs):
        self.check()
        self.report['phase'] = 'host-command:' + str(args[1])
        result = original(*args, **kwargs)
        # An already-running operation finishes under its original deadline.
        # Never interrupt/replay it merely because a warning arrived meanwhile.
        self.check()
        return result

    async def login(self, original, *args, **kwargs):
        if self.cursor is None:
            before = journal()
            if not before:
                raise RuntimeError('Missing gateway journal cursor before admission')
            self.cursor = before[-1]['__CURSOR']
        self.check()
        if self.logins >= MAX_LOGINS:
            raise RuntimeError('Original-sequence login budget exhausted')
        self.logins += 1
        self.report['phase'] = f'login-{self.logins}'
        result = await original(*args, **kwargs)
        self.check()
        return result

    def finish(self):
        # No intermediate healthy waits: settle only after the original sequence.
        deadline = monotonic() + OBSERVATION_SECONDS
        while True:
            self.check()
            messages = '\n'.join(row['MESSAGE'] for row in self.rows)
            started = set(re.findall(r'Terminal session started: connection=([a-zA-Z0-9]+)', messages))
            completed = set(re.findall(r'Terminal logout complete: connection=([a-zA-Z0-9]+)', messages))
            if self.logins == MAX_LOGINS and len(started) == MAX_LOGINS and started <= completed:
                self.report.update(outcome='not-reproduced', connections=sorted(started))
                return
            if monotonic() >= deadline:
                self.report.update(outcome='cleanup-unconfirmed',
                                   connections=sorted(started),
                                   completed_connections=sorted(completed))
                return
            sleep(POLL_SECONDS)


def run():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    sequence = Sequence()
    original_invoke = deployment.invoke
    original_login = deployment.login
    try:
        with patch.object(deployment, 'invoke', lambda *args, **kwargs:
                          sequence.invoke(original_invoke, *args, **kwargs)), \
             patch.object(deployment, 'login', lambda *args, **kwargs:
                          sequence.login(original_login, *args, **kwargs)):
            deployment.run(CONTAINER, URL, fresh=True)
        sequence.finish()
    except StopExperiment:
        pass
    except Exception as error:
        sequence.report.update(outcome='experiment-error', driver_error_type=type(error).__name__)
        # Preserve a concurrent cleanup failure without erasing the driver error.
        try:
            sequence.check()
        except StopExperiment:
            pass
        except Exception as capture_error:
            sequence.report['capture_error_type'] = type(capture_error).__name__
    finally:
        sequence.report['logins_submitted'] = sequence.logins
        (OUTPUT / 'journal.log').write_text(
            '\n'.join(json.dumps(row) for row in sequence.rows) + '\n')
        (OUTPUT / 'report.json').write_text(json.dumps(sequence.report, indent=2) + '\n')
        print(json.dumps(sequence.report, indent=2), flush=True)
    return sequence.report


if __name__ == '__main__':
    result = run()
    if result['outcome'] != 'not-reproduced':
        raise SystemExit('Diagnostic stopped: ' + result['outcome'])
