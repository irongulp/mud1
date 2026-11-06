"""One disposable external installation per comparison arm; no test retries."""
import argparse
import asyncio
import json
from pathlib import Path
import re
import time

from tests.integration_external_deployment import invoke, login

IDLE_SECONDS = 660


def run(candidate):
    container = 'mud86-external-fresh'
    output = Path('runtime/deployment-batch-comparison')
    output.mkdir(parents=True, exist_ok=True)
    report = dict(candidate=candidate, complete=False, phase='setup', idle_seconds=IDLE_SECONDS)
    try:
        if candidate:
            dropin = ('[Service]\nExecStart=\n'
                'ExecStart=/opt/mud86/current/.venv/bin/python -u -m server.runtime '
                '--state /var/lib/mud86 --simh ${SIMH_BIN} --batch-preflight\nRestart=no\n')
        else:
            dropin = '[Service]\nRestart=no\n'
        invoke(container,'python3.12','-c',
            'from pathlib import Path; p=Path("/etc/systemd/system/mud86-runtime.service.d/comparison.conf"); '
            'p.parent.mkdir(parents=True,exist_ok=True); p.write_text('+repr(dropin)+')')
        invoke(container,'bash','/checkout/setup.sh','--domain','mud.etimbo.com','--http-only',
            '--image','/artifacts/mud86-runtime.tar.gz','--persona-storage','mariadb',log=output/'install.log')
        report['phase']='create-save-quit'
        asyncio.run(login('http://127.0.0.1:48080','Batchtest','testpass',creating=True))
        report['phase']='idle'
        time.sleep(IDLE_SECONDS)
        journal = invoke(container,'journalctl','-u','mud86-runtime','--no-pager','--all','-o','cat')
        (output/'before-stop.log').write_text(journal)
        # Preserve exact lines rather than infer idle logout from wall time.
        report['idle_messages'] = [line for line in journal.splitlines()
                                   if re.search(r'(?i)idle',line)]
        report['phase']='returning-login'
        asyncio.run(login('http://127.0.0.1:48080','Batchtest','testpass'))
        report['phase']='shutdown'
        invoke(container,'systemctl','stop','mud86-runtime.service')
        marker=json.loads(invoke(container,'python3.12','-c',
            'from pathlib import Path; print(Path("/var/lib/mud86/shutdown.json").read_text())'))
        report['shutdown']=marker
        report['complete']=True
        report['phase']='finished'
        if marker.get('clean') is not True:
            raise AssertionError('Native shutdown failed; no restart permitted')
    except Exception as error:
        report['error_type']=type(error).__name__
        raise
    finally:
        (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate',action='store_true')
    run(parser.parse_args().candidate)
