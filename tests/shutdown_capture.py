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

from server.runtime import Runtime, MONITOR_PROMPT, BOOT_TIMEOUT, main
from tools.persona_snapshot import publish_private

if __package__:
    from .ksys_capture import capture_halted
else:
    from ksys_capture import capture_halted

STATE_CAPTURE_SECONDS=10


def observed_stop(runtime,output,report,*,stop=None,census=True,ksys=False):
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
        deadline = (time.monotonic() + kwargs.get('timeout', BOOT_TIMEOUT)
                    if ksys and text == 'set ksys now' else None)
        try:
            return original_command(text,*args,**kwargs)
        except Exception as error:
            if text=='set ksys now':
                deadline_exhausted=deadline is not None and time.monotonic()>=deadline
                evidence['error_type']=type(error).__name__
                console=runtime.scope.console
                console.deadline=time.monotonic()+STATE_CAPTURE_SECONDS
                try:
                    console.halt()
                    status=console.command('show dz')
                    (output/'shutdown-failure-dz.txt').write_text(status)
                    evidence['device_report_completed']=True
                    if ksys:
                        if not deadline_exhausted:
                            evidence['ksys_capture_skipped']='original-deadline-not-exhausted'
                        else:
                            evidence['ksys_state']={}
                            try:
                                # Raw physical pages must not reach console logs.
                                with runtime.scope.private_console():
                                    capture_halted(console,evidence['ksys_state'],
                                                   scope_verified=runtime.scope.verified)
                            except Exception as mapping_error:
                                evidence['ksys_state']['error_type']=type(mapping_error).__name__
                except Exception as capture_error:
                    evidence['device_error_type']=type(capture_error).__name__
                finally:
                    runtime.booted=False
                    runtime.control_prompt=None
                    console.deadline=None
            raise

    with patch.object(runtime,'command',command):
        return (stop or runtime.stop)()


def capture_runtime_shutdown(runtime,original_stop,*,census=True,ksys=False):
    if runtime.child is None:
        return original_stop(runtime)
    output=runtime.state/'shutdown-capture'/uuid.uuid4().hex
    output.mkdir(parents=True,mode=0o700)
    report=dict(shutdown_clean=False)
    try:
        report['shutdown_clean']=observed_stop(runtime,output,report,
                                              stop=lambda:original_stop(runtime),census=census,ksys=ksys)
        return report['shutdown_clean']
    except Exception as error:
        report['error_type']=type(error).__name__
        raise
    finally:
        publish_private(output/'report.json',lambda stream:stream.write(
            (json.dumps(report,indent=2)+'\n').encode('ascii')))


if __name__=='__main__':
    from logout_census import install_owner
    original_boot=Runtime.boot
    def boot(runtime):
        result=original_boot(runtime)
        if os.environ.get('MUD86_LOGOUT_CENSUS')=='1':
            install_owner(runtime)
        return result
    original_stop=Runtime.stop
    census=os.environ.get('MUD86_CAPTURE_CENSUS','1')!='0'
    ksys=os.environ.get('MUD86_KSYS_MAPPING')=='1'
    with patch.object(Runtime,'boot',boot),patch.object(Runtime,'stop',lambda runtime:capture_runtime_shutdown(runtime,original_stop,census=census,ksys=ksys)):
        main()
