"""Production DB/bridge/supervisor bootstrap, no test runtime helpers in services."""
import argparse
import asyncio
import json
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time

from server.database import PrivateDatabase
from tools.external_install import database_config
from tools.persona_snapshot import publish_private
from tests.integration_external_local import browser_check,browser_purge
from tests.integration_provisioning import require

ROOT=Path(__file__).resolve().parents[1]


def run(output,source):
    output.mkdir(mode=0o700); (output/'game').mkdir(mode=0o700); configdir=output/'config'; configdir.mkdir(mode=0o700)
    shutil.copyfile(source/'guest.dsk',output/'game/guest.dsk')
    shutil.copyfile(ROOT/'runtime/media/t10boot.tap',output/'game/t10boot.tap')
    with socket.socket() as probe: probe.bind(('127.0.0.1',0)); telnet_port=probe.getsockname()[1]
    with socket.socket() as probe: probe.bind(('127.0.0.1',0)); http_port=probe.getsockname()[1]
    report={'complete':False}; runtime=gateway=None
    try:
        with PrivateDatabase(output/'external/database'):
            config,admin=database_config(output,configdir)
            with (output/'runtime.log').open('wb') as log:
                runtime=subprocess.Popen([sys.executable,'-m','server.runtime','--state',str(output),'--simh',str(ROOT/'upstream/simh/BIN/pdp10'),
                    '--port',str(telnet_port),'--persona-config',str(configdir/'personas.json')],stdout=log,stderr=log)
                deadline=time.monotonic()+240
                while not (output/'ready').exists():
                    require(runtime.poll() is None,'Production runtime exited; inspect private log')
                    require(time.monotonic()<deadline,'Production runtime readiness timed out'); time.sleep(.1)
                with (output/'gateway.log').open('wb') as gatewaylog:
                    gateway=subprocess.Popen([sys.executable,'-m','server.gateway','--port',str(http_port),'--upstream-port',str(telnet_port),
                                              '--persona-config',str(configdir/'personas.json')],stdout=gatewaylog,stderr=gatewaylog)
                    time.sleep(1)
                    url=f'http://127.0.0.1:{http_port}'
                    asyncio.run(browser_check(url,'Service','labproof',True,output))
                    gateway.send_signal(signal.SIGTERM); require(gateway.wait(timeout=45)==0,'Gateway stop failed'); gateway=None
                runtime.send_signal(signal.SIGTERM); require(runtime.wait(timeout=180)==0,'Runtime stop failed'); runtime=None
                require(json.loads((output/'shutdown.json').read_text())['clean'],'Production guest did not complete KSYS')
        report.update(complete=True,private_database=True,production_runtime=True,browser_save_password=True,clean_shutdown=True)
        print('Production external service acceptance complete:',output,flush=True)
    finally:
        for process in (gateway,runtime):
            if process is not None and process.poll() is None:
                process.send_signal(signal.SIGTERM)
                try: process.wait(timeout=180)
                except subprocess.TimeoutExpired: process.kill(); process.wait()
        (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--prepared-runtime',type=Path,default=ROOT/'runtime/external-always-open-green/compiled')
    args=parser.parse_args(); run(args.output.resolve(),args.prepared_runtime.resolve())
