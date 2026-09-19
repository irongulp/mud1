"""Decompress the six TOPS-10 installation tapes without replacing outputs."""
import bz2
import shutil
from pathlib import Path

MEDIA = Path(__file__).resolve().parents[1] / "runtime/media"

for name in ("t10boot", "t10mon", "t10cusp1", "t10cusp2", "t10cust", "t10tool"):
    with bz2.open(MEDIA / (name + ".tap.bz2"), "rb") as source:
        with (MEDIA / (name + ".tap")).open("xb") as output:
            shutil.copyfileobj(source, output)
    print(name)
