"""按字体整层判重：同一页上两种字体位置重叠、字数少的那层是副本。"""
import re
import sys
from collections import defaultdict
from pathlib import Path

import pymupdf

ROOT = Path("E:/workbuddy/仓库/rea/zhenti-local/data")
TOL = 4.0


def groups(page):
    by = defaultdict(list)
    for b in page.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            for s in l["spans"]:
                if not s["text"].strip():
                    continue
                by[s["font"]].append(s)
    return by


def shadow(page):
    by = groups(page)
    if len(by) < 2:
        return []
    chars = {f: sum(len(s["text"].strip()) for s in v) for f, v in by.items()}
    main = max(chars, key=chars.get)
    out = []
    for f, group in by.items():
        if f == main:
            continue
        hit = 0
        for s in group:
            cy = (s["bbox"][1] + s["bbox"][3]) / 2
            for m in by[main]:
                if abs((m["bbox"][1] + m["bbox"][3]) / 2 - cy) > TOL:
                    continue
                ov = min(s["bbox"][2], m["bbox"][2]) - max(s["bbox"][0], m["bbox"][0])
                shortest = min(s["bbox"][2] - s["bbox"][0], m["bbox"][2] - m["bbox"][0])
                if shortest > 0 and ov > 0.5 * shortest:
                    hit += 1
                    break
        if len(group) >= 4 and hit / len(group) > 0.6:
            out.append((f, len(group), round(hit / len(group), 2), chars[f], chars[main]))
    return out


def main() -> None:
    for pdf in sorted((ROOT / "cet6").glob("*/*/read.pdf")):
        pid = pdf.parent.relative_to(ROOT).as_posix()
        doc = pymupdf.open(pdf)
        rows = []
        for pno, page in enumerate(doc, 1):
            for item in shadow(page):
                rows.append((pno,) + item)
        doc.close()
        if rows:
            print(pid, rows[:4], f"...共{len(rows)}")


if __name__ == "__main__":
    main()
