import sys
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[2]


def main(pid: str, page_no: int) -> None:
    doc = pymupdf.open(ROOT / "data" / pid / "read.pdf")
    page = doc[page_no]
    d = page.get_text("dict")
    print(f"page {page_no} size={page.rect.width:.0f}x{page.rect.height:.0f}")
    for b in d["blocks"]:
        for l in b.get("lines", []):
            for s in l["spans"]:
                t = s["text"]
                print(f"  y={s['bbox'][1]:6.1f} x={s['bbox'][0]:6.1f} {s['font'][:24]:24s} {s['size']:5.1f} {t[:60]!r}")
    _ = sys


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]))
