"""Extract only the two disk packs from the downloaded TOPS-10 distribution."""
import shutil
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    output = ROOT / "runtime/disks"
    output.mkdir(exist_ok=True)
    with tarfile.open(ROOT / "runtime/media/tops10-1.4.tar.bz2", "r:bz2") as archive:
        for member in archive:
            name = Path(member.name).name
            if name in {"dskb.dsk", "dskc.dsk"} and member.isfile():
                with archive.extractfile(member) as source, (output / name).open("xb") as target:
                    shutil.copyfileobj(source, target)
                print(f"Extracted {name}: {member.size} bytes")
    for name in ("dskb.dsk", "dskc.dsk"):
        if not (output / name).is_file():
            raise FileNotFoundError(name)


if __name__ == "__main__":
    main()
