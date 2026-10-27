"""逐页对比原卷与重排版的字数，定位差值到底出在哪几页。"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import check_quality as cq

ROOT = Path("E:/workbuddy/仓库/rea/zhenti-local/data")
pid = sys.argv[1] if len(sys.argv) > 1 else "cet6/2019-06/01"
src = ROOT / pid / "read.pdf"
clean = ROOT / pid / "read.clean.pdf"


def per_page(pdf: Path, drop_dup: bool):
    doc = cq.pymupdf.open(pdf)
    skip = {n[:20] for n in cq.cipher_fonts(pdf)}
    out = []
    for page in doc:
        buf = []
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    if span["font"][:20] in skip:
                        continue
                    buf.append(span["text"])
        text = re.sub(r"\s+", "", "".join(buf))
        text = re.sub(r"https?://[A-Za-z0-9./_\-]+", "", text)
        raw = len(text)
        if drop_dup:
            text = cq.half_dup(text)
        out.append((raw, len(text), text[:60]))
    doc.close()
    return out


a = per_page(src, True)
b = per_page(clean, False)
print(f"{pid}  src {len(a)}p  out {len(b)}p   cipher={cq.cipher_fonts(src)}")
print(f"{'pg':>3} {'src_raw':>8} {'src_dd':>7} {'out':>7}  diff")
for i in range(max(len(a), len(b))):
    sa = a[i] if i < len(a) else (0, 0, "")
    sb = b[i] if i < len(b) else (0, 0, "")
    print(f"{i+1:>3} {sa[0]:8d} {sa[1]:7d} {sb[1]:7d}  {sb[1]-sa[1]:+6d}  {sa[2][:40]}")
