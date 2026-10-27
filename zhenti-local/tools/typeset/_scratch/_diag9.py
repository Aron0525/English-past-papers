import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pymupdf
from decipher import font_roles, page_rows

ROOT = Path(__file__).resolve().parents[2]


def main(pid: str, page_no: int, ymin: float, ymax: float) -> None:
    pdf = ROOT / "data" / pid / "read.pdf"
    cipher, readable = font_roles(pdf)
    doc = pymupdf.open(pdf)
    page = doc[page_no]
    for tag, want in (("CIPHER", cipher), ("READ", readable)):
        for row in page_rows(page, want):
            if not (ymin <= row["y"] <= ymax):
                continue
            print(f"{tag} y={row['y']:.1f} n={len(row['chars'])}")
            for i, c in enumerate(row["chars"]):
                print(f"   {i:3d} code={ord(c['c']):4d} x={c['x']:6.1f} size={c['size']:.1f} {c['font'][:20]}")


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4]))
