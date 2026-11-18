"""Explicit healthy native name-prompt census, never a failed-logout proof."""
import asyncio
import json
from pathlib import Path
import re
from server import gateway
from tests.logout_census import request_census

BASE=Path('/var/lib/mud86/logout-census')


def verify_job(text,line):
    matches=re.findall(r'^\s*(\d+)\s+2653,2653\s+'+str(line)+r'\s+MUD\s+',text,re.M)
    if len(matches)!=1:
        raise ValueError('Expected exactly one MUDGUEST MUD job on assigned line')
    return int(matches[0])


async def run():
    report=dict(control='healthy-native-name-prompt',complete=False)
    reader=writer=None
    login_started=False
    monitor=False
    try:
        reader,writer=await asyncio.wait_for(gateway.telnetlib3.open_connection(
            host='127.0.0.1',port=2020,term='vt100',encoding='ascii',
            client_factory=gateway.SimhClient,connect_minwait=.1,connect_maxwait=1),
            gateway.CONNECT_TIMEOUT)
        progress={}
        await asyncio.wait_for(gateway.wake_monitor(reader,writer,progress=progress),
                               gateway.CONNECT_TIMEOUT)
        monitor=True
        reader.fixture_line=progress['line']
        report['line']=reader.fixture_line
        login_started=True
        monitor=False
        writer.write('login mudguest\r')
        await asyncio.wait_for(reader.readuntil(b'By what name shall I call you?'),
                               gateway.CONNECT_TIMEOUT)
        report['name_prompt']=True
        result=await request_census(reader,'healthy-native-name-prompt')
        report['census']=result
        if result.get('completed') is not True:
            raise RuntimeError('Healthy census request did not complete')
        report['job']=verify_job((BASE/result['token']/'systat.txt').read_text(),reader.fixture_line)
        report['line_open']=not writer.is_closing()
        if not report['line_open']:
            raise RuntimeError('Healthy terminal closed during census')
        report['complete']=True
    except Exception as error:
        report['error_type']=type(error).__name__
        raise
    finally:
        if writer is not None:
            try:
                if login_started or monitor:
                    report['logout_complete']=await gateway.logout_guest(reader,writer,
                        entered=False,monitor=monitor,connection_id='healthy-native-name-prompt')
            finally:
                writer.close()
        report['complete']=report['complete'] and report.get('logout_complete',False)
        (BASE/'healthy-report.json').write_text(json.dumps(report,indent=2)+'\n')
    if not report['complete']:
        raise RuntimeError('Healthy control cleanup incomplete')


if __name__=='__main__':
    asyncio.run(run())
