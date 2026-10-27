"""扫描已收录的试题 PDF，抽出出现过的英文单词，作为精简词库的词表。

只做一件事：读正文文本 → 正则切词 → 小写化 → 统计词频 → 写 JSON。
中文部分的字体没有 ToUnicode 映射时会抽出乱码，但英文不受影响。
"""

import json
import pathlib
import re
import sys

DATA = pathlib.Path(__file__).resolve().parent.parent / "data" / "cet6"
OUT = pathlib.Path(__file__).resolve().parent.parent / "data" / "wordlist.json"

WORD = re.compile(r"[A-Za-z][A-Za-z'\-]{1,24}")

try:
    from pypdf import PdfReader
except ImportError:
    sys.exit("需要 pypdf：pip install pypdf")


def main() -> None:
    counts: dict[str, int] = {}
    files = sorted(DATA.glob("*/*/read.pdf"))
    print(f"扫描 {len(files)} 套试卷")

    for index, path in enumerate(files, 1):
        try:
            reader = PdfReader(str(path))
        except Exception as error:  # 损坏或加密的跳过，不影响整体
            print(f"  跳过 {path.parent.parent.name}/{path.parent.name}: {error}")
            continue
        for page in reader.pages:
            try:
                text = page.extract_text() or ""
            except Exception:
                continue
            for token in WORD.findall(text):
                word = token.strip("-").lower()
                if len(word) < 2:
                    continue
                counts[word] = counts.get(word, 0) + 1
        if index % 20 == 0:
            print(f"  {index}/{len(files)}  累计 {len(counts)} 个词")

    # 词形归并：把复数/过去式之类尽量并到原形上由词典的 exchange 字段处理，
    # 这里只保证词表干净
    ordered = dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))
    OUT.write_text(json.dumps(ordered, ensure_ascii=False), encoding="utf-8")
    print(f"词表 {len(ordered)} 个 → {OUT}")

    common = [w for w, c in ordered.items() if c >= 3]
    print(f"出现 3 次以上的 {len(common)} 个")


if __name__ == "__main__":
    main()
