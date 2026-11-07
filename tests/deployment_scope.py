"""Explicit installer opt-in and sanitized per-boot proof checks for acceptance."""
import json
import os


def setup_options():
    return ['--monitor-scope'] if os.environ.get('MUD86_TEST_MONITOR_SCOPE')=='1' else []


def configure_capture(container,invoke):
    if not setup_options(): return
    script='''from pathlib import Path
p=Path('/etc/systemd/system/mud86-runtime.service.d/ksys-evidence.conf')
p.parent.mkdir(parents=True,exist_ok=True)
p.write_text('[Service]\\nEnvironment=MUD86_KSYS_CAPTURE=1\\n')
'''
    invoke(container,'python3.12','-c',script)


def verify_scope(container,invoke):
    if not setup_options(): return None
    script='''import json
from pathlib import Path
config=Path('/etc/mud86')
assert json.loads((config/'deployment.json').read_text())['monitor_scope'] is True
assert 'MUD86_MONITOR_SCOPE=1' in (config/'runtime.env').read_text().splitlines()
boots=list(Path('/var/lib/mud86/monitor-boots').iterdir())
assert boots
for boot in boots:
    proofs=list(boot.glob('[0-9][0-9]-verified.json'))
    assert len(proofs)==1, 'Missing per-boot monitor verification'
    assert json.loads(proofs[0].read_text())['installed'] is True
    assert not list(boot.glob('*-failed.json')), 'Failed monitor bootstrap retained'
print(json.dumps({'verified_boots':len(boots),'monitor_scope':True}))
'''
    return json.loads(invoke(container,'python3.12','-c',script))
