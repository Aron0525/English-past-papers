import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pymupdf

ROOT = Path(__file__).resolve().parents[2]


def sfnt_tables(buf: bytes):
    if len(buf) < 12:
        return None
    tag = buf[:4]
    if tag not in (b"\x00\x01\x00\x00", b"OTTO", b"true", b"ttcf"):
        return ("not-sfnt", tag)
    num = struct.unpack(">H", buf[4:6])[0]
    out = []
    for i in range(num):
        off = 12 + i * 16
        t = buf[off:off + 4]
        o, l = struct.unpack(">II", buf[off + 8:off + 16])
        out.append((t.decode("latin-1", "replace"), o, l))
    return out


def main(pid: str) -> None:
    pdf = ROOT / "data" / pid / "read.pdf"
    doc = pymupdf.open(pdf)
    seen = set()
    for xref in range(1, doc.xref_length()):
        if doc.xref_get_key(xref, "Type")[1] != "/Font":
            continue
        bf = doc.xref_get_key(xref, "BaseFont")[1]
        if "Cambria" not in bf and "Times" not in bf:
            continue
        try:
            info = doc.extract_font(xref)
        except Exception as exc:
            print(xref, bf, "提取失败", exc)
            continue
        name, ext, typ, buf = info
        key = (bf, name, len(buf) if buf else 0)
        if key in seen:
            continue
        seen.add(key)
        tables = sfnt_tables(buf) if buf else None
        names = [t[0] for t in tables] if isinstance(tables, list) else tables
        print(f"xref={xref} base={bf} name={name} ext={ext} type={typ} len={len(buf) if buf else 0}")
        print("   tables:", names)


if __name__ == "__main__":
    main(sys.argv[1])
