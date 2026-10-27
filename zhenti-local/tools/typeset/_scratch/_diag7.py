import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pymupdf
from decipher import apply_map, font_roles, load

ROOT = Path(__file__).resolve().parents[2]


def main(pid: str, page_no: int, gm: str) -> None:
    pdf = ROOT / "data" / pid / "read.pdf"
    m = load(Path(gm))
    cipher, readable = font_roles(pdf)
    doc = pymupdf.open(pdf)
    page = doc[page_no]
    print(f"== {pid} page {page_no}")
    for b in page.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            parts = []
            for s in l["spans"]:
                t = s["text"]
                if s["font"] in m:
                    t = apply_map(t, m[s["font"]])
                parts.append(t)
            line = "".join(parts).strip()
            if line:
                print(f"  {round(l['bbox'][1]):4d} {line[:120]}")


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]), sys.argv[3])
