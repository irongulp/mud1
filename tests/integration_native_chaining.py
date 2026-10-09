"""Native round-trip chaining between two compatible disposable MUD images."""
import argparse
import json
from pathlib import Path
import time
from tools.audit_archwizards import Guest, MAX_BOOT_ATTEMPTS, logoff
from tools.inspect_game import NativeInspector
from tools.persona_protocol import pack_name
from tools.provision_archwizards import generate_password
from tools.prepare import prepare
from tests.chaining_fixture import install_worlds
from tests.integration_external_login import export_records, compile_source
from tests.integration_external_save import private_export
from tests.integration_storage_bridge import ROOT, private_emulator
from tests.integration_provisioning import require, source_hashes


def run(output, diagnose=False, trace=False):
    output.mkdir(mode=0o700)
    report = {'complete': False}
    original = source_hashes()
    machine = private_emulator(output / 'machine', {})
    try:
        machine.boot()
        with NativeInspector(machine.port) as native:
            native.command('assign dsk: bcl:'); native.command('set tty no altmode')
            export_records(native)
            if trace:
                build = ROOT / 'build' / output.name
                prepare(ROOT / 'source', ROOT / 'upstream/mud1', build)
                path = build / 'MUDLIB.BCL'
                text = path.read_text()
                text = text.replace("if ch ne '*^A' then abort()", "if ch ne '*^A' then chainbad(1,ch)")
                text = text.replace('unless ch=8\\/ch=3 abort()', 'unless ch=8\\/ch=3 chainbad(2,ch)')
                text = text.replace('daytime+WHOLEDAY-str ls TIMECHK abort()', 'daytime+WHOLEDAY-str ls TIMECHK chainbad(3,daytime-str)')
                text = text.replace('and abort() be', 'and chainbad(code,detail) be out("CHAIN CHECK :N :N*C*L",code,detail)<>abort()\nand abort() be')
                path.write_text(text)
                compile_source(native, build, 'mudlib', output)
                native.command('r link', b'\n*')
                native.command('mud0,mud1,mud2,mud3,mud4,mud5,mud6,mud7,mud8,mudlib,mboots/set:.high.:520000,dbadat/g')
                native.command('ssave mud')
                native.command('r link', b'\n*')
                native.command('/set:.high.:430000', b'\n*')
                native.command('dbase,sys:bcplib/search/set:.high.:520000,dbadat/g')
                native.command('save dbase')
            report['worlds'] = install_worlds(machine, native, output)
            if diagnose:
                native.install_source('chnck', (ROOT / 'tools/fixtures/CHAINCK.BCL').read_text())
                native.command('copy valley.exe=chnck.exe')
        machine.command('r opr', 'OPR>'); machine.child.send('set ksys now\r')
        machine.child.expect_exact('KSYS processing completed', timeout=120)
        directory = machine.directory; machine.stop(); machine = None
        for attempt in range(MAX_BOOT_ATTEMPTS):
            machine = private_emulator(directory, {}, reuse=True)
            try:
                machine.boot(); machine.command('daytime'); break
            except Exception:
                machine.stop(); machine = None
                if attempt + 1 == MAX_BOOT_ATTEMPTS: raise
        with NativeInspector(machine.port) as native:
            guest = Guest(machine.port, 'mudguest', [])
            try:
                require(guest.authenticate('Chainer', generate_password(), creating=True), 'Native chain admission failed')
                require(pack_name('chainer') not in private_export(native), 'Admission persisted early')
                guest.send('e')
                if diagnose:
                    text = guest.expect(b'\n.')
                    guest.accepted = False
                    report['diagnostic'] = text
                    print(text, flush=True)
                    return
                result = guest.expect(b'\n*')
                require('Narrow road between lands' in result, 'Native chain did not enter destination room: ' + repr(result))
                first = private_export(native)[pack_name('chainer')]
                require(first.words[0] & ((1 << 18)-1) == 1, 'Native chained admission incremented games')
                require('VALLEY' in native.command('systat'), 'Destination executable not running')
                guest.send('e'); result = guest.expect(b'\n*')
                require('Narrow road between lands' in result, 'Native return chain did not reach source')
                second = private_export(native)[pack_name('chainer')]
                require(first.words[:5] + first.words[6:] == second.words[:5] + second.words[6:], 'Native round trip changed persona except clock')
                guest.close()
                report.update(round_trip=True, first_game_created=True, games=1)
            finally: logoff(guest.connection)
        require(source_hashes() == original, 'Original source changed')
        report.update(complete=True, source_unchanged=True)
        print('Native chaining controls complete:', output, flush=True)
    finally:
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        if machine is not None: machine.stop()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'runtime' / f'native-chain-{time.time_ns()}')
    parser.add_argument('--diagnose', action='store_true')
    parser.add_argument('--trace', action='store_true')
    args = parser.parse_args()
    run(args.output.resolve(), args.diagnose, args.trace)
