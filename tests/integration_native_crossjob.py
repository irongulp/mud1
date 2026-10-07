"""Characterize native live-profile ATTACH across jobs on a disposable disk."""
import argparse
import json
from pathlib import Path
import time

from tools.audit_archwizards import Guest, MAX_BOOT_ATTEMPTS, logoff
from tools.inspect_game import NativeInspector
from tools.persona_protocol import pack_name
from tools.provision_archwizards import generate_password
from tests.integration_external_login import baseline, export_records
from tests.integration_external_save import private_export
from tests.integration_storage_bridge import ROOT, private_emulator
from tests.integration_provisioning import require, source_hashes


def attach(guest, name, wizard=False):
    guest.send('attach ' + name)
    text = guest.expect(b'\n----*' if wizard else b'\n*')
    require('Attaching to ' + name in text, 'Native live ATTACH failed')
    return text


def controls(machine, native, passwords):
    original = export_records(native)
    results = {}
    for name, initially_saved in (('Crossnew', False), ('Crossold', True)):
        owner = Guest(machine.port, 'mudguest', [])
        visitor = None
        try:
            require(owner.authenticate(name, passwords[name], creating=True), 'Native owner admission failed')
            if initially_saved: owner.save(name)
            before = private_export(native).get(pack_name(name.lower()))
            visitor = Guest(machine.port, 'mudguest', [])
            require(visitor.authenticate('Roy', passwords['Roy']), 'Native visitor login failed')
            text = attach(visitor, name)
            require("they'll get your password" in text, 'Native live-profile password warning absent')
            visitor.save(name)
            after = private_export(native)[pack_name(name.lower())]
            require(after.words[7] == original[pack_name('roy')].words[7], 'Attached SAVE did not use visitor password')
            require(after.words[0] & ((1 << 18)-1) == 1, 'Live ATTACH incremented games')
            attach(visitor, 'Roy', wizard=True)
            visitor.close(); logoff(visitor.connection); visitor = None
            owner.save(name) if not initially_saved else None
            owner.close()
            saved = private_export(native)[pack_name(name.lower())]
            require(saved.words[7] != after.words[7], 'Owner persistence did not restore owner password')
            results[name] = {'initially_saved': before is not None,
                             'visitor_password_saved': True, 'owner_password_restored': True,
                             'games': saved.words[0] & ((1 << 18)-1)}
        finally:
            if visitor is not None: logoff(visitor.connection)
            logoff(owner.connection)
        verifier = Guest(machine.port, 'mudguest', [])
        try:
            require(verifier.authenticate(name, passwords[name]), 'Owner password no longer authenticates')
            verifier.close()
        finally: logoff(verifier.connection)
    return results


def run(output):
    output.mkdir(mode=0o700)
    original = source_hashes()
    report = {'complete': False}
    machine = None
    try:
        for attempt in range(MAX_BOOT_ATTEMPTS):
            machine = private_emulator(output / f'machine-{attempt+1}', {})
            try:
                machine.boot(); machine.command('daytime'); break
            except Exception:
                machine.stop(); machine = None
                if attempt + 1 == MAX_BOOT_ATTEMPTS: raise
        passwords = {name: generate_password() for name in ('Roy', 'Crossnew', 'Crossold')}
        baseline(machine.port, {'Roy': passwords['Roy']})
        with NativeInspector(machine.port) as native:
            native.command('assign dsk: bcl:'); native.command('set tty no altmode')
            report['cases'] = controls(machine, native, passwords)
        require(source_hashes() == original, 'Original source changed')
        report.update(complete=True, source_unchanged=True)
        print('Native cross-job controls complete:', output, flush=True)
    finally:
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        if machine is not None: machine.stop()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'runtime' / f'native-crossjob-{time.time_ns()}')
    run(parser.parse_args().output.resolve())
