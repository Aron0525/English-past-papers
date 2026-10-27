"""用字形宽度指纹反推 CID -> 字符。

子集字体不改宽度，所以 /W 里的每个 CID 宽度等于原字体里那个字符的 advance width。
拿 Windows 上的 timesbd.ttf / cambriab.ttf 做参照，先看候选集有多窄。
"""

from __future__ import annotations

import re
import struct
import sys
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[2]
FONTS = Path("C:/Windows/Fonts")


def sfnt(path: Path, index: int = 0) -> tuple[dict[str, bytes], int]:
    buf = path.read_bytes()
    base = 0
    if buf[:4] == b"ttcf":
        n = struct.unpack(">I", buf[8:12])[0]
        offs = struct.unpack(">" + "I" * n, buf[12:12 + 4 * n])
        base = offs[index]
    num = struct.unpack(">H", buf[base + 4:base + 6])[0]
    tables = {}
    for i in range(num):
        p = base + 12 + i * 16
        tag = buf[p:p + 4].decode("latin-1")
        off, ln = struct.unpack(">II", buf[p + 8:p + 16])
        tables[tag] = buf[off:off + ln]
    return tables, base


def ref_widths(path: Path) -> tuple[int, dict[str, int]]:
    t, _ = sfnt(path)
    head = t["head"]
    upem = struct.unpack(">H", head[18:20])[0]
    nhm = struct.unpack(">H", t["hhea"][34:36])[0]
    hmtx = t["hmtx"]
    adv = []
    for i in range(nhm):
        adv.append(struct.unpack(">H", hmtx[i * 4:i * 4 + 2])[0])
    cmap = t["cmap"]
    ntab = struct.unpack(">H", cmap[2:4])[0]
    char2gid: dict[str, int] = {}
    for i in range(ntab):
        pid, eid, sub = struct.unpack(">HHI", cmap[4 + i * 8:12 + i * 8])
        fmt = struct.unpack(">H", cmap[sub:sub + 2])[0]
        if fmt != 4:
            continue
        segx2 = struct.unpack(">H", cmap[sub + 6:sub + 8])[0]
        seg = segx2 // 2
        ends = struct.unpack(">" + "H" * seg, cmap[sub + 14:sub + 14 + segx2])
        so = sub + 16 + segx2
        starts = struct.unpack(">" + "H" * seg, cmap[so:so + segx2])
        do = so + segx2
        deltas = struct.unpack(">" + "h" * seg, cmap[do:do + segx2])
        ro = do + segx2
        ranges = struct.unpack(">" + "H" * seg, cmap[ro:ro + segx2])
        for k in range(seg):
            for c in range(starts[k], min(ends[k], 0xFFFF) + 1):
                if ranges[k] == 0:
                    g = (c + deltas[k]) & 0xFFFF
                else:
                    gp = ro + k * 2 + ranges[k] + (c - starts[k]) * 2
                    if gp + 2 > len(cmap):
                        continue
                    g = struct.unpack(">H", cmap[gp:gp + 2])[0]
                    if g:
                        g = (g + deltas[k]) & 0xFFFF
                if g and 32 <= c <= 126:
                    char2gid[chr(c)] = g
        if char2gid:
            break
    out = {}
    for ch, g in char2gid.items():
        w = adv[g] if g < len(adv) else adv[-1]
        out[ch] = w
    return upem, out


def pdf_widths(pdf: Path, match: str) -> dict[int, float]:
    doc = pymupdf.open(pdf)
    res = {}
    for xref in range(1, doc.xref_length()):
        if doc.xref_get_key(xref, "Type")[1] != "/Font":
            continue
        bf = doc.xref_get_key(xref, "BaseFont")[1]
        if match not in bf:
            continue
        desc = doc.xref_get_key(xref, "DescendantFonts")
        mm = re.search(r"(\d+) 0 R", desc[1] or "")
        if not mm:
            continue
        dx = int(mm.group(1))
        w = doc.xref_get_key(dx, "W")[1]
        nums = [float(x) for x in re.findall(r"-?\d+\.?\d*", w)]
        i = 0
        while i < len(nums):
            start = int(nums[i])
            if i + 1 < len(nums) and nums[i + 1] == int(nums[i + 1]) and start == nums[i]:
                # 逐字形式：c [w w w ...]
                j = i + 1
                c = start
                while j < len(nums):
                    res[c] = nums[j]
                    c += 1
                    j += 1
                    if j < len(nums) and nums[j] == int(nums[j]) and j + 1 < len(nums) and nums[j + 1] not in ():
                        # 猜下一个是新的起始 CID（宽度一般 > 100 且为整数）
                        pass
                    break
                i += 1
            i += 1
        break
    doc.close()
    return res


def main(pid: str, match: str, ref: str) -> None:
    pdf = ROOT / "data" / pid / "read.pdf"
    upem, rw = ref_widths(FONTS / ref)
    print(f"参照字体 {ref} upem={upem} 字符数={len(rw)}")
    doc = pymupdf.open(pdf)
    for xref in range(1, doc.xref_length()):
        if doc.xref_get_key(xref, "Type")[1] != "/Font":
            continue
        bf = doc.xref_get_key(xref, "BaseFont")[1]
        if match not in bf or doc.xref_get_key(xref, "Subtype")[1] != "/Type0":
            continue
        desc = doc.xref_get_key(xref, "DescendantFonts")
        mm = re.search(r"(\d+) 0 R", desc[1] or "")
        dx = int(mm.group(1))
        raw = doc.xref_get_key(dx, "W")[1]
        nums = [int(float(x)) for x in re.findall(r"-?\d+", raw)]
        print(f"\n{bf} W={nums[:40]}")
        # 解析 c [w...] 形式
        cid_w: dict[int, int] = {}
        i = 0
        while i < len(nums):
            first = nums[i]
            if i + 1 < len(nums) and raw and re.search(rf"{first}\s*\[", raw):
                j = raw.find("[", raw.find(str(first)))
                k = raw.find("]", j)
                ws = [int(float(x)) for x in re.findall(r"-?\d+", raw[j + 1:k])]
                for off, w in enumerate(ws):
                    cid_w[first + off] = w
                i += 1
            else:
                i += 1
        print(f"  解析到 {len(cid_w)} 个 CID 宽度")
        scale = upem / 1000.0
        for cid in sorted(cid_w):
            w = cid_w[cid] * scale
            cands = [ch for ch, ww in rw.items() if abs(ww - w) <= 2]
            print(f"   cid{cid:3d} w={cid_w[cid]:4d} -> {''.join(cands)!r} ({len(cands)})")
        break


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
