import re
import sys
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[2]


def main(pid: str) -> None:
    pdf = ROOT / "data" / pid / "read.pdf"
    doc = pymupdf.open(pdf)
    for xref in range(1, doc.xref_length()):
        if doc.xref_get_key(xref, "Type")[1] != "/Font":
            continue
        bf = doc.xref_get_key(xref, "BaseFont")[1]
        if "Cambria-Bold-5198" not in bf:
            continue
        print("font xref", xref, bf, doc.xref_get_key(xref, "Subtype"))
        for key in ("FontDescriptor", "DescendantFonts", "FirstChar", "LastChar", "CIDToGIDMap"):
            print("  ", key, doc.xref_get_key(xref, key))
        fd = doc.xref_get_key(xref, "FontDescriptor")
        m = re.match(r"(\d+) 0 R", fd[1]) if fd[0] == "xref" else None
        if not m:
            # Type0 -> descendant
            d = doc.xref_get_key(xref, "DescendantFonts")
            print("  desc raw", d)
            mm = re.search(r"(\d+) 0 R", d[1])
            if mm:
                dx = int(mm.group(1))
                print("  desc obj", dx, doc.xref_object(dx)[:400])
                fd = doc.xref_get_key(dx, "FontDescriptor")
                m = re.search(r"(\d+) 0 R", fd[1])
        if m:
            fx = int(m.group(1))
            print("  descriptor", fx, doc.xref_object(fx)[:400])
            for k in ("FontFile", "FontFile2", "FontFile3"):
                print("   ", k, doc.xref_get_key(fx, k))
            ff = doc.xref_get_key(fx, "FontFile3")
            mm2 = re.search(r"(\d+) 0 R", ff[1])
            if mm2:
                sx = int(mm2.group(1))
                buf = doc.xref_stream(sx)
                print("   FontFile3 stream len", len(buf), buf[:16])
                out = Path(__file__).parent / "_font.bin"
                out.write_bytes(buf)
                print("   saved", out)


if __name__ == "__main__":
    main(sys.argv[1])
