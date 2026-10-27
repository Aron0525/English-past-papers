"""把解析出来的结构重新排成一份干净的 A4 卷面。

排版规则照着原站 2025.12 第 1 套的样子来，但把原 PDF 里那些不齐的地方全部抹平：
统一字号、统一行距、正文两端对齐、选项固定两列、题目不跨页断开。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

FONT_DIR = Path("C:/Windows/Fonts")
CJK = re.compile(r"[\u3000-\u303f\u4e00-\u9fff\uff00-\uffef]+")

PAGE_W, PAGE_H = A4
MARGIN_X = 45
MARGIN_TOP = 46
MARGIN_BOTTOM = 44
CONTENT_W = PAGE_W - MARGIN_X * 2

BODY = 10.6
LEAD = BODY * 1.46


def register_fonts() -> None:
    pdfmetrics.registerFont(TTFont("SimSun", str(FONT_DIR / "simsun.ttc"), subfontIndex=0))
    pdfmetrics.registerFont(TTFont("SimHei", str(FONT_DIR / "simhei.ttf")))
    pdfmetrics.registerFontFamily("SimSun", normal="SimSun", bold="SimSun")


def mixed(text: str, cjk: str = "SimSun") -> str:
    """中英混排时各用自己的字体，英文 Times 比宋体里的拉丁字母好看得多。"""
    safe = escape(tidy(text))
    return CJK.sub(lambda m: f'<font name="{cjk}">{m.group(0)}</font>', safe)


CJK_GAP = [
    (re.compile(r"(\d)\s+(?=[年月日套届])"), r"\1"),
    (re.compile(r"(?<=[年月日套届])\s+(?=\d)"), ""),
    (re.compile(r"(?<=[（(])\s+"), ""),
    (re.compile(r"\s+(?=[）)])"), ""),
    (re.compile(r"(?<=[，。、；：？！])\s+"), ""),
    (re.compile(r"\s+(?=[，。、；：？！])"), ""),
]


def tidy(text: str) -> str:
    """原 PDF 的字间距会渗进中文里，排出 '2025 年12 月 … （第1 套）' 这种缝。"""
    for pattern, repl in CJK_GAP:
        text = pattern.sub(repl, text)
    return text


def build_styles() -> dict[str, ParagraphStyle]:
    common = {"fontName": "Times-Roman", "textColor": "#111111"}
    return {
        "title": ParagraphStyle(
            "title", fontName="SimHei", fontSize=15.5, leading=22,
            alignment=TA_CENTER, spaceAfter=14 * mm / 2.8, textColor="#111111",
        ),
        "part": ParagraphStyle(
            "part", fontName="Times-Bold", fontSize=12.2, leading=16, alignment=TA_LEFT,
        ),
        "section": ParagraphStyle(
            "section", fontName="Times-Bold", fontSize=11.4, leading=15, alignment=TA_LEFT,
        ),
        "subhead": ParagraphStyle(
            "subhead", fontName="Times-Bold", fontSize=11, leading=15,
            alignment=TA_LEFT, spaceBefore=6, spaceAfter=2,
        ),
        "headline": ParagraphStyle(
            "headline", fontName="Times-Bold", fontSize=11.2, leading=16,
            alignment=TA_CENTER, spaceBefore=2, spaceAfter=2,
        ),
        "directions": ParagraphStyle(
            "directions", fontSize=9.9, leading=14.2, alignment=TA_JUSTIFY,
            firstLineIndent=0, spaceBefore=3, spaceAfter=2, **common,
        ),
        "intro": ParagraphStyle(
            "intro", fontSize=10.2, leading=15, alignment=TA_LEFT,
            spaceBefore=5, spaceAfter=1, **common,
        ),
        "question": ParagraphStyle(
            "question", fontSize=BODY, leading=LEAD, alignment=TA_LEFT,
            spaceBefore=0, **common,
        ),
        "option": ParagraphStyle(
            "option", fontSize=BODY, leading=LEAD, alignment=TA_LEFT, **common,
        ),
        "para": ParagraphStyle(
            "para", fontSize=BODY, leading=LEAD, alignment=TA_JUSTIFY,
            firstLineIndent=13, spaceBefore=0, spaceAfter=5.5, **common,
        ),
        "para_hang": ParagraphStyle(
            "para_hang", fontSize=BODY, leading=LEAD, alignment=TA_JUSTIFY,
            leftIndent=13, firstLineIndent=-13, spaceAfter=5.5, **common,
        ),
        "bank": ParagraphStyle("bank", fontSize=BODY, leading=LEAD, **common),
        "right": ParagraphStyle(
            "right", fontName="Times-Italic", fontSize=8.6, leading=12,
            alignment=TA_RIGHT, textColor="#555555",
        ),
        "minutes": ParagraphStyle(
            "minutes", fontName="Times-Italic", fontSize=9.2, leading=12,
            alignment=TA_RIGHT, textColor="#333333",
        ),
    }


def option_grid(options: list[str], style: ParagraphStyle, narrow: bool = False) -> Table:
    """四个选项默认 2×2，都很短时并成一行四列。narrow 表示首格带了题号，不再并四列。"""
    cells = [Paragraph(mixed(opt), style) for opt in options]
    widths = [pdfmetrics.stringWidth(opt, "Times-Roman", BODY) for opt in options]
    gap = 14
    four_col = (not narrow) and max(widths) <= (CONTENT_W - gap * 3) / 4
    if four_col and len(cells) == 4:
        table = Table([cells], colWidths=[(CONTENT_W - gap * 3) / 4 + gap / 2] * 4)
        table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), gap),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        return table

    half = (CONTENT_W - gap) / 2
    rows = []
    for i in range(0, len(cells), 2):
        pair = cells[i : i + 2]
        while len(pair) < 2:
            pair.append(Paragraph("", style))
        rows.append(pair)
    table = Table(rows, colWidths=[half + gap / 2, half + gap / 2])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), gap),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.6),
            ]
        )
    )
    return table


def flow_for(block: dict, styles: dict) -> list:
    kind = block["t"]

    if kind == "title":
        return [Paragraph(mixed(block["text"], "SimHei"), styles["title"])]

    if kind == "part":
        left = Paragraph(mixed(block["text"], "SimHei"), styles["part"])
        right = Paragraph(block.get("right") or "", styles["minutes"])
        table = Table([[left, right]], colWidths=[CONTENT_W * 0.72, CONTENT_W * 0.28])
        table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.6, "#222222"),
                ]
            )
        )
        return [Spacer(1, 9), table, Spacer(1, 5)]

    if kind == "section":
        return [Spacer(1, 7), Paragraph(mixed(block["text"], "SimHei"), styles["section"]), Spacer(1, 2)]

    if kind == "subhead":
        return [Paragraph(mixed(block["text"]), styles["subhead"])]

    if kind == "headline":
        return [
            Spacer(1, 4),
            Paragraph(mixed(block["text"]), styles["headline"]),
            Spacer(1, 2),
        ]

    if kind == "directions":
        return [Paragraph(mixed(block["text"]), styles["directions"])]

    if kind == "intro":
        return [Paragraph(mixed(block["text"]), styles["intro"])]

    if kind == "question":
        inner = []
        num = block["num"]
        stem = block.get("stem") or ""
        options = list(block["options"])
        if stem:
            inner.append(Paragraph(mixed(f"{num}. {stem}"), styles["question"]))
            if options:
                inner.append(option_grid(options, styles["option"]))
        elif options:
            # 题号直接长在第一个选项前面，排出来就是 "1. A. …"
            options[0] = f"{num}. {options[0]}"
            inner.append(option_grid(options, styles["option"], narrow=True))
        else:
            inner.append(Paragraph(f"{num}.", styles["question"]))
        return [Spacer(1, 4.6), KeepTogether(inner)]

    if kind == "stmt":
        return [
            KeepTogether(
                [Paragraph(mixed(f"{block['num']}. {block['text']}"), styles["question"])]
            )
        ]

    if kind == "bank":
        items = [Paragraph(mixed(i), styles["bank"]) for i in block["items"]]
        rows = [items[i : i + 4] for i in range(0, len(items), 4)]
        for row in rows:
            while len(row) < 4:
                row.append(Paragraph("", styles["bank"]))
        table = Table(rows, colWidths=[CONTENT_W / 4] * 4)
        table.setStyle(
            TableStyle(
                [
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                ]
            )
        )
        return [Spacer(1, 6), table, Spacer(1, 6)]

    if kind == "para":
        style = styles["para_hang"] if block.get("letter") else styles["para"]
        return [Paragraph(mixed(block["text"]), style)]

    return []


def render(payload: dict, out: Path) -> int:
    register_fonts()
    styles = build_styles()

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Times-Roman", 8.4)
        canvas.setFillColor("#888888")
        canvas.drawCentredString(PAGE_W / 2, 22, str(doc.page))
        canvas.setFont("Times-Italic", 7.4)
        canvas.drawRightString(PAGE_W - MARGIN_X, 22, "zhenti-local")
        canvas.restoreState()

    doc = BaseDocTemplate(
        str(out),
        pagesize=A4,
        leftMargin=MARGIN_X,
        rightMargin=MARGIN_X,
        topMargin=MARGIN_TOP,
        bottomMargin=MARGIN_BOTTOM,
        title=payload.get("title", ""),
        author="zhenti-local",
    )
    frame = Frame(
        MARGIN_X, MARGIN_BOTTOM, CONTENT_W,
        PAGE_H - MARGIN_TOP - MARGIN_BOTTOM, id="body",
        leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0,
    )
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=footer)])

    story = []
    for block in payload["blocks"]:
        story.extend(flow_for(block, styles))
    doc.build(story)
    return doc.page


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    target = sys.argv[1] if len(sys.argv) > 1 else "cet6/2025-12/01"
    src = root / ".cache" / "typeset" / (target.replace("/", "_") + ".json")
    if not src.exists():
        raise SystemExit(f"先跑 parse_paper.py {target}")
    payload = json.loads(src.read_text(encoding="utf-8"))
    out = root / "data" / target / "read.clean.pdf"
    pages = render(payload, out)
    print(f"{target}  ->  {out.name}  {pages} 页  {out.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
