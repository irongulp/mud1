"""Single native PMSNAP upload/read-back/compile on a new starter-image copy.

Never executes PMSNAP or captures persona records. No retry or external build.
"""
import argparse
from contextlib import redirect_stdout
import json
from pathlib import Path
import socket

from server.runtime import Runtime
from tools.capture_personas import SnapshotInspector
from tools.deploy import install_image

ROOT=Path(__file__).resolve().parents[1]


def run(output,archive,executable):
    output.mkdir(mode=0o700)
    state=output/'machine'
    state.mkdir(mode=0o700)
    install_image(archive,json.loads((ROOT/'deploy/runtime.json').read_text()),state/'game')
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0))
        port=listener.getsockname()[1]
    runtime=Runtime(state,executable,port=port)
    report=dict(complete=False,phase='boot',source='runtime-v1',persona_records_read=False)
    error=None
    with (output/'console.log').open('x') as console,redirect_stdout(console):
        try:
            runtime.boot()
            report['phase']='maintenance-admission'
            with SnapshotInspector(port) as native:
                native.command('assign dsk: bcl:')
                native.command('set tty no altmode')
                report['phase']='transfer-readback-compile'
                native.install_source('pmsnap',(ROOT/'tools/fixtures/PMSNAP.BCL').read_text())
                report['companion_compiled']=True
            report['phase']='shutdown'
        except Exception as failure:
            error=failure
            report['error_type']=type(failure).__name__
            # InspectionError messages exclude raw native buffers.
            from tools.inspect_game import InspectionError
            if isinstance(failure,InspectionError): report['diagnostic']=str(failure)
        finally:
            try:
                report['shutdown_clean']=runtime.stop()
            except Exception as failure:
                report['shutdown_clean']=False
                report['shutdown_error_type']=type(failure).__name__
            report['complete']=error is None and report['shutdown_clean']
            (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    if not report['complete']:
        raise RuntimeError('Focused companion transfer failed; inspect retained report and console') from None


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--simh',type=Path,required=True)
    args=parser.parse_args()
    run(args.output.resolve(),args.archive.resolve(),args.simh.resolve())
