"""试点：整行含中文时，把夹在中间读不通的英文乱码段整段剔掉。"""
import re
import sys
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).parent))
from _garb import bad_token

CJK = re.compile(r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]")


def scrub(text: str) -> str:
    if not CJK.search(text):
        return text
    out = []
    buf: list[str] = []

    def push(seg: str) -> None:
        toks = re.findall(r"[A-Za-z]{3,}", seg)
        if toks and sum(bad_token(t) for t in toks) / len(toks) > 0.4:
            return  # 这一段读不通，整段是乱码
        if re.search(r"[\\|~^`<>@=+*#$%&]", seg):
            return
        out.append(seg)

    for ch in text:
        if CJK.match(ch):
            if buf:
                push("".join(buf))
                buf = []
            out.append(ch)
        else:
            buf.append(ch)
    if buf:
        push("".join(buf))
    return "".join(out)


def main() -> None:
    pdf = Path(sys.argv[1])
    pno = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    doc = pymupdf.open(pdf)
    text = doc[pno - 1].get_text("text")
    for line in text.splitlines():
        if CJK.search(line):
            print("OLD:", line[:110])
            print("NEW:", scrub(line)[:110])
    doc.close()


if __name__ == "__main__":
    main()
