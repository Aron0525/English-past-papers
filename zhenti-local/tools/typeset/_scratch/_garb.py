"""按行打分，找出原卷里"看得见但读不出"的乱码层，并给出所在页面。"""
import re
import sys
from pathlib import Path

import pymupdf

VOWELS = set("aeiouyAEIOUY")


def bad_token(tok: str) -> bool:
    """英文碎片只要没元音、或连续辅音过长，就当乱码。"""
    if len(tok) < 3:
        return False
    if not (set(tok) & VOWELS):
        return True
    run = 0
    worst = 0
    for ch in tok:
        if ch not in VOWELS:
            run += 1
            worst = max(worst, run)
        else:
            run = 0
    return worst >= 4


def line_score(text: str) -> tuple[int, int]:
    """返回 (可疑字母数, 总字母数)。"""
    suspicious = total = 0
    for tok in re.findall(r"[A-Za-z]+", text):
        total += len(tok)
        if bad_token(tok):
            suspicious += len(tok)
    return suspicious, total


def main() -> None:
    pdf = Path(sys.argv[1])
    doc = pymupdf.open(pdf)
    for pno, page in enumerate(doc, 1):
        bad = tot = 0
        samples = []
        for b in page.get_text("dict")["blocks"]:
            for l in b.get("lines", []):
                text = "".join(s["text"] for s in l["spans"])
                s, t = line_score(text)
                bad += s
                tot += t
                if t and s / t > 0.3 and len(samples) < 3:
                    samples.append(text[:50].replace("\n", " "))
        if tot and bad / tot > 0.15:
            print(f"p{pno:>2}  可疑 {bad:4d}/{tot:4d} = {bad/tot:5.1%}  {samples}")
    doc.close()


if __name__ == "__main__":
    main()
