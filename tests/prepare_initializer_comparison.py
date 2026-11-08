"""Change only STOMP on an explicitly stopped disposable installed fixture."""
import argparse
from contextlib import redirect_stdout
import fcntl
import hashlib
import json
from pathlib import Path
import re
import socket

from server.runtime import Runtime
from tools.terminal_config import local_tty_config, protect_bridge_terminals


def configuration(machine):
    return machine.command('type sys:tty.ini').replace('\r','').split('\n',1)[1].rsplit('\n.',1)[0]


def configure_pair_arm(machine,disabled,report):
    machine.boot()
    original=configuration(machine)
    if not re.search(r'(?mi)^\s*STOMP ',original) or 'STOMPR' not in machine.command('systat'):
        raise RuntimeError('Comparison requires an enabled initializer in the original fixture')
    report['before_sha256']=hashlib.sha256(original.encode()).hexdigest()
    if disabled and not protect_bridge_terminals(machine):
        raise RuntimeError('Candidate configuration did not change')
    report['configuration_shutdown_clean']=machine.stop()
    if not report['configuration_shutdown_clean']:
        raise RuntimeError('Unconfirmed configuration shutdown; no reboot')
    # Equal reboot count in both arms, no in-place edits of a running ini.
    machine.boot()
    actual=configuration(machine)
    expected=local_tty_config(original) if disabled else original
    if actual.strip()!=expected.strip(): raise RuntimeError('Unexpected terminal configuration after reboot')
    running='STOMPR' in machine.command('systat')
    if running==disabled: raise RuntimeError('Initializer process state disagrees with selected arm')
    report.update(initializer_running=running,after_sha256=hashlib.sha256(actual.encode()).hexdigest())


def run(state,config,output,disabled):
    output.mkdir(mode=0o700)
    report=dict(disabled=disabled,complete=False)
    machine=None
    with (state/'runtime.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if json.loads((state/'shutdown.json').read_text()).get('clean') is not True:
            raise RuntimeError('Comparison requires a confirmed stopped installed fixture')
        metadata=json.loads((config/'deployment.json').read_text())
        if (metadata.get('persona_storage')!='native' or metadata.get('monitor_scope') is not True
                or metadata.get('batch_preflight') is not True):
            raise RuntimeError('Comparison requires the declared guarded native fixture')
        env=dict(line.split('=',1) for line in (config/'runtime.env').read_text().splitlines() if '=' in line)
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0))
            port=listener.getsockname()[1]
        machine=Runtime(state,env['SIMH_BIN'],port=port,monitor_scope=True,batch_preflight=True)
        with (output/'console.log').open('x') as log,redirect_stdout(log):
            try:
                (state/'shutdown.json').write_text('{"clean":false}\n')
                configure_pair_arm(machine,disabled,report)
                report['complete']=True
            except Exception as error:
                report['error_type']=type(error).__name__
                raise
            finally:
                if machine.child is not None:
                    report['final_shutdown_clean']=machine.stop()
                else:
                    report['final_shutdown_clean']=False
                report['complete']=report['complete'] and report['final_shutdown_clean']
                (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    if not report['complete']: raise RuntimeError('Comparison preparation failed; no service restart allowed')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state',type=Path,required=True)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--disable-initializer',action='store_true')
    args=parser.parse_args()
    run(args.state.resolve(),args.config.resolve(),args.output.resolve(),args.disable_initializer)
