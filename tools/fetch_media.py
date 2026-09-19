"""Download historical media, recording hashes; never replace existing media."""
import argparse
import hashlib
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("name", help="Filename under runtime/media")
    args = parser.parse_args()
    if Path(args.name).name != args.name:
        parser.error("name must be a filename")
    directory = ROOT / "runtime/media"
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / args.name
    if destination.exists():
        raise FileExistsError(destination)
    request = urllib.request.Request(args.url, headers={"User-Agent": "mud86-restoration/1"})
    temporary = destination.with_name(destination.name + ".part")
    digest = hashlib.sha256()
    with urllib.request.urlopen(request, timeout=60) as response, temporary.open("xb") as output:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            output.write(chunk)
            digest.update(chunk)
    temporary.rename(destination)
    record = {"url": args.url, "sha256": digest.hexdigest(), "size": destination.stat().st_size}
    destination.with_name(destination.name + ".json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
