"""把某一套的 analysis.pdf 拆成逐题解析 analysis.json。

用法：
    python tools/build-analysis.py --only cet6/2026-06/02
    python tools/build-analysis.py --all          # 有 analysis.pdf 的套全跑

输出 data/<套>/analysis.json：
    questions: { "46": { answer, text, page, section } }   # page 是解析 PDF 的页码（1 起）
    blocks:    [ { id: "writing"|"translation", title, text, pages } ]

只抽取、不改写：解析文字原样保留（跨行合并、去连字符断词）。
听力若官方只有"答案+概要"，会标 note="pending-transcript"，等拿到原文再补。
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]

PART_RE = re.compile(r"^Part\s+([IVX]+)\s*(.*)$")
SECTION_RE = re.compile(r"^Section\s+([ABC])\b\s*(.*)$")
QUESTION_RE = re.compile(r"^(\d{1,2})[.、]\s+(\S.*)$")
# 纯题号 + 单字母答案的列表区（"26" "D" 两行一组），不是解析正文
ANSWER_ROW_RE = re.compile(r"^\d{1,2}$")
PASSAGE_RE = re.compile(r"^Passage\s+(One|Two)\b[—\- ]*(.*)$", re.I)


def join_lines(lines: list[str]) -> str:
    """跨行合并：中英文之间不乱加空格；行尾连字符按词库判断是断词还是复合词。"""
    out = ""
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if not out:
            out = line
            continue
        if out.endswith("-") and re.search(r"[A-Za-z]-$", out):
            # self-discipline 这类复合词不能并成 selfdiscipline，拿词库验证一下再决定
            head = re.search(r"([A-Za-z]+)-$", out).group(1)
            tail = re.match(r"^([A-Za-z]+)", line)
            tail_word = tail.group(1) if tail else ""
            merged = (head + tail_word).lower()
            hyphenated = f"{head}-{tail_word}".lower()
            if tail_word and word_exists(merged) and not word_exists(hyphenated):
                out = out[:-1] + line
            else:
                out += line
            continue
        last, first = out[-1], line[0]
        if is_cjk(last) or is_cjk(first):
            out += line
        elif first in "，。、；：）】》)]":
            out += line
        else:
            out += " " + line
    return out.strip()


def is_cjk(char: str) -> bool:
    return "一" <= char <= "鿿" or char in "“”‘’（）《》、。，；：？！—"


_WORD_DB = None
_WORD_CACHE: dict[str, bool] = {}


def word_exists(word: str) -> bool:
    """用本地 ECDICT（dict.db）判断一个词是否真实存在，查不到就当作不存在。"""
    global _WORD_DB
    if not word:
        return False
    if word in _WORD_CACHE:
        return _WORD_CACHE[word]
    if _WORD_DB is None:
        path = ROOT / "data" / "dict.db"
        if path.exists():
            import sqlite3
            _WORD_DB = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        else:
            _WORD_DB = False
    found = False
    if _WORD_DB:
        found = _WORD_DB.execute("SELECT 1 FROM w WHERE word = ? LIMIT 1", (word,)).fetchone() is not None
    _WORD_CACHE[word] = found
    return found


def load_supplement(paper_id: str) -> dict | None:
    """听力补充材料：tools/listening/<套卷 id 换成 - >.json，含原文分段与逐题解析。"""
    path = ROOT / "tools" / "listening" / (paper_id.replace("/", "-") + ".json")
    if not path.exists():
        return None
    return json.loads(path.read_text("utf-8"))


def build(paper_id: str) -> dict:
    directory = ROOT / "data" / paper_id
    doc = pymupdf.open(directory / "analysis.pdf")
    answers = {}
    answers_path = directory / "answers.json"
    if answers_path.exists():
        answers = {k: v for k, v in json.loads(answers_path.read_text("utf-8")).items() if k.isdigit()}

    # 摊平成 (页码, 行) 序列，页码跟着行走，后面每题才知道在解析 PDF 第几页
    rows: list[tuple[int, str]] = []
    for index, page in enumerate(doc):
        for line in page.get_text().splitlines():
            rows.append((index + 1, line.rstrip()))

    questions: dict[str, dict] = {}
    blocks: list[dict] = []
    part = ""
    section = ""
    listening_note = ""

    current_q: dict | None = None
    current_block: dict | None = None
    buffer: list[str] = []

    def flush_question() -> None:
        nonlocal current_q, buffer
        if current_q is not None:
            current_q["text"] = join_lines(buffer)
            if current_q["text"]:
                questions[current_q["q"]] = {
                    "answer": current_q["answer"],
                    "section": current_q["section"],
                    "page": current_q["page"],
                    "text": current_q["text"],
                }
        current_q = None
        buffer = []

    def flush_block() -> None:
        nonlocal current_block, buffer
        if current_block is not None:
            text = join_lines(buffer)
            if text:
                current_block["text"] = text
                blocks.append(current_block)
        current_block = None
        buffer = []

    def flush() -> None:
        if current_q is not None:
            flush_question()
        elif current_block is not None:
            flush_block()
        else:
            buffer.clear()

    for page_no, raw in rows:
        line = raw.strip()
        if not line:
            continue
        part_hit = PART_RE.match(line)
        if part_hit:
            flush()
            part = part_hit.group(1)
            section = ""
            if part == "I":
                current_block = {"id": "writing", "title": "Part I 写作 · 思路与参考范文", "pages": [page_no]}
            elif part == "IV":
                current_block = {"id": "translation", "title": "Part IV 翻译 · 参考译文与要点", "pages": [page_no]}
            continue

        section_hit = SECTION_RE.match(line)
        if section_hit and part in ("II", "III"):
            flush()
            section = f"Part {part} Section {section_hit.group(1)} {section_hit.group(2)}".strip()
            continue

        passage_hit = PASSAGE_RE.match(line)
        if passage_hit and part == "III":
            flush()
            section = f"Part III Section C · {passage_hit.group(0)}"
            continue

        if line.startswith("听力解析概要"):
            listening_note = line
            continue
        if part == "II" and line and not ANSWER_ROW_RE.match(line) and not re.fullmatch(r"[A-O]", line):
            # 听力部分的说明性文字（不是逐题解析）
            listening_note = f"{listening_note} {line}".strip()
            continue

        # 跳过"26 / D"这种答案速查表，只认 "26. …" 开头的解析行
        question_hit = QUESTION_RE.match(line)
        if question_hit and part in ("II", "III"):
            number = int(question_hit.group(1))
            expected = len(questions) + 1
            if 1 <= number <= 55 and (number >= 26 or part == "II"):
                flush()
                key = str(number)
                current_q = {
                    "q": key,
                    "answer": answers.get(key, ""),
                    "section": section,
                    "page": page_no,
                }
                buffer = [question_hit.group(2)]
                continue

        if current_q is not None or current_block is not None:
            buffer.append(line)

    flush()
    doc.close()

    # 听力官方只给答案+概要时，逐题先挂上答案与说明，标 pending，等原文来了再补详细解析
    # 如果 tools/listening/<id>.json 里有转写原文与逐题解析，就用它补上
    supplement = load_supplement(paper_id)
    pending = []
    listening = []
    if supplement:
        for section in supplement.get("sections", []):
            listening.append({
                "id": section["id"],
                "title": section.get("title", section["id"]),
                "from": section.get("from"),
                "to": section.get("to"),
                "text": section.get("text", ""),
            })
    for number in range(1, 26):
        key = str(number)
        if key in questions:
            continue
        if not answers.get(key):
            continue
        extra = (supplement or {}).get("questions", {}).get(key)
        if extra and extra.get("text"):
            questions[key] = {
                "answer": answers[key],
                "section": "Part II Listening Comprehension",
                "page": 2,
                "text": extra["text"],
                "stem": extra.get("stem", ""),
                "choices": extra.get("choices", {}),
                "source": (supplement or {}).get("source", ""),
            }
            continue
        questions[key] = {
            "answer": answers[key],
            "section": "Part II Listening Comprehension",
            "page": 2,
            "text": "",
            "note": "pending-transcript",
        }
        pending.append(key)

    source = supplement.get("source") if supplement else ""
    source_note = supplement.get("sourceNote") if supplement else ""
    return {
        "paperId": paper_id,
        "source": f"analysis.pdf + {source}" if supplement else "analysis.pdf",
        "sourceNote": source_note,
        "questions": dict(sorted(questions.items(), key=lambda kv: int(kv[0]))),
        "blocks": blocks,
        "listening": listening,
        "listeningNote": listening_note,
        "pending": pending,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="套卷 id，如 cet6/2026-06/02")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    if args.only:
        targets = [args.only]
    elif args.all:
        targets = sorted(str(p.parent.relative_to(ROOT / "data")).replace("\\", "/")
                         for p in (ROOT / "data").glob("cet6/*/*/analysis.pdf"))
    else:
        parser.error("要 --only 或 --all")
        return

    for paper_id in targets:
        result = build(paper_id)
        out = ROOT / "data" / paper_id / "analysis.json"
        out.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", "utf-8")
        detailed = sum(1 for q in result["questions"].values() if q.get("text"))
        print(f"{paper_id}: {len(result['questions'])} 题（{detailed} 题有详细解析），"
              f"{len(result['blocks'])} 个写作/翻译块，待补听力 {len(result['pending'])} 题 → {out.name}")


if __name__ == "__main__":
    main()
