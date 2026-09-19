"""Vendor the pinned xterm.js browser terminal and its license."""
import hashlib
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "5.5.0"
BASE = f"https://cdn.jsdelivr.net/npm/@xterm/xterm@{VERSION}/"
OUTPUT = ROOT / "web/vendor"

OUTPUT.mkdir(parents=True, exist_ok=True)
manifest = {}
for source, name in (("lib/xterm.js", "xterm.js"), ("css/xterm.css", "xterm.css"), ("LICENSE", "LICENSE")):
    url = BASE + source
    with urllib.request.urlopen(url, timeout=30) as response:
        data = response.read()
    path = OUTPUT / name
    if path.exists() and path.read_bytes() != data:
        raise ValueError(f"Vendor asset differs: {name}")
    path.write_bytes(data)
    manifest[name] = {"url": url, "sha256": hashlib.sha256(data).hexdigest()}
(OUTPUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
print("Vendored xterm.js " + VERSION)
