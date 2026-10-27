"""给坏字体的卷子反推 GID -> 字符。

早期那批卷子的字体是 Identity-H 且没有 ToUnicode，文字层只剩字形编号，读出来是
"\x0e\x03U\x14EU" 这种东西。但这些卷子里同时压着一层 SimSun 的隐形文字层，位置和
密文层几乎重合，内容是可读的英文（站点当年自己 OCR 出来的，有个别错字）。

所以做法是：
1. 把可读层（非 Identity-H 字体）的字符按坐标摊开；
2. 每个密文字形，找同一行上 x 最接近的可读字符，投一票；
3. 同一个 (字体, 编号) 在整卷里出现几百次，取多数；
4. 投票结果落成 gidmap.json，解析时翻译。

可读层的错字是偶发的，几百票取多数之后基本被抹平；而字符身份由字形编号决定，
最终拿到的文本是精确的，坐标也是原来的。
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pymupdf

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PAGES = 40  # 尽量整卷都投，页数上限只是保险


# ---------------------------------------------------------------- 字体分类

def _font_index(doc) -> tuple[dict[str, dict], set[str]]:
    """过一遍字体对象：记下 Identity-H 且无 ToUnicode 的（密文），以及全部字体名。"""
    cipher: dict[str, dict] = {}
    every: set[str] = set()
    for xref in range(1, doc.xref_length()):
        try:
            if doc.xref_get_key(xref, "Type")[1] != "/Font":
                continue
            base = doc.xref_get_key(xref, "BaseFont")[1].lstrip("/")
            enc = doc.xref_get_key(xref, "Encoding")[1]
            tounicode = doc.xref_get_key(xref, "ToUnicode")[1]
            subtype = doc.xref_get_key(xref, "Subtype")[1]
        except Exception:
            continue
        clean = base.split("+", 1)[1] if "+" in base else base
        clean = re.sub(r"-Identity-H$", "", clean)
        every.add(clean)
        if subtype == "/Type0" and enc == "/Identity-H" and tounicode == "null":
            cipher.setdefault(clean, {"tounicode": False})
    return cipher, every


def font_roles(pdf: Path) -> tuple[set[str], set[str]]:
    """返回 (密文字体集合, 可读字体集合)。

    光看字体属性不够：有的 Identity-H 卷子没有 ToUnicode，但字体自带 cmap，
    PyMuPDF 照样能解出正常文字。所以再验一道，抽出来的字符里控制字符占多数才算密文。
    """
    doc = pymupdf.open(pdf)
    cipher, every = _font_index(doc)
    if cipher:
        # span 里的字体名被截到 20 个字符，这里统一按前缀比
        short = {f[:20] for f in cipher}
        stats: dict[str, list[int]] = {}
        for pno in range(min(4, doc.page_count)):
            for b in doc[pno].get_text("dict")["blocks"]:
                for l in b.get("lines", []):
                    for s in l["spans"]:
                        name = s["font"][:20]
                        if name not in short:
                            continue
                        slot = stats.setdefault(name, [0, 0])
                        for ch in s["text"]:
                            slot[1] += 1
                            if ord(ch) < 32 or 0x80 <= ord(ch) < 0x200:
                                slot[0] += 1
        cipher = {f for f in cipher if stats.get(f[:20], [0, 0])[1] and
                  stats[f[:20]][0] / stats[f[:20]][1] > 0.02}
    doc.close()
    return set(cipher), every - set(cipher)


# ---------------------------------------------------------------- 按行聚字符

def page_rows(page, want: set[str]) -> list[dict]:
    """把指定字体的字符按 y 聚成行，行内按 x 排序，同位置重复的只留一个。"""
    rows: list[dict] = []
    for b in page.get_text("rawdict")["blocks"]:
        for l in b.get("lines", []):
            for s in l["spans"]:
                if s["font"] not in want:
                    continue
                for c in s["chars"]:
                    x0, y0, x1, y1 = c["bbox"]
                    cy = (y0 + y1) / 2
                    cx = (x0 + x1) / 2
                    tol = max(3.5, s["size"] * 0.42)
                    for row in rows[-8:]:
                        if abs(row["y"] - cy) <= tol:
                            row["chars"].append({"c": c["c"], "x": cx, "w": x1 - x0,
                                                 "font": s["font"], "size": s["size"]})
                            row["y"] = min(row["y"], cy)
                            break
                    else:
                        rows.append({"y": cy, "chars": [{"c": c["c"], "x": cx, "w": x1 - x0,
                                                         "font": s["font"], "size": s["size"]}]})
    for row in rows:
        chars = sorted(row["chars"], key=lambda t: t["x"])
        clean: list[dict] = []
        for ch in chars:
            if clean and abs(clean[-1]["x"] - ch["x"]) < 0.6 and clean[-1]["c"] == ch["c"]:
                continue
            clean.append(ch)
        row["chars"] = clean
    return [r for r in rows if r["chars"]]


def _align_row(ciph: list[dict], ref: list[dict]) -> list[tuple[int, int]]:
    """两条序列按行内归一化位置做带间隔的对齐，返回配对的 (密文下标, 参考下标)。

    空格在两层里的数量不一样（一层等宽、一层按字宽），会带偏整行，所以先把空格
    摘掉再对齐，对完了按下标映射回原序列。
    """
    ci = [i for i, c in enumerate(ciph) if c["c"] != " "]
    ri = [j for j, r in enumerate(ref) if r["c"] != " "]
    a = [ciph[i] for i in ci]
    b = [ref[j] for j in ri]
    if not a or not b:
        return []
    ax0, ax1 = a[0]["x"], a[-1]["x"]
    bx0, bx1 = b[0]["x"], b[-1]["x"]
    an = max(1e-6, ax1 - ax0)
    bn = max(1e-6, bx1 - bx0)
    n, m = len(a), len(b)
    tp = [(c["x"] - ax0) / an for c in a]
    tr = [(r["x"] - bx0) / bn for r in b]
    gap = 0.6
    INF = 1e9
    dp = [[INF] * (m + 1) for _ in range(n + 1)]
    back = [[0] * (m + 1) for _ in range(n + 1)]
    dp[0][0] = 0.0
    for i in range(n + 1):
        for j in range(m + 1):
            cur = dp[i][j]
            if cur >= INF:
                continue
            if i < n and j < m:
                cost = cur + abs(tp[i] - tr[j])
                if cost < dp[i + 1][j + 1]:
                    dp[i + 1][j + 1] = cost
                    back[i + 1][j + 1] = 0
            if i < n:
                cost = cur + gap
                if cost < dp[i + 1][j]:
                    dp[i + 1][j] = cost
                    back[i + 1][j] = 1
            if j < m:
                cost = cur + gap
                if cost < dp[i][j + 1]:
                    dp[i][j + 1] = cost
                    back[i][j + 1] = 2
    pairs = []
    i, j = n, m
    while i > 0 or j > 0:
        b_ = back[i][j]
        if i > 0 and j > 0 and b_ == 0:
            pairs.append((ci[i - 1], ri[j - 1]))
            i -= 1
            j -= 1
        elif i > 0 and (b_ == 1 or j == 0):
            i -= 1
        else:
            j -= 1
    pairs.reverse()
    return pairs


def build(pdf: Path) -> dict:
    cipher, readable = font_roles(pdf)
    doc = pymupdf.open(pdf)
    votes: dict[tuple[str, int], Counter] = defaultdict(Counter)
    aligned = 0
    pages_used = 0
    for pno in range(min(PAGES, doc.page_count)):
        page = doc[pno]
        key_rows = page_rows(page, cipher)
        ref_rows = page_rows(page, readable)
        if not key_rows or not ref_rows:
            continue
        pages_used += 1
        ref_by_y = sorted(((r["y"], r["chars"]) for r in ref_rows), key=lambda t: t[0])
        for row in key_rows:
            cand = [(abs(y - row["y"]), chars) for y, chars in ref_by_y if abs(y - row["y"]) <= 6.0]
            if not cand:
                continue
            _, ref_chars = min(cand, key=lambda t: t[0])
            for i, j in _align_row(row["chars"], ref_chars):
                ch, ref = row["chars"][i], ref_chars[j]
                if not ref["c"].strip():
                    continue
                votes[(ch["font"], ord(ch["c"]))][ref["c"]] += 1
                aligned += 1
    doc.close()


    # 一个字体里字码和字符是一一对应的，按票数从高到低贪心分配，已经用掉的字符不再给
    grouped: dict[str, list[tuple[int, int, Counter]]] = defaultdict(list)
    for (font, code), counter in votes.items():
        grouped[font].append((sum(counter.values()), code, counter))

    mapping: dict[str, dict[str, str]] = {}
    detail: dict[str, dict[str, dict]] = {}
    for font, entries in grouped.items():
        entries.sort(key=lambda t: -t[0])
        taken: set[str] = set()
        for total, code, counter in entries:
            ranked = counter.most_common()
            choice = None
            for cand, _ in ranked:
                if cand not in taken:
                    choice = cand
                    break
            if choice is None:
                choice = ranked[0][0]
            taken.add(choice)
            mapping.setdefault(font, {})[str(code)] = choice
            detail.setdefault(font, {})[str(code)] = {
                "top": choice,
                "n": total,
                "share": round(counter[choice] / total, 3),
                "alts": [[c, m] for c, m in ranked[:3] if c != choice],
            }
    return {"map": mapping, "detail": detail,
            "info": {"aligned": aligned, "cipher_fonts": sorted(cipher), "readable_fonts": sorted(readable)}}


def apply_map(text: str, mapping: dict[str, str]) -> str:
    return "".join(mapping.get(str(ord(ch)), ch) for ch in text)


def load(json_path: Path) -> dict[str, dict[str, str]]:
    if not json_path.exists():
        return {}
    data = json.loads(json_path.read_text(encoding="utf-8"))
    return data.get("map", data)


if __name__ == "__main__":
    pdf = Path(sys.argv[1])
    res = build(pdf)
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else pdf.parent / "gidmap.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(res["info"], ensure_ascii=False))
    for font, m in res["map"].items():
        low = [k for k in m if res["detail"][font][k]["share"] < 0.6]
        print(f"  {font}: {len(m)} 个字形, 低置信 {len(low)}")
