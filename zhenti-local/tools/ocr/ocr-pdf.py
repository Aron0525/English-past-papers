"""
给扫描版真题 PDF 补一层隐形文字。

不是真的"重新排版"，而是：渲染每页 → RapidOCR 识别 → 把识别到的每一行
用 render_mode=3（不可见）原位置写回去。这样 pdf.js 的文本层就能选中、
能框词，查词功能对扫描卷也能用，页面上看不出任何变化。

用法：
    python tools/ocr/ocr-pdf.py --list            # 只看哪些套是扫描件
    python tools/ocr/ocr-pdf.py --only cet6/2013-06/01
    python tools/ocr/ocr-pdf.py --all             # 全部补一遍

原始 PDF 会先备份到 .cache/ocr/backup/，识别文本另存 .cache/ocr/text/<id>.txt。
"""

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
CACHE = ROOT / ".cache" / "ocr"
BACKUP = CACHE / "backup"
TEXTDIR = CACHE / "text"
DPI = 200
SCAN_THRESHOLD = 200          # 前 3 页可用字符数低于这个值就当扫描件
PAGE_MIN_CHARS = 120          # 单页低于这个字数就当成"这页没字"，单独交给 OCR


def iter_papers():
    for pdf in sorted((DATA / "cet6").glob("*/*/read.pdf")):
        yield pdf.parent.relative_to(DATA).as_posix(), pdf


def is_scanned(pdf: Path) -> bool:
    """整本都是图：前 3 页加起来都没字。"""
    doc = pymupdf.open(pdf)
    try:
        chars = 0
        for page in list(doc)[:3]:
            chars += len(page.get_text("text").strip())
            if chars >= SCAN_THRESHOLD:
                return False
        return True
    finally:
        doc.close()


def blank_pages(doc) -> list[int]:
    """有字的 PDF 里也可能夹几页纯图（2018-06/03 就是），这些页要单独补。"""
    return [i for i, page in enumerate(doc)
            if len(page.get_text("text").strip()) < PAGE_MIN_CHARS]


def latin_only(text: str) -> str:
    """内置字体只有拉丁字形，中文写不进去，直接丢掉，别让它整行失败。"""
    return "".join(ch for ch in text if 32 <= ord(ch) < 127).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--only", default=None)
    ap.add_argument("--dpi", type=int, default=DPI)
    args = ap.parse_args()

    papers = [(pid, pdf) for pid, pdf in iter_papers() if pdf.exists()]
    plan = []
    for pid, pdf in papers:
        doc = pymupdf.open(pdf)
        todo = list(range(doc.page_count)) if is_scanned(pdf) else blank_pages(doc)
        doc.close()
        if todo:
            plan.append((pid, pdf, todo))

    if args.list:
        total = sum(len(t) for _, _, t in plan)
        print(f"共 {len(papers)} 套，待补页面的 {len(plan)} 套 / {total} 页")
        for pid, _, todo in plan:
            print(f"   {pid}  第 {'、'.join(str(i + 1) for i in todo)} 页")
        return

    targets = plan if args.all else [x for x in plan if x[0] == args.only]
    if not targets:
        print("没有要处理的目标，用 --list 看看")
        sys.exit(1)

    BACKUP.mkdir(parents=True, exist_ok=True)
    TEXTDIR.mkdir(parents=True, exist_ok=True)

    from rapidocr import RapidOCR
    engine = RapidOCR(params={"Det.lang_type": "en", "Rec.lang_type": "en"})

    started = time.time()
    for pid, pdf, todo in targets:
        backup = BACKUP / (pid.replace("/", "_") + "-read.pdf")
        if not backup.exists():
            shutil.copy2(pdf, backup)

        doc = pymupdf.open(pdf)
        plain = []
        for index, page in enumerate(doc):
            if index not in todo:
                plain.append("")
                continue
            pix = page.get_pixmap(dpi=args.dpi)
            png = CACHE / "_page.png"
            pix.save(png)
            result = engine(str(png))
            # boxes 是 numpy 数组，不能拿 `or` 判空（会抛 ambiguous）
            boxes = getattr(result, "boxes", None)
            texts = getattr(result, "txts", None)
            if boxes is None or texts is None or len(boxes) == 0:
                boxes, texts = [], []
            scale = 72.0 / args.dpi
            lines = []
            for box, text in zip(boxes, texts):
                clean = latin_only(str(text))
                if not clean:
                    continue
                xs = [float(p[0]) for p in box]
                ys = [float(p[1]) for p in box]
                x0, y0 = min(xs), min(ys)
                height = (max(ys) - y0) or 12
                size = max(4.0, height * scale * 0.82)
                try:
                    page.insert_text(
                        pymupdf.Point(x0 * scale, (max(ys)) * scale - 1),
                        clean,
                        fontsize=size,
                        fontname="helv",
                        render_mode=3,
                        color=None,
                    )
                except Exception:
                    continue
                lines.append(clean)
            plain.append("\n".join(lines))
            print(f"  {pid} 第 {index + 1}/{doc.page_count} 页  {len(lines)} 行", flush=True)

        # 增量保存：原内容不动，只把新增的文字对象追写到文件尾
        doc.saveIncr()
        doc.close()
        (TEXTDIR / (pid.replace("/", "_") + ".txt")).write_text("\n\n".join(plain), encoding="utf-8")
        print(f"完成 {pid}（原文件备份在 {backup.relative_to(ROOT)}）", flush=True)

    print(f"全部结束，用时 {time.time() - started:.0f} 秒")


if __name__ == "__main__":
    main()
