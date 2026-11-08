"""Explicit installer opt-in and sanitized per-boot proof checks for acceptance."""
import json
import os


def setup_options():
    if os.environ.get('MUD86_TEST_BATCH_PREFLIGHT')=='1':
        return ['--monitor-scope','--batch-preflight']
    return ['--monitor-scope'] if os.environ.get('MUD86_TEST_MONITOR_SCOPE')=='1' else []


def verify_scope(container,invoke):
    if not setup_options(): return None
    script='require_batch='+repr('--batch-preflight' in setup_options())+'\n'+'''import json
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
report={'verified_boots':len(boots),'monitor_scope':True}
if require_batch:
    from server.local_batch import completed_probe
    assert json.loads((config/'deployment.json').read_text())['batch_preflight'] is True
    assert 'MUD86_BATCH_PREFLIGHT=1' in (config/'runtime.env').read_text().splitlines()
    for boot in boots:
        evidence=json.loads((boot/'batch-proof.json').read_text())
        assert evidence['boot_id']==boot.name
        assert completed_probe(evidence['log'],boot.name[:6],boot.name,evidence['request'])
    report['batch_verified_boots']=len(boots)
print(json.dumps(report))
'''
    return json.loads(invoke(container,'python3.12','-c',script))
