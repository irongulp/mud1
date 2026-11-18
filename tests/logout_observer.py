"""Disposable gateway launcher: passive observation after failed cleanup only."""
import asyncio
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

if __name__=='__main__':
    sys.path.insert(0,str(Path.cwd()))

from server import gateway
from tools.guest_control import completed_logout

OBSERVATION_SECONDS=10


async def observe_logout(original,reader,writer,*,emit,seconds=OBSERVATION_SECONDS,census=None,**kwargs):
    result=await original(reader,writer,**kwargs)
    if result:
        return result
    loop=asyncio.get_running_loop()
    started=loop.time()
    record=dict(connection=kwargs.get('connection_id'),late_complete=False,
                before=gateway.terminal_response_facts(reader),
                line_open_before=not writer.is_closing())
    reply=b''
    try:
        if census is not None:
            record['census']=await census(reader,kwargs.get('connection_id'))
        reply=await asyncio.wait_for(reader.readuntil(b'\n.'),seconds)
        text=reply.decode('ascii',errors='replace') if isinstance(reply,bytes) else reply
        record.update(outcome='prompt',late_complete=completed_logout(text))
    except asyncio.CancelledError:
        record['outcome']='cancelled'
        raise
    except asyncio.TimeoutError:
        record['outcome']='timeout'
    except (OSError,EOFError,asyncio.IncompleteReadError,asyncio.LimitOverrunError) as error:
        reply=getattr(error,'partial',b'')
        record.update(outcome='read-error',error_type=type(error).__name__)
    finally:
        record.update(elapsed_seconds=loop.time()-started,
                      after=gateway.terminal_response_facts(reader,reply),
                      line_open_after=not writer.is_closing())
        emit(record)
    return result  # Never upgrade the original failed cleanup.


if __name__=='__main__':
    from logout_census import request_census
    observer=observe_logout
    if os.environ.get('MUD86_LOGOUT_TIMING')=='1':
        from logout_timing import observe_timed_logout
        observer=observe_timed_logout
    original=gateway.logout_guest
    original_wake=gateway.wake_monitor
    async def wake(reader,writer,*,progress=None):
        progress={} if progress is None else progress
        try:
            return await original_wake(reader,writer,progress=progress)
        finally:
            reader.fixture_line=progress.get('line')
    def emit(record):
        gateway.LOG.warning('Fixture post-timeout logout observation: %s',json.dumps(record,sort_keys=True))
    async def observed(reader,writer,**kwargs):
        return await observer(original,reader,writer,emit=emit,
                    census=request_census if os.environ.get('MUD86_LOGOUT_CENSUS')=='1' else None,**kwargs)
    with patch.object(gateway,'wake_monitor',wake),patch.object(gateway,'logout_guest',observed):
        gateway.main()
