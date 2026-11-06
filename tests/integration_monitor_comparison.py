"""One bounded native baseline/scope arm, no batch warmup or external build."""
import argparse
from collections import Counter
from contextlib import redirect_stdout
import json
from pathlib import Path
import re
import socket
import time
from unittest.mock import patch

from server.monitor_bootstrap import SimulatorConsole
from server.runtime import Runtime, probe_game, simulator_config
from tools.deploy import install_image, sha256
from tools.persona_snapshot import publish_private

ROOT=Path(__file__).resolve().parents[1]
BOOT_LIMIT=3
ADMISSION_COUNT=4
ADMISSION_GAP_SECONDS=10
HISTORY_SIZE=4096
HISTORY_REPORT_SIZE=256
CAPTURE_TIMEOUT=15


def history_summary(text):
    pcs=re.findall(r'(?m)^([0-7]{6})\s+[0-7]{12}\s+[0-7]{6}\s+[^\r\n]+',text)
    return dict(samples=len(pcs),last_pcs=pcs[-64:],halt_5005_seen='005005' in pcs,
                top_pcs=[dict(pc=pc,count=count) for pc,count in Counter(pcs).most_common(12)])


def capture(runtime,directory):
    """Capture before cleanup; raw history/registers are private and not uploaded."""
    child=runtime.child
    if child is None or not child.isalive(): return dict(process_alive=False)
    saved={name:getattr(child,name) for name in ('logfile','logfile_read','logfile_send')}
    for name in saved: setattr(child,name,None)
    console=SimulatorConsole(child)
    console.deadline=time.monotonic()+CAPTURE_TIMEOUT
    raw={}
    result={}
    try:
        try:
            child.expect_exact('sim>',timeout=.1)
            console.at_prompt=True
            result['already_at_simulator_prompt']=True
        except Exception:
            result['already_at_simulator_prompt']=False
            console.halt()
        raw['registers']={name:console.register(name) for name in ('PC','FLAGS','UBR','PION','PIACT')}
        raw['history']=console.command('show cpu history='+str(HISTORY_REPORT_SIZE))
        result.update(history_summary(raw['history']))
        result['pc']=f"{raw['registers']['PC']:06o}"
        if raw['registers']['PC']==0o5005:
            raw['halt_words']=console.words(0o5004,0o5006)
            # Only expose the saved-PC half after verifying the expected HALT.
            if raw['halt_words'][0o5005]==0o254200005005:
                result['saved_word_5004_pc']=f"{raw['halt_words'][0o5004]&0o777777:06o}"
        publish_private(directory/'failure.private.json',lambda stream:stream.write(json.dumps(raw).encode()))
    except Exception as error:
        result['capture_error_type']=type(error).__name__
    finally:
        if console.at_prompt:
            if result.get('already_at_simulator_prompt'):
                # Never submit guest OS cleanup to a halted SCP or resume the halt.
                child.send('quit\r')
                try:
                    child.expect_exact('Goodbye',timeout=5)
                    result['goodbye']=True
                finally:
                    child.close(force=True)
                    runtime.child=None
                    runtime.booted=False
            else:
                console.resume()
                for name,stream in saved.items(): setattr(child,name,stream)
    return result


def history_config(*args,**kwargs):
    return simulator_config(*args,**kwargs).replace('boot tu0\n',f'set cpu history={HISTORY_SIZE}\nboot tu0\n')


def run(output,archive,executable,candidate):
    output.mkdir(mode=0o700)
    report=dict(candidate=candidate,complete=False,simulator_sha256=sha256(executable),
                batch_warmup=False,clock='host UTC',boots=[])
    manifest=json.loads((ROOT/'deploy/runtime.json').read_text())
    for index in range(BOOT_LIMIT):
        directory=output/f'boot-{index+1}'
        directory.mkdir(mode=0o700)
        install_image(archive,manifest,directory/'game')
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0))
            port=listener.getsockname()[1]
        runtime=Runtime(directory,executable,port=port,monitor_scope=candidate)
        observation=dict(index=index+1,phase='boot',admissions=0,clean=False)
        report['boots'].append(observation)
        with (directory/'console.private.log').open('x') as log,redirect_stdout(log):
            try:
                with patch('server.runtime.simulator_config',history_config):
                    runtime.boot()
                observation['scope_verified']=bool(runtime.scope and runtime.scope.verified)
                observation['phase']='admission'
                for _ in range(ADMISSION_COUNT):
                    probe_game(port)
                    observation['admissions']+=1
                    time.sleep(ADMISSION_GAP_SECONDS)
                observation['phase']='shutdown'
                observation['clean']=runtime.stop()
            except Exception as error:
                observation['error_type']=type(error).__name__
                try: observation['failure_capture']=capture(runtime,directory)
                except Exception as failure: observation['capture_error_type']=type(failure).__name__
            finally:
                if runtime.child is not None:
                    try: observation['cleanup_clean']=runtime.stop()
                    except Exception as error: observation['cleanup_error_type']=type(error).__name__
                report['complete']=len(report['boots'])==BOOT_LIMIT and all(row['clean'] for row in report['boots'])
                (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
        if not observation['clean'] or 'error_type' in observation:
            raise RuntimeError('Native lifecycle arm failed; stopped without another boot')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--simh',type=Path,required=True)
    parser.add_argument('--candidate',action='store_true')
    args=parser.parse_args()
    run(args.output.resolve(),args.archive.resolve(),args.simh.resolve(),args.candidate)
