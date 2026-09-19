"""Write an unlabelled SIMH tape of 7-bit ASCII files for TOPS-10 PIP.

Not BACKUP format. Restore in manifest order using COPY filename=MTA0:.
The tape stores PDP-10 core-dump words: four high bytes then four low bits.
"""
import argparse
import json
import struct
from pathlib import Path

WORDS_PER_RECORD = 128
CHARACTERS_PER_WORD = 5
ROOT = Path(__file__).resolve().parents[1]


def pack_text(data):
    if any(char > 127 for char in data):
        raise ValueError("Only 7-bit source text is supported")
    data += b"\0" * (-len(data) % CHARACTERS_PER_WORD)
    result = bytearray()
    for offset in range(0, len(data), CHARACTERS_PER_WORD):
        word = 0
        for char in data[offset:offset + CHARACTERS_PER_WORD]:
            word = (word << 7) | char
        word <<= 1
        result.extend((word >> 4).to_bytes(4, "big"))
        result.append(word & 15)
    return bytes(result)


def write_record(output, data):
    size = struct.pack("<I", len(data))
    output.write(size + data + b"\0" * (len(data) % 2) + size)


def write_tape(output, files):
    block_size = WORDS_PER_RECORD * CHARACTERS_PER_WORD
    for data in files:
        data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        packed = pack_text(data)
        for offset in range(0, len(packed), block_size):
            write_record(output, packed[offset:offset + block_size].ljust(block_size, b"\0"))
        output.write(b"\0" * 4)
    output.write(b"\0" * 4)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    paths = sorted(p for p in args.directory.iterdir() if p.suffix.upper() in
                   {".BCL", ".MAC", ".GET", ".TXT", ".MIC", ".DBA"})
    with args.output.open("xb") as output:
        write_tape(output, (path.read_bytes() for path in paths))
    args.output.with_suffix(".json").write_text(json.dumps([p.name for p in paths], indent=2) + "\n")
    print(f"Wrote {len(paths)} sequential files to {args.output}")


if __name__ == "__main__":
    main()
