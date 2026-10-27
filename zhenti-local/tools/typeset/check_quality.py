"""重排版质检：逐套比对原卷与重排版的文本量，抓内容丢失或膨胀的。"""

from __future__ import annotations

import json
import difflib
import re
import sys
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).parent))
from parse_paper import cipher_fonts, normalise, page_lines

ROOT = Path(__file__).resolve().parents[2]


def source_lines(pdf: Path) -> list[str]:
    """把原卷拆成有内容的行（去掉页脚、域名、纯数字、符号垃圾），用于逐行核对。"""
    doc = pymupdf.open(pdf)
    skip = {name[:20] for name in cipher_fonts(pdf)}
    lines: list[str] = []
    for page in doc:
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                buf = []
                for span in line["spans"]:
                    if span["font"][:20] in skip:
                        continue
                    buf.append(span["text"])
                text = normalise("".join(buf))
                flat = re.sub(r"\s+", "", text)
                if len(flat) < 25:
                    continue
                if "burningvocabulary" in text:
                    continue
                if len(re.findall(r"[A-Za-z\u4e00-\u9fff]", flat)) / len(flat) < 0.45:
                    continue
                lines.append(flat)
    doc.close()
    # 重复层会让同一行出现多次，只留一份
    seen: dict[str, None] = {}
    for line in lines:
        seen.setdefault(line[:60], None)
    return list(seen)


def coverage(src_lines: list[str], clean: Path) -> tuple[int, int]:
    """按词核对。重排会改变断行位置，逐字比会误判，所以看每一行的词有多少出现在产物里。"""
    doc = pymupdf.open(clean)
    words = set(re.findall(r"[A-Za-z]{4,}", " ".join(p.get_text("text") for p in doc).lower()))
    doc.close()
    hit = 0
    for line in src_lines:
        tokens = re.findall(r"[A-Za-z]{4,}", line.lower())
        if not tokens:
            hit += 1
            continue
        found = sum(1 for t in tokens if t in words)
        if found / len(tokens) >= 0.7:
            hit += 1
    return hit, len(src_lines)


def half_dup(text: str) -> str:
    """重复层的卷子，一页的文字是整页写两遍。前后两半比对，相同就只留一半。

    两份是站点两次 OCR 的产物，偶尔差一两个字母，所以比对用相似度不用相等。
    """
    n = len(text)
    if n < 400:
        return text
    best = None
    for k in range(int(n * 0.42), int(n * 0.60), max(1, n // 120)):
        a, b = text[:k], text[k:k * 2]
        if abs(len(a) - len(b)) > 4:
            continue
        ratio = difflib.SequenceMatcher(None, a, b).ratio()
        if ratio > 0.9 and (best is None or ratio > best[0]):
            best = (ratio, a)
    return best[1] if best else text


def text_of(pdf: Path, drop_dup: bool = False) -> tuple[str, int]:
    """按解析器同一套规则取字数：跳过密文字体、去掉叠层副本、滤掉页脚与水印。

    只有这样才能和产物公平比较——原卷那层坏字体 OCR 会把字数撑高三四成，
    直接用 pymupdf 的纯文本字数会得出"少了 30%"的假结论。
    """
    doc = pymupdf.open(pdf)
    skip = cipher_fonts(pdf)
    pages = doc.page_count
    kept: list[str] = []
    for page in doc:
        buf = []
        for line in page_lines(page, skip):
            text = line["text"]
            if re.search(r"burningvocabulary|zhenti|淘宝|光速考研", text):
                continue
            buf.append(text)
        text = re.sub(r"\s+", "", "".join(buf))
        if drop_dup:
            text = half_dup(text)
        kept.append(text)
    doc.close()
    return "".join(kept), pages


def main() -> None:
    only = sys.argv[1] if len(sys.argv) > 1 else ""
    rows = []
    for pdf in sorted((ROOT / "data" / "cet6").glob("*/*/read.pdf")):
        clean = pdf.parent / "read.clean.pdf"
        if not clean.exists():
            continue
        pid = pdf.parent.relative_to(ROOT / "data").as_posix()
        if only and only not in pid:
            continue
        try:
            src_text, src_pages = text_of(pdf, drop_dup=True)
            out_text, out_pages = text_of(clean)
        except Exception as exc:  # noqa: BLE001
            print(f"ERR  {pid}  {exc}")
            continue
        ratio = len(out_text) / max(1, len(src_text))
        rows.append({"id": pid, "src": len(src_text), "out": len(out_text), "ratio": ratio,
                     "pages": (src_pages, out_pages)})

    rows.sort(key=lambda r: r["ratio"])
    print(f"{'id':18s} {'原字数':>7} {'新字数':>7} {'字数比':>7}  页数")
    for r in rows:
        flag = "  <<" if r["ratio"] < 0.9 else ""
        print(f"{r['id']:18s} {r['src']:7d} {r['out']:7d} {r['ratio']*100:6.1f}%  "
              f"{r['pages'][0]:>2}->{r['pages'][1]:<2}{flag}")

    bad = [r for r in rows if r["ratio"] < 0.9]
    print(f"\n共 {len(rows)} 套，字数比低于 90% 的 {len(bad)} 套")
    for r in bad:
        print("  ", r["id"], f"{r['ratio']*100:.0f}%  ({r['out']}/{r['src']} 字)")


if __name__ == "__main__":
    main()
