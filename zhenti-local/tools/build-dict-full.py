"""把 ECDICT 全量灌进 data/dict.db（SQLite）。

ECDICT 的 exchange 字段形如 `p:went/d:gone/i:going/3:goes`：
  - 键是变形类型（p 过去式 / d 过去分词 / i 现在分词 / 3 三单 / s 复数 / r 比较级 / t 最高级）
  - 值是该词条自己的变形，反过来建 form → word 的索引
  - `0:go` 表示本词是 go 的变形，值就是原形

用法：python tools/build-dict-full.py [--source .cache/ecdict.csv] [--out data/dict.db]
"""

import argparse
import csv
import os
import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = ROOT / ".cache" / "ecdict.csv"
DEFAULT_OUT = ROOT / "data" / "dict.db"

# 变形类型 → 中文说明，前端不用，留着自查
FORM_KEYS = {"p": "过去式", "d": "过去分词", "i": "现在分词", "3": "三单", "s": "复数", "r": "比较级", "t": "最高级"}


def clean(text: str) -> str:
    """ECDICT 里换行有真换行也有字面量 \\n，统一成真换行，多余的空白压掉。"""
    if not text:
        return ""
    text = text.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\r", "\n")
    lines = [" ".join(line.split()) for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=str(DEFAULT_SOURCE))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    source = pathlib.Path(args.source)
    out = pathlib.Path(args.out)
    if not source.exists():
        print(f"找不到词典源：{source}", file=sys.stderr)
        return 1
    if out.exists():
        out.unlink()
    out.parent.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(out)
    con.execute("PRAGMA journal_mode=OFF")
    con.execute("PRAGMA synchronous=OFF")
    con.execute("PRAGMA temp_store=MEMORY")
    con.executescript(
        """
        CREATE TABLE w (
          word TEXT PRIMARY KEY,
          k TEXT,            -- 音标
          t TEXT,            -- 中文释义
          d TEXT,            -- 英文释义
          pos TEXT,          -- 词性分布
          tag TEXT,          -- 考纲标签 zk/gk/cet4/cet6/ky/toefl/ielts
          collins INTEGER,   -- 柯林斯星级
          oxford INTEGER,    -- 是否牛津 3000
          bnc INTEGER,
          frq INTEGER
        );
        CREATE TABLE f (form TEXT PRIMARY KEY, lemma TEXT);
        """
    )

    words, forms = [], []
    with source.open("r", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            word = (row.get("word") or "").strip()
            if not word:
                continue
            translation = clean(row.get("translation") or "")
            definition = clean(row.get("definition") or "")
            if not translation and not definition:
                continue

            def num(key):
                try:
                    return int(float(row.get(key) or 0))
                except (TypeError, ValueError):
                    return 0

            words.append(
                (
                    word,
                    (row.get("phonetic") or "").strip(),
                    translation,
                    definition,
                    (row.get("pos") or "").strip(),
                    (row.get("tag") or "").strip(),
                    num("collins"),
                    num("oxford"),
                    num("bnc"),
                    num("frq"),
                )
            )

            exchange = (row.get("exchange") or "").strip()
            if not exchange:
                continue
            for part in exchange.split("/"):
                if ":" not in part:
                    continue
                key, value = part.split(":", 1)
                value = value.strip()
                if not value:
                    continue
                if key == "0":
                    # 本词是 value 的变形
                    forms.append((word.lower(), value))
                elif key in FORM_KEYS:
                    forms.append((value.lower(), word))

    con.executemany("INSERT OR IGNORE INTO w VALUES (?,?,?,?,?,?,?,?,?,?)", words)
    # 变形表只保留词库里真有原形的，避免指向不存在的词条
    known = {w[0] for w in words}
    con.executemany(
        "INSERT OR IGNORE INTO f VALUES (?,?)",
        [(form, lemma) for form, lemma in forms if form != lemma.lower() and lemma in known],
    )
    con.commit()

    total_words = con.execute("SELECT COUNT(*) FROM w").fetchone()[0]
    total_forms = con.execute("SELECT COUNT(*) FROM f").fetchone()[0]
    con.execute("VACUUM")
    con.close()

    size = out.stat().st_size / 1024 / 1024
    print(f"词条 {total_words}，变形 {total_forms}，{out} {size:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
