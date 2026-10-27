"""看每页开头是什么，判断原卷的页序与各页内容归属。"""
import re
import sys
from pathlib import Path

import pymupdf


def head(pdf: Path, n: int = 90) -> None:
    doc = pymupdf.open(pdf)
    print("==", pdf.parent.name + "/" + pdf.name, doc.page_count, "页")
    for pno, page in enumerate(doc, 1):
        text = re.sub(r"\s+", " ", page.get_text("text")).strip()
        print(f"  p{pno:>2} {text[:n]}")
    doc.close()


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        head(Path(arg))
