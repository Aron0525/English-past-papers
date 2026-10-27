import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pymupdf
from decipher import font_roles, page_rows

ROOT = Path(__file__).resolve().parents[2]


def words_of(chars: list[dict], gap: float) -> list[list[dict]]:
    out: list[list[dict]] = []
    cur: list[dict] = []
    prev = None
    for c in chars:
        if c["c"] == " ":
            if cur:
                out.append(cur)
                cur = []
            prev = c
            continue
        if prev is not None and cur and c["x"] - prev["x"] >= gap:
            out.append(cur)
            cur = []
        cur.append(c)
        prev = c
    if cur:
        out.append(cur)
    return out


def main(pid: str, page_no: int, ymin: float, ymax: float) -> None:
    pdf = ROOT / "data" / pid / "read.pdf"
    cipher, readable = font_roles(pdf)
    doc = pymupdf.open(pdf)
    page = doc[page_no]
    for tag, want, gap in (("CIPHER", cipher, 4.6), ("READ", readable, 4.6)):
        for row in page_rows(page, want):
            if not (ymin <= row["y"] <= ymax):
                continue
            ws = words_of(row["chars"], gap)
            print(f"{tag} n_word={len(ws)}")
            print("   " + " | ".join(f"{''.join(w[0]['c'] if len(w)==1 else '·' for w in [x])}{len(w)}" for w in ws))


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4]))
