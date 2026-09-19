"""Preserve the first playable disk and provenance with the emulator stopped."""
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(data)
    return digest.hexdigest()


def main():
    if (ROOT / "runtime/operator.sock").exists():
        raise RuntimeError("Stop the emulator before taking a disk checkpoint")
    provenance = json.loads((ROOT / "build/mud86/provenance.json").read_text())
    for name, expected in provenance["original_sha256"].items():
        if sha256(ROOT / "source" / name) != expected:
            raise ValueError("Original source changed: " + name)
    for name, record in provenance["files"].items():
        if sha256(ROOT / "build/mud86" / name) != record["sha256"]:
            raise ValueError("Prepared source changed: " + name)
    output = ROOT / "runtime/checkpoints/first-playable"
    output.mkdir(parents=True, exist_ok=False)
    disk = output / "tops10-704.dsk"
    shutil.copyfile(ROOT / "runtime/disks/tops10-704.dsk", disk)
    metadata = {"disk_sha256": sha256(disk), "source_provenance": provenance,
                "simh_revision": "47b7ddabbe5b548cfc32f2fd45f7bed238ff7921",
                "boot_media": json.loads((ROOT / "runtime/media/t10boot.tap.bz2.json").read_text()),
                "boot_mode": "TOPS-10 7.04 bootstrap tape, BOOT>/tm02"}
    (output / "manifest.json").write_text(json.dumps(metadata, indent=2) + "\n")
    docs = ROOT / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "provenance.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print("Original and prepared source hashes verified.")
    print("Checkpoint: " + str(output))
    print("Disk SHA-256: " + metadata["disk_sha256"])


if __name__ == "__main__":
    main()
