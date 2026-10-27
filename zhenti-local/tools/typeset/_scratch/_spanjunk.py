"""给 span 打"乱码"标签，统计各卷被标中的 span，供人眼复核误判。"""
import re
import sys
from collections import Counter
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).parent))
from _garb import bad_token

ROOT = Path("E:/workbuddy/仓库/rea/zhenti-local/data")

ALLOWED = re.compile(
    r"[\x20-\x7E\u00A0-\u00FF\u2000-\u206F\u2010-\u2027\u2030-\u205E"
    r"\u3000-\u303F\u4E00-\u9FFF\uFF00-\uFFEF]"
)
CJK = re.compile(r"[\u4e00-\u9fff]")
PUNCT = set(";:#$%&*@\\|~^`<>@=_[]{}+")


def garbage(span_text: str) -> bool:
    t = span_text.strip()
    if len(t) < 6:
        return False
    if CJK.search(t):
        return False
    if any(not ALLOWED.match(ch) for ch in t):
        return True
    letters = sum(ch.isalpha() for ch in t)
    spaces = sum(ch.isspace() for ch in t)
    others = len(t) - letters - spaces
    if letters / len(t) < 0.55 and others / len(t) > 0.3:
        return True
    toks = re.findall(r"[A-Za-z]{3,}", t)
    if tokens_bad(toks) > 0.5:
        return True
    return False


def tokens_bad(toks: list[str]) -> float:
    if not toks:
        return 0.0
    return sum(1 for t in toks if bad_token(t)) / len(toks)


def main() -> None:
    only = sys.argv[1] if len(sys.argv) > 1 else ""
    hits: Counter = Counter()
    samples: dict[str, list[str]] = {}
    for pdf in sorted((ROOT / "cet6").glob("*/*/read.pdf")):
        pid = pdf.parent.relative_to(ROOT).as_posix()
        if only and only not in pid:
            continue
        doc = pymupdf.open(pdf)
        for pno, page in enumerate(doc, 1):
            for b in page.get_text("dict")["blocks"]:
                for l in b.get("lines", []):
                    for s in l["spans"]:
                        if garbage(s["text"]):
                            hits[pid] += 1
                            samples.setdefault(f"{pid} p{pno}", []).append(s["text"][:70])
        doc.close()
    total = sum(hits.values())
    print(f"命中 span {total} 个，涉及 {len(hits)} 套")
    for k, v in hits.most_common():
        print(f"  {k:18s} {v}")
    print("\n抽样：")
    for k, v in list(samples.items())[:40]:
        print(" ", k, "|", " / ".join(v[:3]))


if __name__ == "__main__":
    main()
