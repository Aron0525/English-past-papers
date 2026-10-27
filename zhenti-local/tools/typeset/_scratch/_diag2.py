import sys
from collections import Counter
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[2]


def main(pid: str) -> None:
    pdf = ROOT / "data" / pid / "read.pdf"
    doc = pymupdf.open(pdf)
    page = doc[0]
    d = page.get_text("dict")
    fonts = Counter()
    sample = []
    for b in d["blocks"]:
        for l in b.get("lines", []):
            for s in l["spans"]:
                fonts[(s["font"], round(s["size"], 1))] += 1
                if len(sample) < 6:
                    sample.append((s["font"], s["size"], repr(s["text"][:40])))
    print("fonts:", fonts.most_common())
    for s in sample:
        print(" sample", s)
    # 字体对象信息
    for xref in range(1, doc.xref_length()):
        try:
            t = doc.xref_get_key(xref, "Type")
        except Exception:
            continue
        if t and t[1] == "/Font":
            print("font xref", xref, "BaseFont", doc.xref_get_key(xref, "BaseFont"),
                  "Encoding", doc.xref_get_key(xref, "Encoding"),
                  "ToUnicode", doc.xref_get_key(xref, "ToUnicode"),
                  "Subtype", doc.xref_get_key(xref, "Subtype"))


if __name__ == "__main__":
    main(sys.argv[1])
