"""用"去重后的独立行字数"衡量原卷真实内容量，判断低字数比是不是重复层造成的。"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import check_quality as cq
from parse_paper import cipher_fonts, normalise

ROOT = Path("E:/workbuddy/仓库/rea/zhenti-local/data")


def unique_lines(pdf: Path) -> tuple[int, int]:
    doc = cq.pymupdf.open(pdf)
    skip = {n[:20] for n in cipher_fonts(pdf)}
    seen: dict[str, int] = {}
    total = 0
    for page in doc:
        for b in page.get_text("dict")["blocks"]:
            for l in b.get("lines", []):
                buf = []
                for s in l["spans"]:
                    if s["font"][:20] in skip:
                        continue
                    buf.append(s["text"])
                text = normalise("".join(buf))
                flat = re.sub(r"\s+", "", text)
                if len(flat) < 12:
                    continue
                if re.search(r"burningvocabulary|zhenti|淘宝", text):
                    continue
                total += len(flat)
                seen.setdefault(flat, len(flat))
    doc.close()
    return sum(seen.values()), total


def main() -> None:
    ids = sys.argv[1:] or [
        "cet6/2017-12/01", "cet6/2020-12/01", "cet6/2019-06/01", "cet6/2019-06/02",
        "cet6/2019-06/03", "cet6/2017-12/02", "cet6/2017-12/03", "cet6/2016-06/02",
        "cet6/2020-12/02",
    ]
    print(f"{'id':18s} {'独立行字':>8} {'总字':>8} {'重复率':>7} {'产物':>7} {'比':>7}")
    for pid in ids:
        pdf = ROOT / pid / "read.pdf"
        clean = ROOT / pid / "read.clean.pdf"
        uniq, total = unique_lines(pdf)
        out, _ = cq.text_of(clean)
        print(f"{pid:18s} {uniq:8d} {total:8d} {1-uniq/max(1,total):6.0%} "
              f"{len(out):7d} {len(out)/max(1,uniq):6.0%}")


if __name__ == "__main__":
    main()
