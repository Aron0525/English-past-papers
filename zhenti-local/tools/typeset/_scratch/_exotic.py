"""用"非正常字符集"当指纹找乱码行：JUNK 区间里的字符只在坏文字层出现。"""
import re
import sys
from collections import Counter
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).parent))
ROOT = Path("E:/workbuddy/仓库/rea/zhenti-local/data")

# 正常字符集：ASCII、拉丁扩展、常用标点、罗马数字、CJK、全角
OK = re.compile(
    r"[\x20-\x7E\u00A0-\u00FF\u2000-\u206F\u2010-\u2027\u2030-\u205E"
    r"\u2100-\u214F\u2160-\u217F\u2460-\u24FF"
    r"\u3000-\u303F\u4E00-\u9FFF\uFF00-\uFFEF]"
)


def JUNK(text: str):
    return re.search(r"[^" + OK.pattern[1:-1] + "]", text)


BAD = re.compile(r"[^" + OK.pattern[1:-1] + "]")


def main() -> None:
    hits: Counter = Counter()
    samples: dict[str, list[str]] = {}
    for pdf in sorted((ROOT / "cet6").glob("*/*/read.pdf")):
        pid = pdf.parent.relative_to(ROOT).as_posix()
        doc = pymupdf.open(pdf)
        for pno, page in enumerate(doc, 1):
            for b in page.get_text("dict")["blocks"]:
                for l in b.get("lines", []):
                    text = "".join(s["text"] for s in l["spans"])
                    if JUNK.search(text):
                        hits[pid] += 1
                        samples.setdefault(f"{pid} p{pno}", []).append(text[:60])
        doc.close()
    print(f"命中行 {sum(hits.values())}，涉及 {len(hits)} 套")
    for k, v in hits.most_common():
        print(f"  {k:18s} {v}")
    print("\n抽样：")
    for k, v in list(samples.items())[:30]:
        print(" ", k, "|", " ¶ ".join(x.replace("\n", " ") for x in v[:2]))


if __name__ == "__main__":
    main()
