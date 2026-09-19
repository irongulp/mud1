"""Copy sequential source tape files at the TOPS-10 monitor prompt.

Mount source.tap at BOT first; MTA0 must be assigned to this job. Use --skip
only when files have already been read from this particular tape mount.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--skip", type=int, default=0)
args = parser.parse_args()
names = json.loads((ROOT / "runtime/media/source.json").read_text())
for name in names[args.skip:]:
    command = f"copy dsk:[2011,2776]{name}=mta0:"
    result = subprocess.run([sys.executable, str(ROOT / "tools/console.py"), "--send",
                             command + r"\r", "--wait", "1"],
                            capture_output=True, text=True, check=True)
    if "?" in result.stdout or not result.stdout.rstrip().endswith("."):
        raise RuntimeError(result.stdout)
    print(name, flush=True)
