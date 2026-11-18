"""Disposable file rendezvous; only the runtime main thread touches CTY."""
import asyncio
import json
from pathlib import Path
import time
import uuid
from server.runtime import MONITOR_PROMPT

CENSUS_SECONDS=8
REQUEST_SECONDS=12


def publish(path,record):
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(record)+'\n')
    temporary.replace(path)


def service_request(runtime,root,token):
    request=root/'request.json'
    if not request.exists() or (root/'claimed.json').exists():
        return
    request.rename(root/'claimed.json')
    record=json.loads((root/'claimed.json').read_text())
    if record.get('token')!=token:
        return
    record['completed']=False
    if (not runtime.booted or runtime.control_prompt!=MONITOR_PROMPT
            or (root/'cancelled').exists()
            or runtime.stopping.is_set()
            or record.get('deadline',float('inf'))-time.monotonic()<CENSUS_SECONDS):
        record['outcome']='not-eligible'
        publish(root/'response.json',record)
        return
    try:
        status=runtime.command('systat',timeout=CENSUS_SECONDS)
        (root/'systat.txt').write_text(status)
        record.update(completed=True,outcome='completed')
    except Exception as error:
        record.update(outcome='uncertain',error_type=type(error).__name__)
        runtime.booted=False
        runtime.control_prompt=None
        runtime.stopping.set()
        raise RuntimeError('Fixture census uncertain; guest input fenced') from None
    finally:
        publish(root/'response.json',record)


def install_owner(runtime):
    token=uuid.uuid4().hex
    base=runtime.state/'logout-census'
    root=base/token
    root.mkdir(parents=True,mode=0o700)
    publish(base/'owner.json',dict(token=token))
    original=runtime.child.read_nonblocking
    active=False
    def read(*args,**kwargs):
        nonlocal active
        if not active and (runtime.state/'ready').exists() and not runtime.stopping.is_set():
            active=True
            try:
                service_request(runtime,root,token)
            finally:
                active=False
        return original(*args,**kwargs)
    runtime.child.read_nonblocking=read


async def request_census(reader,connection):
    base=Path('/var/lib/mud86/logout-census')
    owner=json.loads((base/'owner.json').read_text())
    token=owner['token']
    if len(token)!=32 or any(c not in '0123456789abcdef' for c in token):
        raise ValueError('Invalid fixture token')
    root=base/token
    # One request per boot, including concurrent failed sessions.
    try:
        with (root/'reserved').open('x'):
            pass
    except FileExistsError:
        return dict(outcome='already-requested')
    publish(root/'request.json',dict(token=token,connection=connection,
            line=getattr(reader,'fixture_line',None),deadline=time.monotonic()+REQUEST_SECONDS))
    deadline=time.monotonic()+REQUEST_SECONDS
    try:
        while time.monotonic()<deadline:
            if (root/'response.json').exists():
                return json.loads((root/'response.json').read_text())
            await asyncio.sleep(.05)
    except asyncio.CancelledError:
        (root/'cancelled').touch()
        raise
    return dict(outcome='response-timeout',token=token)
