"""把 ECDICT 裁成"这套题库用得上"的小词库。

输入：ECDICT 的 ecdict.csv（66MB，77 万词条）+ data/wordlist.json（从 76 套卷子里抽出的词）
输出：data/dict.json —— 只含有出现过的词，外加一张"词形→原形"的映射表

查词时先用原词查，查不到再走映射表（books→book、went→go 这类）。
"""

import csv
import json
import os
import re
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
# ECDICT 原表很大（66MB），没必要放进题库目录，放在 .cache 里当原料
SOURCE = pathlib.Path(os.environ.get("ECDICT_CSV") or (ROOT / ".cache" / "ecdict.csv"))
WORDS = ROOT / "data" / "wordlist.json"
OUT = ROOT / "data" / "dict.json"

# 只保留释义和音标，其余字段（bnc/frq/detail/audio）用不上，留着白白撑大文件
csv.field_size_limit(10 * 1024 * 1024)


def main() -> None:
    if not SOURCE.exists():
        sys.exit(f"找不到词典源文件：{SOURCE}")
    if not WORDS.exists():
        sys.exit(f"找不到词表：{WORDS}，先跑 tools/collect-words.py")

    wanted = set(json.loads(WORDS.read_text(encoding="utf-8")))
    print(f"目标词 {len(wanted)} 个")

    entries: dict[str, dict] = {}
    forms: dict[str, str] = {}

    with SOURCE.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            word = (row.get("word") or "").strip()
            if not word:
                continue
            key = word.lower()
            translation = (row.get("translation") or "").strip()
            phonetic = (row.get("phonetic") or "").strip()
            exchange = (row.get("exchange") or "").strip()

            # 词形映射：不管这个词本身要不要，都先记下来，供反查原形
            if exchange and key in wanted:
                for part in exchange.split("/"):
                    if ":" not in part:
                        continue
                    tag, value = part.split(":", 1)
                    for variant in value.split(","):
                        variant = variant.strip().lower()
                        # 0:原形 1:原形变换 p:过去式 d:过去分词 i:现在分词 3:第三人称 s:复数 r:比较级 t:最高级
                        if variant and variant != key and tag in {"p", "d", "i", "3", "s", "r", "t"}:
                            forms.setdefault(variant, key)

            if key not in wanted or not translation:
                continue
            entries[key] = {
                "w": word,
                "k": phonetic,
                # ECDICT 里换行有真的，也有字面量的 \n，两种都得切成一个分隔符
                "t": re.sub(r"\\n|\r?\n", "；", translation).strip("；"),
            }

    # 词表里有、但不是词条本身的变形词（比如 books 在词表里但 ECDICT 当成 book 的变形）
    for form, lemma in list(forms.items()):
        if form in entries:
            continue
        base = entries.get(lemma)
        if base:
            entries[form] = {"w": form, "k": base["k"], "t": base["t"], "f": lemma}

    OUT.write_text(json.dumps({"words": entries, "forms": forms}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    size = OUT.stat().st_size / 1024 / 1024
    missing = len(wanted) - len([w for w in wanted if w in entries])
    print(f"词条 {len(entries)} 个，词形映射 {len(forms)} 条")
    print(f"输出 {OUT}  {size:.2f} MB")
    print(f"词典里查不到的 {missing} 个（人名、专有名词、拼写变形）")


if __name__ == "__main__":
    main()
