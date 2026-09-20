"""Import checksum-pinned licence texts and matching xterm.js source."""
import hashlib
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
URL = 'https://www.gnu.org/licenses/gpl-3.0.txt'
SHA256 = '3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986'
SOURCES = (
    ('COPYING', URL, SHA256),
    ('licenses/SIMH.txt',
     'https://raw.githubusercontent.com/simh/simh/47b7ddabbe5b548cfc32f2fd45f7bed238ff7921/LICENSE.txt',
     '2b7b4b58a41f1bcc049e58a14435d168175b1804cc83e188294b701a785e9834'),
)
XTERM_SOURCE = (
    'web/vendor/xterm-source-5.5.0.tar.gz',
    'https://codeload.github.com/xtermjs/xterm.js/tar.gz/9ba6c00a195c95fcf8292a2b9084d91450e5daae',
    '30068bd04022e70e45090269fa27f6aa344762269c8d2d81f07940b41abee4a2',
)


def main():
    for name, url, digest in (*SOURCES, XTERM_SOURCE):
        destination = ROOT / name
        if destination.exists():
            if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
                raise FileExistsError('Refusing to overwrite different contents: ' + name)
            continue
        local = ROOT / 'upstream/simh/LICENSE.txt'
        if name == 'licenses/SIMH.txt' and local.is_file():
            data = local.read_bytes()
        else:
            with urllib.request.urlopen(url, timeout=30) as response:
                data = response.read()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError('Upstream licence text changed; review the pinned copy: ' + name)
        with destination.open('xb') as output:
            output.write(data)


if __name__ == '__main__':
    main()
