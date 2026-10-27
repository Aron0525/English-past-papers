"""给坏字体做字形模板匹配：渲染 PDF 里的字形，和系统同名字体渲染的 ASCII 字符逐个比。

思路
1. 从 rawdict 拿到每个字符的坐标和字体名（坏字体只有 GID）；
2. 按 (字体, GID) 收集样本，挑字号最大的几个；
3. 从页面位图上裁出这个字形的墨迹，归一化到 32x32；
4. 把候选字符用同一个渲染器（MuPDF）画出来，同样归一化后比相似度。
两个图像出自同一个光栅化器，差异只剩抗锯齿，匹配很稳。
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import pymupdf
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
FONT_DIR = Path("C:/Windows/Fonts")
CANDS = [chr(c) for c in range(32, 127)]
NORM = 32


def ink_box(img: Image.Image):
    gray = img.convert("L")
    px = gray.load()
    w, h = gray.size
    xs, ys = [], []
    for y in range(h):
        for x in range(w):
            if px[x, y] < 200:
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return min(xs), min(ys), max(xs) + 1, max(ys) + 1


def norm_patch(img: Image.Image):
    box = ink_box(img)
    if not box:
        return None
    crop = img.convert("L").crop(box)
    b_w, b_h = crop.size
    k = NORM / max(b_w, b_h)
    new = crop.resize((max(1, round(b_w * k)), max(1, round(b_h * k))), Image.LANCZOS)
    canvas = Image.new("L", (NORM, NORM), 255)
    canvas.paste(new, ((NORM - new.size[0]) // 2, (NORM - new.size[1]) // 2))
    return canvas, b_w / b_h


def similarity(a: tuple, b: tuple) -> float:
    pa, ar_a = a
    pb, ar_b = b
    da = pa.load()
    db = pb.load()
    diff = 0
    for y in range(NORM):
        for x in range(NORM):
            diff += abs(da[x, y] - db[x, y])
    pixel = 1 - diff / (NORM * NORM * 255)
    shape = 1 - min(1.0, abs(ar_a - ar_b) / max(ar_a, ar_b, 1e-6))
    return pixel * 0.72 + shape * 0.28


_ref_cache: dict[tuple[str, str, float], tuple | None] = {}


def ref_patch(fontfile: str, ch: str, size: float, zoom: float) -> tuple | None:
    key = (fontfile, ch, round(size, 1))
    if key in _ref_cache:
        return _ref_cache[key]
    doc = pymupdf.open()
    page = doc.new_page(width=60, height=60)
    try:
        page.insert_text((10, 40), ch, fontname="F0", fontfile=str(FONT_DIR / fontfile), fontsize=size)
    except Exception:
        _ref_cache[key] = None
        return None
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    doc.close()
    res = norm_patch(img)
    _ref_cache[key] = res
    return res


def font_file_for(span_font: str) -> str | None:
    s = span_font.lower()
    bold = "bold" in s
    italic = "italic" in s or "oblique" in s
    if "cambria" in s:
        return "cambriaz.ttf" if bold and italic else "cambriab.ttf" if bold else "cambriai.ttf" if italic else "cambria.ttc"
    if "times" in s:
        return "timesbi.ttf" if bold and italic else "timesbd.ttf" if bold else "timesi.ttf" if italic else "times.ttf"
    if "arial" in s:
        return "arialbd.ttf" if bold else "arial.ttf"
    _ = bold, italic
    return None


def build_map(pdf: Path, broken: set[str], limit_pages: int = 6) -> dict[str, dict[int, str]]:
    doc = pymupdf.open(pdf)
    samples: dict[tuple[str, int], list[tuple[int, float, tuple]]] = defaultdict(list)
    zoom = 5.0
    for pno in range(min(limit_pages, doc.page_count)):
        page = doc[pno]
        raw = page.get_text("rawdict")
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        for b in raw["blocks"]:
            for l in b.get("lines", []):
                for s in l["spans"]:
                    if s["font"] not in broken:
                        continue
                    for c in s["chars"]:
                        code = ord(c["c"])
                        if code == 32 or code > 0x7F:
                            continue
                        x0, y0, x1, y1 = c["bbox"]
                        w = x1 - x0
                        if w < 1.2:
                            continue
                        pad = 0.6
                        box = (int((x0 - pad) * zoom), int((y0 - pad) * zoom),
                               int((x1 + pad) * zoom), int((y1 + pad) * zoom))
                        box = (max(0, box[0]), max(0, box[1]),
                               min(img.size[0], box[2]), min(img.size[1], box[3]))
                        if box[2] - box[0] < 3 or box[3] - box[1] < 3:
                            continue
                        patch = norm_patch(img.crop(box))
                        if patch:
                            samples[(s["font"], code)].append((pno, s["size"], patch))
        if len(samples) > 300:
            break
    doc.close()

    out: dict[str, dict[int, str]] = {}
    report = []
    for (font, code), items in samples.items():
        ff = font_file_for(font)
        if not ff:
            continue
        items.sort(key=lambda t: -t[1])
        best_total = None
        for _, size, patch in items[:4]:
            scores = []
            for ch in CANDS:
                rp = ref_patch(ff, ch, size, zoom)
                if rp:
                    scores.append((similarity(patch, rp), ch))
            if not scores:
                continue
            scores.sort(reverse=True)
            if best_total is None or scores[0][0] > best_total[0]:
                best_total = (scores[0][0], scores[:3], size)
        if not best_total:
            continue
        _, scores, size = best_total
        ch = scores[0][1]
        out.setdefault(font, {})[code] = ch
        report.append((font, code, ch, scores[0][0], scores[1] if len(scores) > 1 else (0, "")))
    for font, code, ch, sc, second in sorted(report, key=lambda r: (r[0], r[1])):
        print(f"  {font[:28]:28s} gid{code:3d} -> {ch!r}  score={sc:.3f}  次选={second[1]!r}@{second[0]:.3f}")
    return out


if __name__ == "__main__":
    pid = sys.argv[1]
    fonts = sys.argv[2:] or ["*Times New Roman-5194"]
    m = build_map(ROOT / "data" / pid / "read.pdf", set(fonts))
    for f, mm in m.items():
        print(f, "->", "".join(mm[k] for k in sorted(mm)))
