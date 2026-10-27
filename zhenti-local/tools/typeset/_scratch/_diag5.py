import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pymupdf
from gidmap import font_maps, translate

ROOT = Path(__file__).resolve().parents[2]


def main(pid: str) -> None:
    pdf = ROOT / "data" / pid / "read.pdf"
    maps = font_maps(pdf)
    print("字体映射条数", len(maps))
    for k, v in maps.items():
        sample = "".join(v[g] for g in sorted(v)[:40])
        print(f"  {k!r}: {len(v)} glyphs  sample={sample!r}")
    doc = pymupdf.open(pdf)
    print("--- 前 30 行翻译 ---")
    shown = 0
    for page in doc:
        d = page.get_text("dict")
        for b in d["blocks"]:
            for l in b.get("lines", []):
                parts = []
                for s in l["spans"]:
                    m = maps.get(s["font"])
                    parts.append(translate(s["text"], m) if m else s["text"])
                line = "".join(parts).strip()
                if line:
                    print(f"  {line[:110]!r}")
                    shown += 1
                    if shown >= 30:
                        return


if __name__ == "__main__":
    main(sys.argv[1])
