"""Build a persona-free 24/7 release from the pinned, stopped first-playable image.

Never accepts a live disk or an arbitrary audit image as input. The release
image is never used for credential tests; acceptance tests extract fresh copies.
"""
import argparse
import json
from pathlib import Path

from tools.audit_archwizards import MAX_BOOT_ATTEMPTS, checked_command, inspect, prepare_machine
from tools.benchmark_idle import Emulator
from tools.deploy import ROOT, sha256
from tools.licensing import write_runtime_archive


def build(output, tag):
    provenance = json.loads((ROOT / 'docs/provenance.json').read_text())
    baseline = ROOT / 'runtime/checkpoints/first-playable/tops10-704.dsk'
    if sha256(baseline) != provenance['disk_sha256']:
        raise ValueError('First-playable checkpoint differs from pinned provenance')
    for name, digest in provenance['source_provenance']['original_sha256'].items():
        if sha256(ROOT / 'source' / name) != digest:
            raise ValueError('Original source changed: ' + name)
    output.mkdir(mode=0o700)
    machine = None
    try:
        for attempt in range(MAX_BOOT_ATTEMPTS):
            machine = Emulator(output / f'build-{attempt + 1}', 'noidle', speed_factor=8)
            try:
                machine.boot()
                break
            except Exception:
                machine.stop()
                machine = None
                if attempt + 1 == MAX_BOOT_ATTEMPTS:
                    raise
        prepare_machine(machine, historical=False)
        if inspect(machine):
            raise ValueError('Starter has personas; refusing to publish it')
        listing = checked_command(machine, 'dir')
        (output / 'guest-directory.txt').write_text(listing)
        if 'AUTH0' in listing.upper() or 'MUD.WIZ' in listing.upper():
            raise ValueError('Unexpected authorization fixtures in starter directory')
        checked_command(machine, 'kjob')
        login = checked_command(machine, 'login 1,2', r'\n\.|OPR>')
        if not login.endswith('OPR>'):
            checked_command(machine, 'r opr', r'OPR>')
        machine.child.send('set ksys now\r')
        machine.child.expect_exact('KSYS processing completed', timeout=90)
        disk = machine.directory / 'guest.dsk'
        machine.stop()
        machine = None
        inputs = {'guest.dsk': disk, 't10boot.tap': ROOT / 'runtime/media/t10boot.tap'}
        archive = output / 'mud86-runtime.tar.gz'
        records = write_runtime_archive(archive, inputs)
        manifest = {
            'version': 2, 'release': tag, 'availability': 'always-open',
            'permission_review': 'incomplete; packaging does not authorize redistribution',
            'simh_revision': provenance['simh_revision'],
            'baseline_sha256': provenance['disk_sha256'],
            'persona_records': 0, 'shutdown': 'KSYS processing completed',
            'archive': {'url': f'https://github.com/irongulp/mud1/releases/download/{tag}/{archive.name}',
                        'sha256': sha256(archive), 'size': archive.stat().st_size},
            'files': records,
        }
        (output / 'runtime.json').write_text(json.dumps(manifest, indent=2) + '\n')
        print(json.dumps(manifest, indent=2))
    finally:
        if machine is not None:
            machine.stop()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--tag', default='runtime-v2')
    args = parser.parse_args()
    if not args.tag or any(char not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-' for char in args.tag):
        parser.error('Invalid release tag')
    build(args.output.resolve(), args.tag)
