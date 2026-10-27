"""把原站 PDF 的文字层解析成结构化块，供重新排版使用。

原站 PDF 有几个特点，处理时必须绕开：
  * 下划线填空（26、27…）和字间距会把一行拆成一堆 2.5pt 的碎片 span；
  * 选项排成两列，B 和 C 常常落在同一个 y 上；
  * 段落首行缩进约 23pt，续行回到左边距；
  * 每页页脚是页码和站点 URL。

所以这里不信任 pymupdf 的 line 结构，改成按 y 坐标自己聚行、按 x 间隙拆列。
"""

from __future__ import annotations

import difflib
import json
import re
import sys
from pathlib import Path

import pymupdf

PAGE_W = 595.0
LEFT = 30.0
RIGHT = 566.0
FOOTER_Y = 806.0  # A4 上页脚在 814，正文最后一行能到 796，阈值卡在中间；非 A4 卷按页高折算

# 英文里的多空格是 PDF 两端对齐留下的字间距，压成一个
WS = re.compile(r"[ \t\u00a0]+")
# 行首的题目编号，允许 "1." "1 ." "26 " 这种 OCR 抖动
QNUM = re.compile(r"^(\d{1,2})\s*[.、．,，]\s*(.*)$")
OPT = re.compile(r"^([A-O])\s*[.、．,，)]{1,2}\s*(.*)$")
PART = re.compile(r"^(Part\s*(?:[IVX]+|[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ]))\s*(.*)$", re.I)
# 有些卷子打的是罗马数字单字符（Ⅲ 而不是 III），转回 ASCII 才能拼出 "Part III"
ROMAN_CHARS = dict(zip("ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ",
                       ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"]))
SECTION = re.compile(r"^(Section\s+[A-C])\b\s*$", re.I)
QINTRO = re.compile(r"^Questions?\s+\d+\s*(?:to|-|—|–)\s*\d+\b", re.I)


# 少数卷子的文字层后面还压着一层乱码副本，字符落在切罗基文、藏文这些区里
JUNK = re.compile(
    r"[^\x20-\x7E\u00A0-\u00FF\u2000-\u206F\u2010-\u2027\u2030-\u205E"
    r"\u3000-\u303F\u4E00-\u9FFF\uFF00-\uFFEF\u2160-\u217F\u2460-\u24FF]"
)


CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
# 乱码层带的符号：正常英文里不会这么扎堆出现
JUNK_PUNCT = re.compile(r"[=*\\:;#$%&@|~^<>+_§]")
VOWELS = set("aeiouyAEIOUY")


def looks_wordless(tok: str) -> bool:
    """没元音、或连着四个辅音，就不是正常英文词。"""
    if not (set(tok) & VOWELS):
        return True
    run = worst = 0
    for ch in tok:
        if ch in VOWELS:
            run = 0
        else:
            run += 1
            worst = max(worst, run)
    return worst >= 4


def scrub_cjk(text: str) -> str:
    """中文行里夹的英文碎片，读不通的都是叠上去的乱码层，剔掉。

    译文段本来就只用得上「（Chinese idioms）」这种括注，其余英文残片基本都是
    站点把同一段又 OCR 了一遍、字体映射坏掉之后的产物。
    """
    if not CJK_RUN.search(text):
        return text
    out: list[str] = []
    for piece in re.split(r"([\u4e00-\u9fff]+)", text):
        if not piece or CJK_RUN.search(piece):
            out.append(piece)
            continue
        seg = piece.strip()
        if not seg:
            out.append(piece)
            continue
        toks = re.findall(r"[A-Za-z]{2,}", seg)
        if JUNK_PUNCT.search(seg):
            continue
        if not toks:
            # 单字母残片也当乱码；纯标点、纯数字是正常句读
            if re.search(r"[A-Za-z]", seg):
                continue
            out.append(piece)
            continue
        bad = sum(looks_wordless(t) for t in toks) / len(toks) > 0.4
        tiny = len(seg) <= 5 and not re.fullmatch(r"[\s\d.,;:()（）·、\-]*", seg)
        if bad or tiny:
            continue
        out.append(piece)
    return "".join(out)


def normalise(text: str) -> str:
    # 站点有些页面的文字层里混着一串 < c s 之类的符号垃圾，成段出现，先剔掉
    text = re.sub(r"[<>{}\[\]|\\~^`§]{3,}", " ", text)
    text = WS.sub(" ", scrub_cjk(JUNK.sub("", text))).strip()
    # 站点 OCR 把英文标点后的空格吃掉了（"section,you will hear"、"passage.At"）
    text = re.sub(r"(?<=[A-Za-z\)])([,;:])(?=[A-Za-z])", r"\1 ", text)
    text = re.sub(r"(?<=[a-z])\.(?=[A-Z][a-z])", ". ", text)
    # "A),B),C)and D)" 这种括号后直接接字的，补空格
    text = re.sub(r"(?<=\))(?=[A-Za-z])", " ", text)
    # "150words"、"8are" 这类数字与单词粘连
    text = re.sub(r"(?<=\d)(?=[A-Za-z]{3,}\b)", " ", text)
    return dedupe(WS.sub(" ", text).strip())


def is_junk_line(text: str) -> bool:
    """整行几乎全是符号、凑不出单词的，当垃圾丢掉。"""
    core = text.strip()
    if len(core) < 8:
        return False
    letters = len(re.findall(r"[A-Za-z\u4e00-\u9fff]", core))
    return letters / len(core) < 0.45


def dedupe(text: str) -> str:
    """文字层叠了两遍的卷子，一行会被原样写两次，后面还可能拖着乱码。"""
    n = len(text)
    if n < 10:
        return text
    # 两遍之间常常差一个空格（"2.A)It" 对 "2.A) It"），比对时把空白全去掉；
    # 两份又是两次 OCR 的产物，个别字母有出入，所以按相似度认，不要求完全相等
    flat = re.sub(r"\s+", "", text)
    fn = len(flat)
    best = None
    for k in range(max(6, fn // 3), (fn * 2) // 3 + 1):
        head, repeat = flat[:k], flat[k:k * 2]
        if len(repeat) < 6:
            continue
        if head == repeat:
            level = 1.0
        else:
            level = difflib.SequenceMatcher(None, head, repeat).ratio() if len(repeat) >= 20 else 0
        if level > 0.9 and (best is None or level > best[0]):
            best = (level, k)
    if not best:
        return text
    # 把去空白后的切点换算回原文位置
    pos = [i for i, ch in enumerate(text) if not ch.isspace()]
    k = best[1]
    return text[: pos[k]] if k < len(pos) else text


def cipher_fonts(pdf: Path) -> set[str]:
    """找出文字层读不出来的字体（Identity-H 又没有 ToUnicode）。

    这类字体吐出来的只是字形编号，卷子里同时压着一层可读的隐形文字层，
    所以解析时把密文层整层丢掉，只留能读的那一层。
    """
    try:
        from decipher import font_roles

        cipher, _ = font_roles(pdf)
        return cipher
    except Exception:
        return set()


def page_lines(page, skip_fonts: set[str] | None = None) -> list[dict]:
    """把一页里所有 span 按 y 聚成视觉行，再按 x 间隙拆成若干列。"""
    skip = {name[:20] for name in (skip_fonts or set())}
    spans = []
    for block in page.get_text("dict")["blocks"]:
        if block["type"] != 0:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                # pymupdf 把字体名截到 20 个字符，只能按前缀比
                if span["font"][:20] in skip:
                    continue
                text = span["text"]
                # 纯空格 span 必须留着，英文的词间空格常常就是单独一个 span，
                # 一旦按 strip() 过滤掉，整页会粘成 "Hehasdistinguished" 这样。
                if not text:
                    continue
                x0, y0, x1, y1 = span["bbox"]
                spans.append(
                    {
                        "x0": x0,
                        "x1": x1,
                        "y0": y0,
                        "y1": y1,
                        "size": round(span["size"], 1),
                        "font": span["font"],
                        "text": text,
                    }
                )

    spans.sort(key=lambda s: (s["y0"], s["x0"]))
    # 这类卷子把可读文字层写了两遍，坐标几乎重合；重复的不去，整行会变成
    # "Part IIPart II" 这样。按 (文字, 位置) 判重。
    kept: list[dict] = []
    for span in spans:
        dup = False
        for prev in kept[-40:]:
            # 两份副本的文字偶尔差一两个字母（站点当年 OCR 的两次结果），所以只按位置判
            if abs(prev["x0"] - span["x0"]) < 2.0 and abs(prev["y0"] - span["y0"]) < 2.0 \
                    and abs(prev["x1"] - span["x1"]) < 4.0:
                dup = True
                break
        if not dup:
            kept.append(span)
    spans = drop_covered(kept)
    rows: list[dict] = []
    for span in spans:
        # 用垂直中心判行。原站 PDF 把词间空格做成了 2.5pt 的小 span，
        # 它的 y0 比正文低 8pt 左右，跟文字差得远，但中心只差 3pt。
        center = (span["y0"] + span["y1"]) / 2
        tol = max(5.0, span["size"] * 0.5)
        for row in rows[-4:]:
            if abs(row["center"] - center) <= tol:
                row["spans"].append(span)
                row["center"] = min(row["center"], center)
                break
        else:
            rows.append({"center": center, "spans": [span]})

    # 页脚位置随纸张走：2020-12/01 是 A3（1040 高），写死 806 会把下半页整段切掉
    footer = page.rect.height - (842.0 - FOOTER_Y)
    out: list[dict] = []
    for row in rows:
        if row["center"] > footer:
            continue
        cells = split_columns(row["spans"])
        for index, cell in enumerate(cells):
            text = normalise("".join(s["text"] for s in cell))
            if not text or is_junk_line(text):
                continue
            out.append(
                {
                    "y": round(row["center"], 1),
                    "x": round(cell[0]["x0"], 1),
                    "x1": round(cell[-1]["x1"], 1),
                    "size": max(s["size"] for s in cell),
                    "text": text,
                    "col": index,
                    "ncol": len(cells),
                }
            )
    return out


def drop_covered(spans: list[dict]) -> list[dict]:
    """同一行上被另一种字体整段罩住、或内容是别人一段话的子串，都是叠上去的副本层。

    老卷子常见两层：SimSun 排的可读正文，上面又压一层 Times New Roman 的
    OCR 残片（字号、基线都差一两磅，位置却几乎重合）。判据用两条：
    几何上被包住；或者文字本身就是另一层那段话的一部分（"motivating." 之于
    "B) Stimulating and motivating."）。
    """
    out: list[dict] = []
    for a in spans:
        mine = a["text"].strip()
        covered = False
        for b in spans:
            if a is b or b["font"] == a["font"]:
                continue
            if abs(a["y0"] - b["y0"]) > 4.0:
                continue
            overlap = min(a["x1"], b["x1"]) - max(a["x0"], b["x0"])
            shortest = min(a["x1"] - a["x0"], b["x1"] - b["x0"])
            if shortest <= 0 or overlap < 0.5 * shortest:
                continue
            theirs = b["text"].strip()
            if mine == theirs:
                # 两层写的是同一句，只留位置靠前的那个，免得互删
                if (a["x0"], a["y0"]) > (b["x0"], b["y0"]):
                    covered = True
                    break
                continue
            # 残片本身是原文的一部分，或者几何上被整段罩住
            if len(mine) >= 4 and mine in theirs:
                covered = True
                break
            if a["x0"] >= b["x0"] - 1.5 and a["x1"] <= b["x1"] + 1.5 \
                    and len(theirs) >= len(mine):
                covered = True
                break
        if not covered:
            out.append(a)
    return out


def split_columns(spans: list[dict], gap: float = 55.0) -> list[list[dict]]:
    """同一视觉行里，横向空隙超过 gap 就当成左右两列。"""
    spans = sorted(spans, key=lambda s: s["x0"])
    cells: list[list[dict]] = []
    current: list[dict] = []
    prev = None
    for span in spans:
        if prev is not None and span["x0"] - prev["x1"] > gap:
            cells.append(current)
            current = []
        current.append(span)
        prev = span
    if current:
        cells.append(current)
    return cells


def is_footer(text: str) -> bool:
    if re.fullmatch(r"\d{1,3}", text):
        return True
    # 页码和页脚数字被切成 "6.9" 这种，撞上题号格式后会把下一题整段吞掉
    if re.fullmatch(r"\d{1,3}\s*[.·]\s*\d{1,3}", text):
        return True
    # 站点的页脚、店招、水印，都不是卷面内容
    return any(
        mark in text
        for mark in ("burningvocabulary", "zhenti-local", "淘宝", "光速考研")
    )


def parse_pdf(pdf: Path) -> dict:
    doc = pymupdf.open(pdf)
    cipher = cipher_fonts(pdf)
    lines: list[dict] = []
    for page_no, page in enumerate(doc, start=1):
        for line in page_lines(page, cipher):
            if is_footer(line["text"]):
                continue
            line["page"] = page_no
            lines.append(line)
    doc.close()

    # 卷名页眉常在标题之前出现（第 1 页顶端一行 9pt 小字），先把标题定下来再回头剔掉，
    # 否则它会先被当成正文段落吃掉，后面 22pt 的标题才被认出来。
    head = next((item for item in lines if item["size"] >= 16), None)
    if head:
        key = re.sub(r"\s+", "", head["text"])
        lines = [item for item in lines
                 if item is head or re.sub(r"\s+", "", item["text"]) != key]

    max_x1 = max((line["x1"] for line in lines), default=561.0)

    blocks: list[dict] = []
    title = ""
    paragraph: list[str] | None = None
    bank_zone = False
    current_part = ""

    def flush():
        nonlocal paragraph
        if paragraph:
            text = merge(paragraph)
            if bank_zone:
                # 选词填空的 26—35 在原卷里是下划线空格，文字层拿不到横线，这里补回去
                text = re.sub(r"\b(2[6-9]|3[0-5])\b(?!\s*_)", r"\1 ______", text)
            # 段落匹配（Section B）的每段以 [A] [B] … 打头，文字层把十段并成了一段
            marks = list(re.finditer(r"\[([A-Z])]\s*", text))
            if len(marks) >= 3:
                lead = text[: marks[0].start()].strip()
                if lead:
                    blocks.append({"t": "para", "text": lead})
                for pos, mark in enumerate(marks):
                    end = marks[pos + 1].start() if pos + 1 < len(marks) else len(text)
                    body = text[mark.end():end].strip()
                    if body:
                        blocks.append({"t": "para", "text": f"[{mark.group(1)}] {body}"})
            else:
                blocks.append({"t": "para", "text": text})
            paragraph = None

    index = 0
    while index < len(lines):
        line = lines[index]
        text = line["text"]
        size = line["size"]

        # 标题，18pt 居中那一行
        if not title and size >= 16:
            title = text
            blocks.append({"t": "title", "text": text})
            index += 1
            continue

        # 原卷页眉把卷名又排了一遍，落在正文里就是重复标题，去掉
        if title and re.sub(r"\s+", "", text) == re.sub(r"\s+", "", title):
            index += 1
            continue

        part = PART.match(text)
        if part:
            flush()
            tail = part.group(2).strip()
            # "Part II" 和 "Listening Comprehension" 常分开成两列，补上右边那列
            if not tail and index + 1 < len(lines):
                nxt = lines[index + 1]
                if nxt["y"] == line["y"] and nxt["size"] >= 11:
                    tail = nxt["text"]
                    index += 1
            right = ""
            if not right and index + 1 < len(lines):
                nxt = lines[index + 1]
                if re.fullmatch(r"\(\d+\s*minutes?\)", nxt["text"]) and abs(nxt["y"] - line["y"]) < 45:
                    right = nxt["text"]
                    index += 1
            minute = re.search(r"\((\d+)\s*minutes?\)", tail)
            if minute:
                right = minute.group(0)
                tail = tail[: minute.start()].strip()
                # "(30 minutes)" 常是单独一列、字号被压成 2.5
                if index + 1 < len(lines) and lines[index + 1]["y"] == line["y"]:
                    index += 1
            label = "".join(ROMAN_CHARS.get(ch, ch) for ch in part.group(1))
            roman = re.search(r"[IVX]+", label, re.I)
            current_part = f"Part {roman.group(0).upper() if roman else label[4:].strip()} {tail}".strip()
            blocks.append(
                {
                    "t": "part",
                    "text": current_part,
                    "right": right,
                }
            )
            index += 1
            continue

        if SECTION.match(text) or re.match(r"^Section\s+[A-C]\b", text, re.I):
            flush()
            bank_zone = current_part.upper().startswith("PART III") and re.search(
                r"Section\s+A", text, re.I
            ) is not None
            blocks.append({"t": "section", "text": text})
            index += 1
            continue

        if text.startswith("Directions:") or text.startswith("Directions："):
            flush()
            body = [text]
            index += 1
            while index < len(lines) and len(body) < 14:
                nxt = lines[index]
                if is_block_start(nxt["text"]):
                    break
                # Directions 的正文是 11pt；字号跳上去说明已经进了题目或段落。
                # 老卷文字层的字号在 9.5–12.6 之间乱抖，阈值放到 13.5 才不误切
                if nxt["size"] > 13.5:
                    break
                # 文章标题（居中、短行）标志着 Directions 结束。
                # 2015-06/01 的 Section B 没有这道闸，整篇 7000 字正文都被 Directions 吞了；
                # 判据要收紧，否则 Directions 自己的续行（缩进、但近满行）会被当成标题切断
                if (nxt.get("ncol", 1) == 1 and nxt["x"] > 140 and len(nxt["text"]) <= 90
                        and nxt["x1"] < max_x1 * 0.85 and nxt["text"][:1].isupper()):
                    break
                body.append(nxt["text"])
                index += 1
            blocks.append({"t": "directions", "text": merge(body)})
            continue

        if QINTRO.match(text):
            flush()
            blocks.append({"t": "intro", "text": text})
            index += 1
            continue

        qnum = QNUM.match(text)
        if qnum:
            num = int(qnum.group(1))
            # "6.9" 这类页码碎片会撞上题号，后面的选项全被它吞走
            if not re.search(r"[A-Za-z\u4e00-\u9fff]", qnum.group(2)) and len(text) <= 6:
                index += 1
                continue
            if split_options(qnum.group(2)) or options_follow(lines, index):
                flush()
                block, index = read_question(lines, index, qnum, max_x1)
                # 页码、页脚碎片这类也会撞上题号格式，凑不出完整题目的直接扔掉
                opts = block.get("options") or []
                stem = block.get("stem") or ""
                if len(opts) < 3 and len(re.findall(r"[A-Za-z]", stem)) < 20:
                    continue
                # 选项尾巴上常粘着下一段的 "Questions 5 to 8 are based on …"，
                # 不切下来会变成 D 选项的一部分
                stray = ""
                kept_opts = []
                for opt in block.get("options") or []:
                    hit = re.search(r"\s(Questions?\s+\d+\s*(?:to|and|-|—|–)\s*\d+.*)$", opt)
                    if hit:
                        stray = hit.group(1)
                        opt = opt[: hit.start()].strip()
                    kept_opts.append(opt)
                block["options"] = kept_opts
                blocks.append(block)
                if stray:
                    blocks.append({"t": "intro", "text": re.sub(r"(?<=\d)(?=[A-Za-z]{2,})", " ", stray)})
                continue
            # 36—45 那种只有一句陈述、没有选项的题
            if 30 <= num <= 60:
                flush()
                body = [qnum.group(2)]
                index += 1
                while index < len(lines):
                    nxt = lines[index]
                    if is_block_start(nxt["text"]) or nxt["size"] < 11 or nxt["x"] < 45:
                        break
                    body.append(nxt["text"])
                    index += 1
                blocks.append({"t": "stmt", "num": num, "text": merge(body)})
                continue

        # 词库 A) adolescents … O) vocal，按列排，单独收成一组
        if bank_zone and re.match(r"^[A-O][.)]\s", text) and line["x"] > 100 and len(text) <= 40:
            flush()
            items: list[str] = []
            guard = 0
            while index < len(lines) and guard < 30:
                guard += 1
                nxt = lines[index]
                parts = split_options(nxt["text"])
                if not parts or nxt["x"] <= 100:
                    if items and nxt["x"] > 100 and not is_block_start(nxt["text"]):
                        index += 1  # 长词折行的残片，丢掉不影响
                        continue
                    break
                items.extend(f"{letter}. {body}" for letter, body in parts)
                index += 1
            blocks.append({"t": "bank", "items": sorted(items, key=lambda s: s[0])})
            continue

        if re.match(r"^Passages?\s+(One|Two|Three|Four)$", text, re.I):
            flush()
            blocks.append({"t": "subhead", "text": text})
            index += 1
            continue

        # 文章大标题，字号跟正文一样但明显居中缩进
        # 双栏页里的正文也会缩进并且栏宽不到页面 92%，靠"这一行是否被拆成两栏"排除掉
        if (
            size >= 11.4
            and line.get("ncol", 1) == 1
            and line["x"] > 90
            and line["x1"] < max_x1 * 0.92
            and len(text) <= 160
            and re.search(r"[A-Za-z\u4e00-\u9fff]{3}", text)
            and not text[:1].islower()
            and not re.fullmatch(r"\(?\d+\s*minutes?\)?", text)
        ):
            flush()
            blocks.append({"t": "headline", "text": text})
            index += 1
            continue

        # Section B 的段落用 A. B. C. 打头，段首贴左
        if re.match(r"^[A-P][.)]\s\S", text) and line["x"] <= 45:
            flush()
            body = [text]
            index += 1
            while index < len(lines):
                nxt = lines[index]
                if is_block_start(nxt["text"]) or re.match(r"^[A-P][.)]\s", nxt["text"]):
                    break
                if nxt["size"] < 11:
                    break
                body.append(nxt["text"])
                index += 1
            blocks.append({"t": "para", "text": merge(body), "letter": text[0]})
            continue

        if re.fullmatch(r"[\d\s]{1,8}", text) and not QNUM.match(text):
            index += 1
            continue

        # 首行缩进，说明进了新的一段
        # 上一行排满了才可能是段落中间，否则这一行的缩进就是新段开头
        if (
            paragraph is not None
            and line["x"] >= 50
            and size >= 11.4
            and lines[index - 1]["x1"] < max_x1 * 0.93
        ):
            flush()

        if paragraph is None:
            paragraph = []
        paragraph.append(text)
        index += 1

    flush()
    blocks = move_part1_front(blocks)
    return {"title": title, "blocks": blocks}


PART_I = re.compile(r"^Part\s*(?:I|Ⅰ)\s+[A-Za-z]")


def move_part1_front(blocks: list[dict]) -> list[dict]:
    """老卷子把作文页扫在了最后，Part I 排在 Part IV 后面；按参考卷的次序挪回卷首。"""
    heads: list[dict] = []
    rest = blocks
    if rest and rest[0]["t"] == "title":
        heads = [rest[0]]
        rest = rest[1:]
    idx = next(
        (i for i, b in enumerate(rest) if b["t"] == "part" and PART_I.match(b["text"])),
        None,
    )
    if idx is None or idx < len(rest) // 2:
        return blocks
    tail = rest[idx:]
    # 后面若还跟着别的 Part，说明不是倒置，别动
    if any(b["t"] == "part" for b in tail[1:]):
        return blocks
    return heads + tail + rest[:idx]


def is_block_start(text: str) -> bool:
    return bool(
        PART.match(text)
        or SECTION.match(text)
        or text.startswith("Directions:")
        or QINTRO.match(text)
        or re.match(r"^\d{1,2}\s*[.、．,，]\s*", text)
    )


def split_options(text: str) -> list[tuple[str, str]]:
    """一行里可能并排两个选项（A 和 C 常落在同一行），按标记切开。"""
    # 前面只要求不是字母数字：OCR 卷常把 "…methodology.C)" 粘成一串，中间没有空格
    marks = list(re.finditer(r"(?<![A-Za-z0-9])([A-O])\s*[.)]{1,2}\s*", text))
    if not marks:
        return []
    out: list[tuple[str, str]] = []
    for i, mark in enumerate(marks):
        end = marks[i + 1].start(1) if i + 1 < len(marks) else len(text)
        out.append((mark.group(1), text[mark.end() : end].strip()))
    return out


def options_follow(lines: list[dict], index: int, span: int = 3) -> bool:
    """题干下紧跟 A. 开头才算选择题。36—45 那种纯陈述句后面直接是下一题号。"""
    for k in range(index + 1, min(index + 1 + span, len(lines))):
        text = lines[k]["text"]
        if re.match(r"^[A-D][.)]\s*\S", text):
            return True
        if is_block_start(text):
            return False
    return False


def read_question(lines: list[dict], index: int, qnum: re.Match, max_x1: float = 561.0) -> tuple[dict, int]:
    num = int(qnum.group(1))
    rest = qnum.group(2).strip()
    found: dict[str, str] = {}
    stem = ""

    first = split_options(rest)
    if first:
        for letter, body in first:
            found[letter] = body
    else:
        stem = rest

    index += 1
    while index < len(lines):
        nxt = lines[index]
        text = nxt["text"]

        # 走到下一题就收手
        other = re.match(r"^(\d{1,2})\s*[.、．,，]\s*", text)
        if other and int(other.group(1)) != num:
            break
        if is_block_start(text) and not re.match(r"^[A-O]\.\s", text):
            break

        parts = split_options(text)
        if parts:
            added = False
            for letter, body in parts:
                if letter in found:
                    continue
                found[letter] = body
                added = True
            if not added:
                break
            index += 1
            continue

        # 题干自己也会折行（"…lowering the climate cost" / "through its dietary guidelines?"），
        # 不接住的话后面 A) B) 会掉出去变成孤立的段落
        if not found and nxt["x"] > 40 and nxt["size"] >= 11 and len(stem) < 400 \
                and not re.match(r"^[A-O][.)]\s*\S", text):
            stem = f"{stem} {text}".strip()
            index += 1
            continue

        # 选项文字折行，接到已收到的最后一个字母后面。
        # 用长度上限兜底，免得某个选项把后面整篇都吸进来。
        if found and nxt["x"] > 40 and nxt["size"] >= 11 and len(found[max(found)]) < 220:
            last = max(found)
            found[last] = f"{found[last]} {text}".strip()
            index += 1
            continue
        break

    options = [f"{letter}. {tidy(found[letter])}" for letter in sorted(found)]
    return {"t": "question", "num": num, "stem": tidy(stem), "options": options}, index


def tidy(text: str) -> str:
    """A3 那种宽页，页码会跟选项挤在同一行，尾巴上挂一串 "5."，切掉。"""
    text = re.sub(r"\.\s*\d{1,3}\.$", ".", text.strip())
    return text.strip()


def merge(parts: list[str]) -> str:
    """把折行拼成一段，处理行尾连字符。"""
    out = ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if not out:
            out = part
        elif out.endswith("-"):
            out = out + part
        else:
            out = out + " " + part
    return out


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    target = sys.argv[1] if len(sys.argv) > 1 else "cet6/2025-12/01"
    pdf = root / "data" / target / "read.pdf"
    result = parse_pdf(pdf)
    result["id"] = target
    # OCR 卷的标题往往被识别成 "2022121" 这种数字串，退回索引里的正式标题
    if not re.search(r"[A-Za-z\u4e00-\u9fff]{3}", result.get("title", "")):
        index_file = root / "data" / "papers.json"
        if index_file.exists():
            index = json.loads(index_file.read_text(encoding="utf-8"))
            for paper in index.get("papers", []):
                if paper.get("id") == target:
                    result["title"] = paper.get("title") or result["title"]
                    break
        # 原卷标题被 OCR 认成数字串时，它已经作为一个普通段落进了 blocks，这里换掉
        garbage = re.compile(r"^[\d\s\W]{0,12}$")
        while result["blocks"] and result["blocks"][0]["t"] == "para" and garbage.match(result["blocks"][0]["text"]):
            result["blocks"].pop(0)
        if not result["blocks"] or result["blocks"][0]["t"] != "title":
            result["blocks"].insert(0, {"t": "title", "text": result["title"]})
    out = root / ".cache" / "typeset" / (target.replace("/", "_") + ".json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"标题 {result['title']}")
    print(f"块数 {len(result['blocks'])}  -> {out}")


if __name__ == "__main__":
    main()
