"""Prepare a traceable MUD86 build tree without changing the source archive."""
import argparse
import difflib
import hashlib
import json
import re
import subprocess
from pathlib import Path

MUD_REVISION = "8d2ce6ee5ca1ae3d835538de20aeb87acaae3df1"
ROOT = Path(__file__).resolve().parents[1]
SOURCE_SUFFIXES = {".BCL", ".MAC", ".GET", ".TXT", ".SUB", ".BOX", ".MIC", ".DBA"}
SUBFILE = re.compile(rb"(?:^|\n)\\{5}\s*\x0cSUBFILE: ([A-Z0-9]+\.[A-Z]+)[^\n]*\n")


def normalize(data):
    data = data.replace(b"\r\n", b"\n").rstrip(b"\x00")
    if b"\x00" in data:
        raise ValueError("Embedded NUL in source")
    data.decode("ascii")
    return data


def split_subfiles(name, data):
    data = normalize(data)
    markers = list(SUBFILE.finditer(data))
    if not markers:
        return {name: data}
    data = re.sub(rb"\n\\{5}\s*\x0c\s*\Z", b"\n", data)
    result = {name: data[:markers[0].start()].rstrip(b"\n") + b"\n"}
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(data)
        child = marker.group(1).decode("ascii")
        if child in result:
            raise ValueError("Duplicate subfile: " + child)
        result[child] = data[marker.end():end].rstrip(b"\n") + b"\n"
    return result


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_normalized(path):
    if path.suffix.upper() == ".DBA":
        # Appended historical writing contains NUL padding between entries.
        # Preserve it: these are runtime assets, not compiler source files.
        return path.read_bytes().replace(b"\r\n", b"\n")
    try:
        return normalize(path.read_bytes())
    except ValueError as error:
        raise ValueError(f"{path}: {error}") from error


def always_open_library(data):
    """Bypass only the schedule gate; HOURS and DEMO retain their own semantics."""
    pattern = re.compile(rb"(?m)^and timeok\(low\)=demo\\/valof\n\$\([\s\S]*?^\$\)\n(?=and overload\(low\)=)")
    matches = list(pattern.finditer(data))
    if len(matches) != 1 or b"resultis ~overload(numbargs()->low, low1)" not in matches[0].group():
        raise ValueError("Unrecognized timeok implementation; refusing availability patch")
    replacement = (b"// Local 24/7 build: preserve HOURS data and the original load checks.\n"
                   b"and timeok(low)=demo\\/~overload(numbargs()->low, low1)\n")
    match = matches[0]
    return data[:match.start()] + replacement + data[match.end():]


def prepare(local, upstream, output, *, always_open=False):
    if output.exists():
        raise FileExistsError("Output already exists: " + str(output))
    files, origins, originals = {}, {}, {}
    for path in sorted(local.iterdir()):
        if path.suffix.upper() not in SOURCE_SUFFIXES:
            continue
        raw = path.read_bytes()
        originals[path.name] = digest(raw)
        for name, data in split_subfiles(path.name, raw).items():
            # Archive boundaries can contribute blank lines; no code/content
            # normalization is permitted when comparing duplicate sections.
            if name in files and files[name].strip(b"\n") != data.strip(b"\n"):
                raise ValueError("Conflicting embedded source: " + name)
            if name not in files:
                files[name] = data
                origins[name] = "source/" + path.name
    for path in sorted(upstream.iterdir()):
        if path.name == "MUD.MIC" or path.suffix.upper() == ".DBA":
            if path.name not in files:
                files[path.name] = read_normalized(path)
                origins[path.name] = "PDP-10/MUD1@" + MUD_REVISION + "/" + path.name

    if "MUD.TXT" not in files:
        raise ValueError("Missing master database: MUD.TXT")
    includes = []
    for name in re.findall(rb"^@([a-zA-Z0-9]+)", files["MUD.TXT"], re.M):
        include = name.decode("ascii").upper() + ".GET"
        if include not in files:
            raise ValueError("Missing include: " + include)
        if re.search(rb"^@", files[include], re.M):
            raise ValueError("DBASE disallows nested includes: " + include)
        includes.append(include)

    local_changes = []
    if always_open:
        original = files.get("MUDLIB.BCL", b"")
        modified = always_open_library(original)
        files["MUDLIB.BCL"] = modified
        local_changes = list(difflib.unified_diff(
            original.decode("ascii").splitlines(True), modified.decode("ascii").splitlines(True),
            fromfile="historical/MUDLIB.BCL", tofile="always-open/MUDLIB.BCL"))

    report = {"upstream_revision": MUD_REVISION, "original_sha256": originals,
              "availability": "always-open" if always_open else "historical",
              "includes": includes, "files": {}}
    differences = []
    for name, data in sorted(files.items()):
        reference = upstream / name
        comparison = "absent"
        if reference.is_file():
            other = read_normalized(reference)
            comparison = "identical" if data == other else "different"
            if comparison == "different":
                differences.extend(difflib.unified_diff(
                    data.decode("ascii").splitlines(True), other.decode("ascii").splitlines(True),
                    fromfile="prepared/" + name, tofile="upstream/" + name))
        report["files"][name] = {"origin": origins[name], "sha256": digest(data),
                                  "upstream_comparison": comparison}
    output.mkdir(parents=True)
    for name, data in files.items():
        (output / name).write_bytes(data)
    (output / "provenance.json").write_text(json.dumps(report, indent=2) + "\n")
    (output / "upstream.diff").write_text("".join(differences))
    (output / "local.diff").write_text("".join(local_changes))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "source")
    parser.add_argument("--upstream", type=Path, default=ROOT / "upstream/mud1")
    parser.add_argument("--output", type=Path, default=ROOT / "build/mud86")
    parser.add_argument("--always-open", action="store_true",
                        help="Bypass opening-hours enforcement in generated code; preserve HOURS output")
    args = parser.parse_args()
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=args.upstream, text=True).strip()
    if revision != MUD_REVISION:
        parser.error("Upstream checkout must be pinned to " + MUD_REVISION)
    subprocess.run(["git", "diff", "--exit-code", "HEAD", "--"], cwd=args.upstream, check=True)
    report = prepare(args.source, args.upstream, args.output, always_open=args.always_open)
    print(f"Prepared {len(report['files'])} files in {args.output}")
    for name, info in report["files"].items():
        if info["upstream_comparison"] != "identical":
            print(f"  {name}: upstream {info['upstream_comparison']}")


if __name__ == "__main__":
    main()
