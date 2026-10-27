#!/usr/bin/env python
"""把抽好的纯正文排版成一份能进阅读器的 PDF（带文本层，可划词查词）。

这些卷子原本是网页存档，没有原始 PDF。做法是：正文 → 规整 HTML → 无头 Edge 打印。
打印出来的 PDF 有真实文字层，pdf.js 的选中、框词、查词都能用。

用法：
    python tools/tem/build_paper_pdf.py --text x.txt --out read.pdf --title "2016年英语专业四级真题"
    python tools/tem/build_paper_pdf.py --text x.txt --out read.pdf --title "..." --html keep.html
"""
from __future__ import annotations

import argparse
import html
import re
import subprocess
import tempfile
from pathlib import Path

EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
]

# 题型标题、题号、选项：这些必须独立成块
RE_PART = re.compile(r"^(PART|SECTION)\b")
RE_QUESTION = re.compile(r"^\d{1,3}[.)、]\s*")
RE_OPTION = re.compile(r"^[A-D][).、]\s+")
RE_CN = re.compile(r"[\u4e00-\u9fff]")

# 网页常把「PART I DICTATION [10 MIN] Listen to the following…」写在一行里，
# 标题后面紧跟指令。这里把标题切出来，剩下的当正文。
RE_PART_HEAD = re.compile(r"^(PART\s+[IVX]+|Section\s+[A-C]|SECTION\s+[A-C])\s*(.*)$")
# 题型名可能由两三个词组成（LISTENING COMPREHENSION / LANGUAGE USAGE），要整段吃下
HEAD_TAIL = re.compile(
    r"((?:(?:LISTENING|READING|WRITING|LANGUAGE|CLOZE|DICTATION|COMPREHENSION|USAGE|TALK|CONVERSATIONS?)\s*)+)"
    r"(\[[^\]]{1,24}\]|\d+\s*MIN)?"
)
TAIL_STOP = re.compile(r"\b(Listen to|In this section|You will hear|Now listen|Questions?\s+\d|Write|Read the following|There are)\b")


def split_part_line(line: str) -> tuple[str, str] | None:
    """「PART I DICTATION [10 MIN] Listen to…」→ ('PART I DICTATION [10 MIN]', 'Listen to…')"""
    m = RE_PART_HEAD.match(line)
    if not m:
        return None
    prefix, rest = m.group(1), m.group(2)
    rest = rest.strip()
    if not rest:
        return prefix, ""
    cut = None
    stop = TAIL_STOP.search(rest)
    if stop:
        cut = stop.start()
    else:
        tail = HEAD_TAIL.search(rest)
        if tail:
            cut = tail.end()
    if cut is None or cut <= 0:
        return prefix, ""
    head = f"{prefix} {rest[:cut].strip()}".strip()
    body = rest[cut:].strip()
    return head, body


def looks_like_heading(line: str) -> bool:
    letters = [c for c in line if c.isalpha()]
    if not letters:
        return False
    upper = sum(1 for c in letters if c.isupper()) / len(letters)
    return upper > 0.85 and len(line) < 90


def reflow_long_lines(text: str, width: int = 520) -> str:
    """有的归档页整篇只有一行（回忆版常见），这里按句子切成正常长度的段落。

    听写部分用 // 断句，先还原成换行；再把超长行按句末标点拆成若干段。
    """
    text = re.sub(r"\s*//\s*", "\n", text)
    # PART / SECTION 标题前断行，免得和正文糊在一句里
    text = re.sub(r"(?<=[\u4e00-\u9fff。”\".])\s*(?=(PART|Part|SECTION|Section)\s)", "\n", text)
    return text


def split_sentences(text: str, width: int = 520) -> list[str]:
    """把超长行按句末标点切成不超过 width 的几段。"""
    pieces = re.split(r"(?<=[.!?。！？])\s+", text)
    chunks: list[str] = []
    buf = ""
    for piece in pieces:
        piece = piece.strip()
        if not piece:
            continue
        if buf and len(buf) + len(piece) + 1 > width:
            chunks.append(buf)
            buf = piece
        else:
            buf = f"{buf} {piece}".strip() if buf else piece
    if buf:
        chunks.append(buf)
    return chunks


def paragraphize(text: str) -> list[tuple[str, str]]:
    """行 → [(类型, 内容)]，类型是 h / q / opt / p。"""
    text = reflow_long_lines(text)
    blocks: list[tuple[str, str]] = []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            joined = re.sub(r"\s+", " ", " ".join(buf)).strip()
            if joined:
                blocks.append(("p", joined))
            buf.clear()

    def feed(line: str) -> None:
        """普通行：按标点决定接上一段还是另起一段。"""
        if not buf:
            buf.append(line)
            return
        prev = buf[-1]
        glue = f"{prev} {line}" if prev[-1].isascii() and line[0].isascii() else prev + line
        if not re.search(r"[.!?:;]$", prev) or re.match(r"^[a-z,;]", line):
            buf[-1] = glue
        else:
            flush()
            buf.append(line)

    def handle(line: str) -> None:
        if RE_PART.match(line):
            split = split_part_line(line)
            if split:
                flush()
                blocks.append(("h", split[0]))
                if split[1]:
                    # 标题后面那段是普通指令，继续参与段落合并
                    buf.append(split[1])
                return
        if looks_like_heading(line):
            flush()
            blocks.append(("h", line))
        elif RE_QUESTION.match(line):
            flush()
            blocks.append(("q", line))
        elif RE_OPTION.match(line):
            flush()
            blocks.append(("opt", line))
        elif RE_CN.search(line) and len(line) > 24:
            flush()
            blocks.append(("p", line))
        else:
            feed(line)

    for raw in text.split("\n"):
        raw = raw.strip()
        if not raw:
            continue
        # 超长行先切成几段再分类，否则整篇只落成一个块
        for line in (split_sentences(raw) if len(raw) > 560 else [raw]):
            handle(line)
    flush()
    return blocks


CSS = """
@page { size: A4; margin: 16mm 15mm 15mm 15mm; }
* { box-sizing: border-box; }
body {
  font-family: "Times New Roman", "Songti SC", "SimSun", serif;
  font-size: 10.8pt; line-height: 1.55; color: #111; margin: 0;
}
.head { border-bottom: 1.6pt solid #222; padding-bottom: 7pt; margin-bottom: 12pt; }
.head h1 { font-size: 15pt; margin: 0 0 4pt; letter-spacing: .01em; }
.head .meta { font-size: 8.6pt; color: #666; }
h2.part { font-size: 11.4pt; margin: 14pt 0 5pt; padding-bottom: 2pt; border-bottom: .6pt solid #bbb; page-break-after: avoid; }
p { margin: 0 0 5pt; text-align: justify; }
p.q { margin: 8pt 0 3pt; font-weight: 600; page-break-after: avoid; }
p.opt { margin: 0 0 2pt 14pt; text-align: left; }
p.keep { white-space: pre-wrap; }
.blank { margin: 0 0 5pt; border-bottom: .4pt dotted #bbb; height: 2pt; }
"""


def render_html(title: str, meta: str, blocks: list[tuple[str, str]]) -> str:
    body: list[str] = []
    for kind, text in blocks:
        safe = html.escape(text)
        if kind == "h":
            body.append(f'<h2 class="part">{safe}</h2>')
        elif kind == "q":
            body.append(f'<p class="q">{safe}</p>')
        elif kind == "opt":
            body.append(f'<p class="opt">{safe}</p>')
        else:
            body.append(f'<p>{safe}</p>')
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>{CSS}</style></head>
<body>
<div class="head">
  <h1>{html.escape(title)}</h1>
  <div class="meta">{html.escape(meta)}</div>
</div>
{chr(10).join(body)}
</body></html>
"""


def find_browser() -> str:
    for path in EDGE_CANDIDATES:
        if Path(path).exists():
            return path
    raise SystemExit("找不到 Edge / Chrome，无法打印 PDF")


def print_pdf(html_path: Path, pdf_path: Path) -> None:
    # Edge 是独立进程，cwd 不一定是当前目录，两个路径都必须绝对
    pdf_path = pdf_path.resolve()
    html_path = html_path.resolve()
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as profile:
        cmd = [
            find_browser(),
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-pdf-header-footer",
            f"--user-data-dir={profile}",
            f"--print-to-pdf={pdf_path}",
            html_path.as_uri(),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if not pdf_path.exists():
        raise SystemExit(f"打印失败：{result.stderr[-400:]}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--meta", default="")
    ap.add_argument("--html", help="顺便把排版用的 HTML 留一份")
    args = ap.parse_args()

    text = Path(args.text).read_text(encoding="utf-8")
    blocks = paragraphize(text)
    if len(blocks) < 10:
        raise SystemExit(f"正文太少（{len(blocks)} 块），拒绝生成")
    markup = render_html(args.title, args.meta, blocks)

    if args.html:
        Path(args.html).parent.mkdir(parents=True, exist_ok=True)
        Path(args.html).write_text(markup, encoding="utf-8")

    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "paper.html"
        page.write_text(markup, encoding="utf-8")
        print_pdf(page, Path(args.out))

    print(f"{args.out}  {len(blocks)} 块")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
