import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pymupdf
from decipher import font_roles

ROOT = Path(__file__).resolve().parents[2]


def main(pid: str, page_no: int, ymin: float, ymax: float) -> None:
    pdf = ROOT / "data" / pid / "read.pdf"
    cipher, readable = font_roles(pdf)
    doc = pymupdf.open(pdf)
    page = doc[page_no]
    for tag, want in (("cipher", cipher), ("read", readable)):
        for b in page.get_text("rawdict")["blocks"]:
            for l in b.get("lines", []):
                if not (ymin <= l["bbox"][1] <= ymax):
                    continue
                for s in l["spans"]:
                    if s["font"] not in want:
                        continue
                    row = []
                    for c in s["chars"]:
                        cx = (c["bbox"][0] + c["bbox"][2]) / 2
                        row.append(f"{c['c']}@{cx:.1f}")
                    print(f"{tag} y={l['bbox'][1]:.1f} {s['font'][:22]:22s} " + " ".join(row))


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4]))
