"""Assemble licence evidence and notices; this is not a permission-clearance tool."""
import argparse
import gzip
import hashlib
import io
from pathlib import Path
import tarfile

from tools.deploy import ROOT, sha256
from tools.fetch_licences import SOURCES

NOTICE_PATHS = (
    'NOTICE', 'LICENSE', 'COPYING', 'licenses/MUD1-NOTICE.txt',
    'licenses/DEC-HOBBYIST.txt', 'licenses/BCPL-STATUS.md', 'licenses/SIMH.txt',
    'THIRD_PARTY.md', 'docs/licensing.md',
    'web/vendor/LICENSE', 'web/vendor/xterm-source-NOTICE.txt', 'web/vendor/GlassTTY-LICENSE.txt',
    'web/vendor/Bedstead-LICENSE.txt', 'web/vendor/VT52-LICENSE.txt',
    'web/vendor/BBCBitmap-LICENSE.txt', 'web/vendor/IBMPC-LICENSE.txt',
)


def notice_bundle(root):
    texts = {name: (root / name).read_bytes() for name in NOTICE_PATHS}
    for name, _, digest in SOURCES:
        if hashlib.sha256(texts[name]).hexdigest() != digest:
            raise ValueError('Pinned licence text changed: ' + name)
    sections = ['MUD86 LICENCES AND NOTICES\n'
                'Read LICENSE for scope: the GPL does not relicense the historical runtime.\n'
                'Permission review remains incomplete. See the historical-component sections.\n'
                'Some components described here accompany the repository/application rather\n'
                'than the disk image. This bundle records terms and evidence, not new grants.\n']
    for name, data in texts.items():
        sections.append('\n' + '=' * 72 + '\n' + name + '\n' + '=' * 72 + '\n\n'
                        + data.decode('utf-8'))
    return '\n'.join(sections).encode('utf-8')


def write_runtime_archive(destination, inputs, notice_root=ROOT):
    if set(inputs) != {'guest.dsk', 't10boot.tap'}:
        raise ValueError('Expected only the verified disk and boot tape')
    notices = notice_bundle(notice_root)
    records = {name: {'sha256': sha256(path), 'size': path.stat().st_size}
               for name, path in inputs.items()}
    records['NOTICES.txt'] = {'sha256': hashlib.sha256(notices).hexdigest(), 'size': len(notices)}
    with destination.open('xb') as raw, gzip.GzipFile(fileobj=raw, mode='wb', mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w|') as bundle:
            for name, record in records.items():
                member = tarfile.TarInfo(name)
                member.size = record['size']
                member.mode = 0o600 if name == 'guest.dsk' else 0o644
                if name == 'NOTICES.txt':
                    bundle.addfile(member, io.BytesIO(notices))
                else:
                    with inputs[name].open('rb') as source:
                        bundle.addfile(member, source)
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New notice-only supplement file')
    args = parser.parse_args()
    with args.output.open('xb') as destination:
        destination.write(notice_bundle(ROOT))


if __name__ == '__main__':
    main()
