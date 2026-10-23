"""Exercise the native batch dependency before local browser admission."""
import json
import re
import time

from server.monitor_scope import MonitorBootstrapError
from tools.persona_snapshot import publish_private

BATCH_READINESS_TIMEOUT = 30
BATCH_READINESS_ID = 'native-daytime-v1'
BATCH_POLL_SECONDS = .25
BATCH_STARTUP_STUB_PAGES = 5
BATCH_PROBE_TIME_LIMIT = '0:00:10'


class BatchBootstrapError(MonitorBootstrapError):
    """No admission/retry after an incomplete or uncertain batch probe."""


def completed_probe(log, basename, boot_id, request):
    identity = re.search(r'\bJob\s+'+re.escape(basename)+r'\s+Req\s+#'+str(request)+r'\b', log, re.I)
    result = re.search(r'(?m)^[ \t]*\d+:\d+:\d+\s+'
        r'(?:MONITR[ \t]+\.DAYTIME|BATCH[ \t]+DAYTIME)[ \t]*\r?\n'
        r'[ \t]*\d+:\d+:\d+\s+MONITR[ \t]+'
        r'(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)'
        r'\s+\d+-[A-Za-z]+-\d+\s+\d+:\d+:\d+', log)
    if not identity or not result or boot_id not in log.lower():
        return False
    tail = log[result.end():]
    return bool(re.search(r'BATCH\s+\.KJOB/BATCH', tail) and 'Logged-off' in tail)


def prepare_batch(machine):
    machine._batch_verified = False
    boot_id = machine.scope.evidence.name
    if not machine.monitor_scope_verified or not re.fullmatch(r'[0-9a-f]{32}', boot_id):
        raise BatchBootstrapError('Batch readiness requires the current verified monitor boot')
    basename = boot_id[:6]
    deadline = time.monotonic()+BATCH_READINESS_TIMEOUT

    def remaining():
        budget = deadline-time.monotonic()
        if budget <= 0:
            raise BatchBootstrapError('Native batch probe did not complete before its deadline')
        return budget

    def command(text):
        return machine.command(text, timeout=remaining())

    try:
        preflight = command('directory '+basename+'.*')
        if ('%WLDNSF No such files as '+basename+'.*').lower() not in preflight.lower():
            raise BatchBootstrapError('Native batch probe filenames are occupied or absence is unconfirmed')
        machine.copy_text(basename+'.ctl', ';MUD86 batch probe '+boot_id+'\n.DAYTIME\n', timeout=remaining())
        submission = command('submit '+basename+'.ctl/time:'+BATCH_PROBE_TIME_LIMIT+'/output:nolog')
        queued = re.search(r'\[Batch job '+basename+r' queued, request #(\d+),', submission, re.I)
        if not queued:
            raise BatchBootstrapError('Batch submission was not confirmed; it will not be replayed')
        request = int(queued.group(1))
        statuses = []
        while True:
            status = command('systat')
            statuses.append(status)
            controller = re.search(r'(?m)^\s*\d+\s+.*?\bBATCON\s+(\d+)', status)
            if controller and int(controller.group(1)) > BATCH_STARTUP_STUB_PAGES:
                log = command('type '+basename+'.log')
                if completed_probe(log, basename, boot_id, request):
                    evidence = dict(boot_id=boot_id, request=request, preflight=preflight,
                                    submission=submission, statuses=statuses, log=log)
                    publish_private(machine.scope.evidence/'batch-probe.json',
                        lambda stream: stream.write((json.dumps(evidence, indent=2)+'\n').encode('ascii')))
                    machine.scope.record('batch-ready', batch_ready=True, batch_probe_request=request)
                    machine._batch_verified = True
                    return
            time.sleep(min(BATCH_POLL_SECONDS, remaining()))
    except Exception as error:
        try:
            machine.scope.record('batch-failed', batch_ready=False, batch_error_type=type(error).__name__)
        except OSError:
            # Diagnostic failures must not make uncertain submissions retryable.
            pass
        if isinstance(error, BatchBootstrapError):
            raise
        raise BatchBootstrapError('Native batch readiness failed; inspect per-boot evidence') from None
