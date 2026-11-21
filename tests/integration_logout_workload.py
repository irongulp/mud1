"""Finite logout experiment: one external install, stop at first warning."""
import asyncio
import json
from pathlib import Path
import re
import subprocess
import time
from tests.integration_external_deployment import invoke, login
from tests.deployment_scope import setup_options

CONTAINER='mud86-external-fresh'
URL='http://127.0.0.1:48080'
MAX_CYCLES=3
OBSERVATION_SECONDS=30
POLL_SECONDS=1
JOURNAL_SECONDS=5
OUTPUT=Path('runtime/logout-workload')


def classify(messages):
    warnings=[row for row in messages if 'Terminal logout did not complete;' in row]
    if warnings:
        match=re.search(r'connection=([a-zA-Z0-9]+)',warnings[0])
        connection=match.group(1) if match else None
        for row in messages:
            marker='Fixture post-timeout logout observation: '
            if marker in row:
                observation=json.loads(row.split(marker,1)[1])
                if connection and observation.get('connection')==connection:
                    if (observation.get('timing_mode')=='passive-only'
                            and observation.get('census',{}).get('outcome')=='disabled-passive-only'):
                        outcome='reproduced-capture-failed'
                        if observation.get('outcome')=='prompt' and observation.get('late_complete') is True:
                            outcome='reproduced-passive-completion'
                        elif observation.get('outcome')=='timeout' and observation.get('late_complete') is False:
                            outcome='reproduced-passive-timeout'
                        return dict(outcome=outcome,connection=connection,observation=observation)
                    if (observation.get('late_complete') is True
                            and observation.get('census',{}).get('outcome')=='not-requested-passive-complete'):
                        return dict(outcome='reproduced-passive-completion',
                                    connection=connection,observation=observation)
                    captured=observation.get('census',{}).get('completed') is True
                    return dict(outcome='reproduced-captured' if captured else 'reproduced-capture-failed',
                                connection=connection,observation=observation)
        return dict(outcome='reproduced-awaiting-capture',connection=connection)
    if any('Terminal logout complete:' in row for row in messages):
        return dict(outcome='cycle-complete')
    return dict(outcome='pending')


def journal(cursor=None):
    command=['docker','exec',CONTAINER,'journalctl','-u','mud86-gateway',
             '--no-pager','-o','json']
    command+=['--after-cursor',cursor] if cursor else ['-n','1']
    result=subprocess.run(command,capture_output=True,text=True,check=True,timeout=JOURNAL_SECONDS)
    return [json.loads(row) for row in result.stdout.splitlines() if row.startswith('{')]


def observe(cursor):
    deadline=time.monotonic()+OBSERVATION_SECONDS
    while True:
        rows=journal(cursor)
        result=classify([row['MESSAGE'] for row in rows])
        if result['outcome'] not in ('pending','reproduced-awaiting-capture'):
            return result,rows
        if time.monotonic()>=deadline:
            result['outcome']='reproduced-capture-failed' if result['outcome'].startswith('reproduced') else 'cleanup-unconfirmed'
            return result,rows
        time.sleep(POLL_SECONDS)


def run():
    OUTPUT.mkdir(parents=True,exist_ok=True)
    report=dict(outcome='not-started',max_cycles=MAX_CYCLES,cycles=[],phase='install')
    try:
        invoke(CONTAINER,'bash','/checkout/setup.sh','--domain','mud.etimbo.com','--http-only',
               '--image','/artifacts/mud86-runtime.tar.gz','--persona-storage','mariadb',
               *setup_options(),log=OUTPUT/'install.log')
        for cycle in range(MAX_CYCLES):
            report['phase']='player-cycle'
            before=journal()
            if not before:
                raise RuntimeError('Missing journal cursor')
            cursor=before[-1]['__CURSOR']
            # First admission creates/saves the single ordinary test persona.
            asyncio.run(login(URL,'Bounded','testpass',creating=cycle==0))
            result,rows=observe(cursor)
            (OUTPUT/f'cycle-{cycle+1}-journal.log').write_text(
                '\n'.join(json.dumps(row) for row in rows)+'\n')
            report['cycles'].append(result)
            if result['outcome']!='cycle-complete':
                report['outcome']=result['outcome']
                return
            if cycle+1<MAX_CYCLES:
                report['phase']='backup' if cycle==0 else 'restart'
                invoke(CONTAINER,'mud86ctl',report['phase'],log=OUTPUT/f'{report["phase"]}.log')
        report['outcome']='not-reproduced'
    except Exception as error:
        report.update(outcome='experiment-error',error_type=type(error).__name__)
        raise
    finally:
        (OUTPUT/'report.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':
    run()
    result=json.loads((OUTPUT/'report.json').read_text())
    if result['outcome']!='not-reproduced':
        raise SystemExit('Diagnostic stopped: '+result['outcome'])
