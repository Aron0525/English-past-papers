import re
import sys
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[2]


def dump(pid: str, n: int = 60) -> None:
    pdf = ROOT / "data" / pid / "read.pdf"
    doc = pymupdf.open(pdf)
    lines = []
    for page in doc:
        lines += page.get_text("text").splitlines()
    print(f"== {pid}  pages={doc.page_count} lines={len(lines)}")
    for i, l in enumerate(lines[:n]):
        print(f"{i:4d} {l!r}")


if __name__ == "__main__":
    dump(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 60)
