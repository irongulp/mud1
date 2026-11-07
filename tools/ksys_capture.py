"""Opt-in post-failure stream evidence; never retries or confirms shutdown."""
import json
import re
import time
import uuid

from tools.persona_snapshot import publish_private

CAPTURE_TIMEOUT=20
MONITOR_PROMPT=r'\n\.'


def log_name(response):
    if not all(text in response for text in ('Event KSYS queued','KSYS stream started','Batch-Stream 32')):
        return None
    names=re.findall(r'(?mi)^[ \t]*Log file:[ \t]+(DSKB:B[0-7]{5}\.LOG\[3,3\])[ \t]*\r?$',response)
    return names[0] if len(names)==1 else None


def summarize(log,status):
    allowed={'ATTACH','KJOB','LOGIN','LOGOUT','SYSTAT','DAYTIME','RUN','R','SEND','KSYS','DETACH'}
    commands=re.findall(r'(?mi)^\s*\d+:\d+:\d+\s+(?:BATCH|MONITR)\s+\.?(\w+)',log)
    jobs=re.findall(r'(?m)^\s*(\d+)\s+(?:\[OPR\]|\d+\s*,\s*\d+)\s+\S+\s+'
                    r'([A-Z0-9]{1,6})\s+(\d+)(?:\+\w+)?\s+(\w+)',status)
    return dict(commands=[word.upper() if word.upper() in allowed else 'OTHER' for word in commands][-32:],
                error_codes=sorted(set(re.findall(r'[?%]([A-Z]{3,8})\b',log))),
                logout_seen='Logged-off' in log,
                jobs=[dict(job=int(job),program=name,pages=int(pages),state=state) for job,name,pages,state in jobs])


def capture(runtime,response):
    name=log_name(response)
    if name is None: return
    directory=runtime.state/'ksys-failures'/uuid.uuid4().hex
    directory.mkdir(mode=0o700,parents=True)
    child=runtime.child
    saved={key:getattr(child,key) for key in ('logfile','logfile_read','logfile_send')}
    for key in saved: setattr(child,key,None)
    raw=dict(ksys=response)
    summary=dict(log_file=name)
    deadline=time.monotonic()+CAPTURE_TIMEOUT
    def budget():
        remaining=deadline-time.monotonic()
        if remaining<=0: raise TimeoutError('Diagnostic deadline')
        return remaining
    success=False
    try:
        # This is the controller-owned CTY, not an arbitrary player's terminal.
        # Interrupt the completed/failed OPR wait and witness a monitor first.
        runtime.control_prompt=None
        child.send('\x03\x03')
        child.expect_exact('^C',timeout=budget())
        child.expect(MONITOR_PROMPT,timeout=budget())
        runtime.control_prompt=MONITOR_PROMPT
        raw['systat']=runtime.command('systat',timeout=budget())
        raw['log']=runtime.command('type '+name,timeout=budget())
        summary.update(summarize(raw['log'],raw['systat']))
        success=True
    except Exception as error:
        summary['capture_error_type']=type(error).__name__
    finally:
        publish_private(directory/'raw.json',lambda stream:stream.write(json.dumps(raw).encode()))
        publish_private(directory/'summary.json',lambda stream:stream.write(json.dumps(summary).encode()))
        # An incomplete private read can leave sensitive bytes queued; keep
        # transcripts off in that case through simulator teardown.
        if success:
            for key,value in saved.items(): setattr(child,key,value)
