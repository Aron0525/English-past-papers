"""检验几何包含规则：同一行上被别的 span 完全罩住的，就是多余的副本层。"""
import re
import sys
from collections import Counter
from pathlib import Path

import pymupdf

ROOT = Path("E:/workbuddy/仓库/rea/zhenti-local/data")
TOL_Y = 4.0
TOL_X = 1.5


def scan(pdf: Path):
    doc = pymupdf.open(pdf)
    drops = []
    for pno, page in enumerate(doc, 1):
        spans = []
        for b in page.get_text("dict")["blocks"]:
            for l in b.get("lines", []):
                for s in l["spans"]:
                    if not s["text"].strip():
                        continue
                    spans.append(s)
        for i, a in enumerate(spans):
            ax0, ay0, ax1, ay1 = a["bbox"]
            for j, b in enumerate(spans):
                if i == j:
                    continue
                bx0, by0, bx1, by1 = b["bbox"]
                if abs(ay0 - by0) > TOL_Y:
                    continue
                if a["font"] == b["font"]:
                    continue
                if ax0 >= bx0 - TOL_X and ax1 <= bx1 + TOL_X and len(b["text"]) >= len(a["text"]):
                    drops.append((pno, a["font"][:18], a["text"][:40], b["font"][:18], b["text"][:40]))
                    break
    doc.close()
    return drops


def main() -> None:
    only = sys.argv[1] if len(sys.argv) > 1 else ""
    total = Counter()
    samples = {}
    for pdf in sorted((ROOT / "cet6").glob("*/*/read.pdf")):
        pid = pdf.parent.relative_to(ROOT).as_posix()
        if only and only not in pid:
            continue
        drops = scan(pdf)
        if drops:
            total[pid] = len(drops)
            samples[pid] = drops[:2]
    print("被丢弃的 span 数：")
    for k, v in total.most_common():
        print(f"  {k:18s} {v}")
    print()
    for pid, d in list(samples.items()):
        for x in d:
            print(f"  {pid} p{x[0]} {x[1]} {x[2]!r} <= {x[3]} {x[4]!r}")


if __name__ == "__main__":
    main()
