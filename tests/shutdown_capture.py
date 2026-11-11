"""Disposable CI shutdown observer, also usable as an installed-runtime launcher."""
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch
import uuid

# The CI service keeps the installed app as cwd; do not import checkout server code.
if __name__=='__main__':
    sys.path.insert(0,str(Path.cwd()))

from server.runtime import Runtime, MONITOR_PROMPT, main

STATE_CAPTURE_SECONDS=10


def observed_stop(runtime,output,report,*,stop=None,census=True):
    """Fixture-only evidence around the original single-attempt shutdown."""
    evidence=dict(census_enabled=census)
    report['shutdown_evidence']=evidence
    if census and runtime.booted and runtime.control_prompt==MONITOR_PROMPT:
        try:
            status=runtime.command('systat',timeout=STATE_CAPTURE_SECONDS)
            (output/'pre-shutdown-systat.txt').write_text(status)
            evidence['census_completed']=True
        except Exception as error:
            evidence['census_error_type']=type(error).__name__
            runtime.booted=False
            runtime.control_prompt=None
    original_command=runtime.command

    def command(text,*args,**kwargs):
        try:
            return original_command(text,*args,**kwargs)
        except Exception as error:
            if text=='set ksys now':
                evidence['error_type']=type(error).__name__
                console=runtime.scope.console
                console.deadline=time.monotonic()+STATE_CAPTURE_SECONDS
                try:
                    console.halt()
                    status=console.command('show dz')
                    (output/'shutdown-failure-dz.txt').write_text(status)
                    evidence['device_report_completed']=True
                except Exception as capture_error:
                    evidence['device_error_type']=type(capture_error).__name__
                finally:
                    runtime.booted=False
                    runtime.control_prompt=None
                    console.deadline=None
            raise

    with patch.object(runtime,'command',command):
        return (stop or runtime.stop)()


def capture_runtime_shutdown(runtime,original_stop,*,census=True):
    if runtime.child is None:
        return original_stop(runtime)
    output=runtime.state/'shutdown-capture'/uuid.uuid4().hex
    output.mkdir(parents=True,mode=0o700)
    report=dict(shutdown_clean=False)
    try:
        report['shutdown_clean']=observed_stop(runtime,output,report,
                                              stop=lambda:original_stop(runtime),census=census)
        return report['shutdown_clean']
    except Exception as error:
        report['error_type']=type(error).__name__
        raise
    finally:
        (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':
    original_stop=Runtime.stop
    census=os.environ.get('MUD86_CAPTURE_CENSUS','1')!='0'
    with patch.object(Runtime,'stop',lambda runtime:capture_runtime_shutdown(runtime,original_stop,census=census)):
        main()
