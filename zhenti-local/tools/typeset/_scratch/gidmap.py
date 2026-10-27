"""给没有 ToUnicode 的 Identity-H 字体反推 GID -> 字符。

站上早期卷子的字体是 Identity-H + 无 ToUnicode，PyMuPDF 只能吐出字形编号。
好在嵌入字体里通常还留着 charset（CFF）或 cmap（TrueType），可以倒着查回来。
"""

from __future__ import annotations

import re
import struct
from pathlib import Path

import pymupdf

# CFF 标准字符串（SID 0..）。只需要覆盖拉丁字母、数字和常见标点。
_STD = (
    ".notdef space exclam quotedbl numbersign dollar percent ampersand quoteright parenleft "
    "parenright asterisk plus comma hyphen period slash zero one two three four five six seven "
    "eight nine colon semicolon less equal greater question at A B C D E F G H I J K L M N O P Q "
    "R S T U V W X Y Z bracketleft backslash bracketright asciicircum underscore quoteleft a b c "
    "d e f g h i j k l m n o p q r s t u v w x y z braceleft bar braceright asciitilde exclamdown "
    "cent sterling fraction yen florin section currency quotesingle quotedblleft guillemotleft "
    "guilsinglleft guilsinglright fi fl endash dagger daggerdbl periodcentered paragraph bullet "
    "quotesinglbase quotedblbase quotedblright guillemotright ellipsis perthousand questiondown "
    "grave acute circumflex tilde macron breve dotaccent dieresis ring cedilla hungarumlaut "
    "ogonek caron emdash AE ordfeminine Lslash Oslash OE ordmasculine ae dotlessi lslash oslash "
    "oe germandbls onesuperior logicalnot mu trademark Eth onehalf plusminus Thorn onequarter "
    "divide brokenbar degree thorn threequarters twosuperior registered minus eth multiply "
    "threesuperior copyright"
).split()

_NAMED = {
    "space": " ", "exclam": "!", "quotedbl": '"', "numbersign": "#", "dollar": "$",
    "percent": "%", "ampersand": "&", "quoteright": "\u2019", "parenleft": "(",
    "parenright": ")", "asterisk": "*", "plus": "+", "comma": ",", "hyphen": "-",
    "period": ".", "slash": "/", "colon": ":", "semicolon": ";", "less": "<", "equal": "=",
    "greater": ">", "question": "?", "at": "@", "bracketleft": "[", "backslash": "\\",
    "bracketright": "]", "asciicircum": "^", "underscore": "_", "quoteleft": "\u2018",
    "braceleft": "{", "bar": "|", "braceright": "}", "asciitilde": "~",
    "quotesingle": "'", "quotedblleft": "\u201c", "quotedblright": "\u201d",
    "endash": "\u2013", "emdash": "\u2014", "bullet": "\u2022", "ellipsis": "\u2026",
    "periodcentered": "\u00b7", "fi": "fi", "fl": "fl", "quotedblbase": "\u201e",
    "quotesinglbase": "\u201a", "degree": "\u00b0", "minus": "\u2212",
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9",
}


def _name_to_char(name: str) -> str | None:
    if name in _NAMED:
        return _NAMED[name]
    if len(name) == 1:
        return name
    # Aacute / eacute 之类：取首字母，忽略重音
    m = re.fullmatch(r"([A-Za-z])(acute|grave|circumflex|dieresis|tilde|ring|cedilla|caron)", name)
    if m:
        return m.group(1)
    return None


# ---------------------------------------------------------------- CFF


def _index(buf: bytes, pos: int) -> tuple[list[bytes], int]:
    count = struct.unpack(">H", buf[pos:pos + 2])[0]
    if count == 0:
        return [], pos + 2
    off_size = buf[pos + 2]
    base = pos + 3
    offs = []
    for i in range(count + 1):
        raw = buf[base + i * off_size: base + (i + 1) * off_size]
        offs.append(int.from_bytes(raw, "big"))
    data = base + (count + 1) * off_size
    items = [buf[data + offs[i] - 1: data + offs[i + 1] - 1] for i in range(count)]
    return items, data + offs[-1] - 1


def _dict_ops(data: bytes) -> dict[int, list[float]]:
    ops: dict[int, list[float]] = {}
    stack: list[float] = []
    i = 0
    while i < len(data):
        b0 = data[i]
        if b0 <= 21:
            op = b0
            i += 1
            if b0 == 12:
                op = 1200 + data[i]
                i += 1
            ops[op] = stack
            stack = []
        elif b0 == 28:
            stack.append(struct.unpack(">h", data[i + 1:i + 3])[0])
            i += 3
        elif b0 == 29:
            stack.append(struct.unpack(">i", data[i + 1:i + 5])[0])
            i += 5
        elif b0 == 30:
            i += 1
            txt = ""
            done = False
            while i < len(data) and not done:
                byte = data[i]
                i += 1
                for nib in (byte >> 4, byte & 15):
                    if nib == 15:
                        done = True
                        break
                    txt += "0123456789.EE?-"[nib] if nib < 14 else ""
            try:
                stack.append(float(txt or 0))
            except ValueError:
                stack.append(0.0)
        elif 32 <= b0 <= 246:
            stack.append(b0 - 139)
            i += 1
        elif 247 <= b0 <= 250:
            stack.append((b0 - 247) * 256 + data[i + 1] + 108)
            i += 2
        elif 251 <= b0 <= 254:
            stack.append(-(b0 - 251) * 256 - data[i + 1] - 108)
            i += 2
        elif b0 == 255:
            stack.append(struct.unpack(">i", data[i + 1:i + 5])[0] / 65536)
            i += 5
        else:
            i += 1
    return ops


def _cff_gidmap(buf: bytes) -> dict[int, str] | None:
    if not buf or buf[0] != 1:
        return None
    try:
        pos = buf[2]
        _names, pos = _index(buf, pos)
        tops, pos = _index(buf, pos)
        strings, pos = _index(buf, pos)
        if not tops:
            return None
        top = _dict_ops(tops[0])
        charstrings_off = int(top.get(17, [0])[0])
        charset_off = int(top.get(15, [0])[0])
        if not charstrings_off:
            return None
        glyphs, _ = _index(buf, charstrings_off)
        n = len(glyphs)
        sids: list[int] = []
        if charset_off == 0:  # ISOAdobe：SID == GID
            sids = list(range(n))
        elif charset_off in (1, 2):  # Expert 预置，本级用不到
            return None
        else:
            fmt = buf[charset_off]
            p = charset_off + 1
            sids = [0]
            if fmt == 0:
                while len(sids) < n:
                    sids.append(struct.unpack(">H", buf[p:p + 2])[0])
                    p += 2
            elif fmt in (1, 2):
                while len(sids) < n:
                    first = struct.unpack(">H", buf[p:p + 2])[0]
                    if fmt == 1:
                        left = buf[p + 2]
                        p += 3
                    else:
                        left = struct.unpack(">H", buf[p + 2:p + 4])[0]
                        p += 4
                    sids.append(first)
                    for k in range(left):
                        sids.append(first + k + 1)
            else:
                return None
        out = {}
        for gid, sid in enumerate(sids):
            if sid < len(_STD):
                ch = _name_to_char(_STD[sid])
            else:
                idx = sid - len(_STD)
                nm = strings[idx].decode("latin-1", "replace") if idx < len(strings) else ""
                ch = _name_to_char(nm)
            if ch:
                out[gid] = ch
        return out or None
    except Exception:
        return None


# ---------------------------------------------------------------- TrueType


def _sfnt_cmap_gidmap(buf: bytes) -> dict[int, str] | None:
    if not buf or buf[:4] not in (b"\x00\x01\x00\x00", b"OTTO", b"true"):
        return None
    try:
        num = struct.unpack(">H", buf[4:6])[0]
        cmap_off = None
        for i in range(num):
            off = 12 + i * 16
            if buf[off:off + 4] == b"cmap":
                cmap_off = struct.unpack(">I", buf[off + 8:off + 12])[0]
                break
        if cmap_off is None:
            return None
        ntab = struct.unpack(">H", buf[cmap_off + 2:cmap_off + 4])[0]
        cands = []
        for i in range(ntab):
            p = cmap_off + 4 + i * 8
            pid, eid, sub = struct.unpack(">HHI", buf[p:p + 8])
            cands.append((pid, eid, cmap_off + sub))
        gid2ch: dict[int, str] = {}
        for pid, eid, sub in cands:
            fmt = struct.unpack(">H", buf[sub:sub + 2])[0]
            if fmt == 4:
                segx2 = struct.unpack(">H", buf[sub + 6:sub + 8])[0]
                seg = segx2 // 2
                ends = struct.unpack(">" + "H" * seg, buf[sub + 14:sub + 14 + segx2])
                starts_off = sub + 16 + segx2
                starts = struct.unpack(">" + "H" * seg, buf[starts_off:starts_off + segx2])
                deltas_off = starts_off + segx2
                deltas = struct.unpack(">" + "h" * seg, buf[deltas_off:deltas_off + segx2])
                range_off = deltas_off + segx2
                ranges = struct.unpack(">" + "H" * seg, buf[range_off:range_off + segx2])
                for i in range(seg):
                    for c in range(starts[i], min(ends[i], 0xFFFF) + 1):
                        if ranges[i] == 0:
                            gid = (c + deltas[i]) & 0xFFFF
                        else:
                            gp = range_off + i * 2 + ranges[i] + (c - starts[i]) * 2
                            if gp + 2 > len(buf):
                                continue
                            gid = struct.unpack(">H", buf[gp:gp + 2])[0]
                            if gid:
                                gid = (gid + deltas[i]) & 0xFFFF
                        if gid and gid not in gid2ch:
                            gid2ch[gid] = chr(c)
            elif fmt == 12:
                ngroups = struct.unpack(">I", buf[sub + 12:sub + 16])[0]
                p = sub + 16
                for _ in range(ngroups):
                    s, e, g = struct.unpack(">III", buf[p:p + 12])
                    p += 12
                    for c in range(s, min(e, s + 2000) + 1):
                        gid = g + (c - s)
                        if gid not in gid2ch:
                            gid2ch[gid] = chr(c)
        return gid2ch or None
    except Exception:
        return None


# ---------------------------------------------------------------- 对外接口


def font_maps(pdf: Path) -> dict[str, dict[int, str]]:
    """返回 {span 里的字体名: {GID: 字符}}。"""
    doc = pymupdf.open(pdf)
    out: dict[str, dict[int, str]] = {}
    for xref in range(1, doc.xref_length()):
        try:
            if doc.xref_get_key(xref, "Type")[1] != "/Font":
                continue
            if doc.xref_get_key(xref, "Subtype")[1] != "/Type0":
                continue
            if doc.xref_get_key(xref, "Encoding")[1] != "/Identity-H":
                continue
        except Exception:
            continue
        desc = doc.xref_get_key(xref, "DescendantFonts")
        mm = re.search(r"(\d+) 0 R", desc[1] or "")
        if not mm:
            continue
        dx = int(mm.group(1))
        fd = doc.xref_get_key(dx, "FontDescriptor")
        mm = re.search(r"(\d+) 0 R", fd[1] or "")
        if not mm:
            continue
        fx = int(mm.group(1))
        name = doc.xref_get_key(fx, "FontName")[1].lstrip("/")
        buf = None
        for key, parser in (("FontFile3", _cff_gidmap), ("FontFile2", _sfnt_cmap_gidmap)):
            ref = doc.xref_get_key(fx, key)
            mm = re.search(r"(\d+) 0 R", ref[1] or "")
            if mm:
                try:
                    raw = doc.xref_stream(int(mm.group(1)))
                except Exception:
                    raw = None
                if raw:
                    mapping = parser(raw)
                    if mapping:
                        buf = mapping
                        break
        if not buf:
            continue
        # span 里的字体名去掉了子集前缀，比如 POMFDA+*Cambria-Bold-5198 -> *Cambria-Bold-5198
        clean = name.split("+", 1)[1] if "+" in name else name
        out.setdefault(clean, buf)
    doc.close()
    return out


def translate(text: str, mapping: dict[int, str]) -> str:
    return "".join(mapping.get(ord(ch), ch) for ch in text)
