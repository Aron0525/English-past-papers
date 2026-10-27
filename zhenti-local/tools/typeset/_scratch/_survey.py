"""全卷体检：Part I 是否在卷首、有没有乱码页、字数比。"""
import re
import sys
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).parent))
from _garb import line_score

ROOT = Path("E:/workbuddy/仓库/rea/zhenti-local/data")

BAD_TAIL = 0


def survey(pdf: Path) -> dict:
    doc = pymupdf.open(pdf)
    first = re.sub(r"\s+", " ", doc[0].get_text("text"))[:120]
    # Part I 出现在哪一页
    part1_page = None
    garbled = []
    for pno, page in enumerate(doc, 1):
        text = page.get_text("text")
        if part1_page is None and re.search(r"Part\s*(?:I{1,3}\b|Ⅰ)", text, re.I) and not re.search(
            r"Part\s*(?:II|III|IV)\b", text[:200]
        ):
            part1_page = pno
        bad = tot = 0
        for b in page.get_text("dict")["blocks"]:
            for l in b.get("lines", []):
                t = "".join(s["text"] for s in l["spans"])
                s, n = line_score(t)
                bad += s
                tot += n
        if tot and bad / tot > 0.03:
            garbled.append((pno, round(bad / tot, 3)))
    pages = doc.page_count
    doc.close()
    return {
        "part1_page": part1_page,
        "pages": pages,
        "garbled": garbled,
        "first": first,
        "tail": part1_page == pages,
    }


def main() -> None:
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    late, dirty = [], []
    total = 0
    for pdf in sorted((ROOT / "cet6").glob("*/*/read.pdf")):
        pid = pdf.parent.relative_to(ROOT).as_posix()
        if arg and arg not in pid:
            continue
        total += 1
        r = survey(pdf)
        if r["tail"]:
            late.append(pid)
        if r["garbled"]:
            dirty.append((pid, r["garbled"]))
    print(f"共 {total} 套")
    print(f"\nPart I 在末页（页序倒置）{len(late)} 套:")
    for p in late:
        print("  ", p)
    print(f"\n有乱码页 {len(dirty)} 套:")
    for pid, g in dirty:
        print("  ", pid, g)


if __name__ == "__main__":
    main()
