"""Operator aid: run at NFT's '*' prompt after restoring TOPS-10 7.04 tapes."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COPIES = {
    "sys:": ["*.exe", "*.ram", "*.vfu", "ddt.rel", "jobdat.rel", "ovrlay.rel", "teco.err", "system.cmd", "*.sys", "*.ini"],
    "hlp:": ["*.hlp"], "doc:": ["*.doc"], "rel:": ["*.rel"], "unv:": ["*.unv"],
}

for destination, patterns in COPIES.items():
    for pattern in patterns:
        command = f"copy {destination}/protection:055=dskb:[10,7,*,*,*,*,*]{pattern}"
        output = ""
        for attempt in range(60):
            result = subprocess.run([sys.executable, str(ROOT / "tools/console.py"),
                                     "--send", command + r"\r" if attempt == 0 else "", "--wait", "1"],
                                    capture_output=True, text=True, check=True)
            output += result.stdout
            if output.rstrip().endswith("*"):
                break
        if "Total of" not in output or "?" in output or not output.rstrip().endswith("*"):
            raise RuntimeError(output)
        print(command + " — copied", flush=True)
