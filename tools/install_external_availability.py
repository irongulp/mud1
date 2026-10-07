"""Install the verified hours-only patch on a stopped private external lab disk."""
import argparse
import json
from pathlib import Path
import shutil
import time

from tools.serve_external import StateLock, reserve_ports, DEFAULT_STATE
from tools.persona_snapshot import publish_private
from tools.inspect_game import NativeInspector
from tests.integration_external_availability import build,boot,shutdown


def run(state):
    state=state.resolve()
    with StateLock(state):
        directory=state/'machine'
        disk=directory/'guest.dsk'
        if not disk.is_file(): raise RuntimeError('No local copied guest disk')
        from tools.serve_external import source_stopped
        if not source_stopped(disk): raise RuntimeError('Local guest disk must be stopped')
        backup=state/'before-always-open.dsk'
        if backup.exists(): raise RuntimeError('Availability backup exists; inspect prior installation before retrying')
        def copy(stream):
            with disk.open('rb') as original: shutil.copyfileobj(original,stream)
        publish_private(backup,copy)
        output=state/('availability-'+str(time.time_ns())); output.mkdir(mode=0o700)
        machine=None
        try:
            machine=boot(directory,reserve_ports())
            with NativeInspector(machine.port) as native: build(native,output)
            shutdown(machine)
            publish_private(state/'always-open.json',lambda stream: stream.write(json.dumps({
                'availability':'always-open','installed_executable':'MUD.EXE[2011,2776]',
                'original_executable':'XHRS.EXE[2011,2776]','build':str(output)}).encode()))
        finally:
            if machine is not None: machine.stop()
    print('Local external lab opening-hours patch installed; database unchanged',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir',type=Path,default=DEFAULT_STATE)
    run(parser.parse_args().state_dir)
