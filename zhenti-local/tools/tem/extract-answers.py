#!/usr/bin/env python
"""从专四 / 专八归档的答案解析里抽客观题答案，写成 answers.json。

只认两种写得很直白的答案表，其他一律不动：
    1-5 CDBAC   6-10 DACDB   （区间连写）
    1. C  2. A  3. D         （逐题列出）
抽完自己校验：区间必须连续、每道题只能有一个答案、总数至少 15 题。
任何一条不满足就整套跳过，宁缺勿错。抽出来的答案会在 meta 里写明出处，
因为来源站给的答案本身可能有争议，没人逐题核过。

用法
    python tools/tem/extract-answers.py --dry
    python tools/tem/extract-answers.py
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"

# 区间连写：1-5 CDBAC / 11～15 CADCB / 1—5 ABCAB
RE_RANGE = re.compile(r"(?<![0-9])(\d{1,3})\s*[-–—~～]\s*(\d{1,3})\s*[:：]?\s*([A-Da-d]{2,12})(?![A-Za-z])")
# 逐题：1. C / 2、A / 3) D，后面必须跟非字母（避免吃掉题干里的词）
RE_ITEM = re.compile(r"(?<![0-9])(\d{1,3})\s*[.、)．]\s*([A-D])(?![A-Za-z])")

MIN_COUNT = 15


def collect(text: str) -> dict[int, str]:
    """两套写法都试一遍，取抽得多的那种；有冲突的题直接丢弃。"""
    ranged: dict[int, str] = {}
    for hit in RE_RANGE.finditer(text):
        start, end, letters = int(hit.group(1)), int(hit.group(2)), hit.group(3)
        if end <= start or end - start + 1 != len(letters):
            continue
        for offset, letter in enumerate(letters.upper()):
            numbered = start + offset
            answer = ranged.setdefault(numbered, letter)
            if answer != letter:
                ranged[numbered] = None      # 同一题两处答案不一致，标记成脏
    ranged = {n: a for n, a in ranged.items() if a}

    itemed: dict[int, str] = {}
    for hit in RE_ITEM.finditer(text):
        numbered, letter = int(hit.group(1)), hit.group(2)
        answer = itemed.setdefault(numbered, letter)
        if answer != letter:
            itemed[numbered] = None
    itemed = {n: a for n, a in itemed.items() if a}

    return ranged if len(ranged) >= len(itemed) else itemed


def is_sane(answers: dict[int, str]) -> bool:
    if len(answers) < MIN_COUNT:
        return False
    numbers = sorted(answers)
    # 题号得基本连成一段：来源页偶尔跳号或重叠，缺 15% 以内认，多就当抽错了
    span = numbers[-1] - numbers[0] + 1
    allowed_gap = max(3, int(span * 0.15))
    return len(numbers) >= span - allowed_gap


def paper_text(paper_dir: Path) -> tuple[str, str]:
    """优先解析 PDF（就是网页重排出来的），没有就退回源需要的日志 meta。"""
    analysis = paper_dir / "analysis.pdf"
    source_name = ""
    meta_path = paper_dir / "meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        for entry in meta.get("files", {}).values():
            if entry.get("name") == "analysis.pdf":
                source_name = entry.get("originName", "")
    if not analysis.exists():
        return "", source_name
    import pymupdf
    with pymupdf.open(analysis) as doc:
        return "".join(page.get_text() for page in doc), source_name


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--exam", choices=["tem4", "tem8", "all"], default="all")
    args = ap.parse_args()

    for exam in (["tem4", "tem8"] if args.exam == "all" else [args.exam]):
        for paper_dir in sorted((DATA / exam).glob("*/*")):
            if not (paper_dir / "meta.json").exists():
                continue
            text, source = paper_text(paper_dir)
            if not text:
                continue
            answers = collect(text)
            if not is_sane(answers):
                print(f"  {paper_dir.relative_to(DATA)}  跳过（只抽到 {len(answers)} 题，或题号不成段）")
                continue
            numbers = sorted(answers)
            print(f"  {paper_dir.relative_to(DATA)}  {len(answers)} 题  第 {numbers[0]}–{numbers[-1]} 题  来源 {source or '?'}")
            if args.dry:
                continue
            ordered = {str(n): answers[n] for n in numbers}
            (paper_dir / "answers.json").write_text(
                json.dumps(ordered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            meta_path = paper_dir / "meta.json"
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta.setdefault("capabilities", {})["answers"] = True
            meta["answersSource"] = source or "归档答案解析页"
            meta["answersNote"] = "由归档答案页自动抽取，未经逐题人工核对；来源站答案偶有争议，仅供自测参考。"
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
