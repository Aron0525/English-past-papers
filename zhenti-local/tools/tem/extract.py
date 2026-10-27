#!/usr/bin/env python
"""把归档的真题网页抽成纯正文（供 TEM4/TEM8 转 PDF 用）。

不依赖原站 CSS，只做一件事：在 HTML 里找到真正放正文的那块 DOM，
去掉导航 / 广告 / 评论 / 分享，保留段落换行与选项缩进。

用法：
    python tools/tem/extract.py --probe tem4_archive/collected/2016/TEM4_2016_paper_yj.html
    python tools/tem/extract.py --text  <file.html> --out x.txt
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup

DROP_TAGS = [
    "script", "style", "noscript", "iframe", "nav", "header", "footer", "aside",
    "form", "button", "select", "input", "svg", "video", "audio",
]

# 常见的正文容器，按可信度从高到低
CONTENT_SELECTORS = [
    "article",
    ".article-content", ".article_content", ".articleCon", ".artContent",
    ".content", "#content", ".main-content", ".post-content", ".entry-content",
    ".detail-content", ".news-content", ".TRS_Editor", ".text", ".art_context",
    ".article", ".detail", ".newsContent", "#artibody", ".article-body",
]

# 一行里出现这些就已经不是正文了
NOISE_PATTERNS = [
    r"^首页\s*$", r"^登录$", r"^注册$", r"^分享到", r"^扫一扫", r"^广告$",
    r"^上一篇", r"^下一篇", r"^返回列表", r"^相关阅读", r"^热门推荐",
    r"copyright", r"版权", r"免责声明", r"^责任编辑", r"^编辑：",
    r"^微信", r"^微博", r"^QQ空间", r"^复制链接",
]

MIN_BLOCK = 200        # 候选块的正文起码这么长才认
MIN_LINE = 2


def load(path: Path) -> BeautifulSoup:
    raw = path.read_bytes()
    for enc in ("utf-8", "gb18030", "gbk"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", "ignore")
    # lxml 快但对坏 HTML 挑剔，失败就退回内置解析器
    try:
        return BeautifulSoup(text, "lxml")
    except Exception:
        return BeautifulSoup(text, "html.parser")


def prune(soup: BeautifulSoup) -> None:
    for tag in soup(DROP_TAGS):
        tag.decompose()
    # 明显是导航/页脚/侧栏的 div
    for tag in soup.find_all(attrs={"class": re.compile(r"(nav|menu|footer|header|sidebar|share|comment|related|advert|banner|breadcrumb|copyright)", re.I)}):
        tag.decompose()
    for tag in soup.find_all(attrs={"id": re.compile(r"(nav|menu|footer|header|sidebar|share|comment|related|banner)", re.I)}):
        tag.decompose()


def is_noise(line: str) -> bool:
    if len(line) < MIN_LINE:
        return True
    return any(re.search(p, line, re.I) for p in NOISE_PATTERNS)


def block_text(node) -> str:
    """按块级元素断行，行内元素原样拼接。"""
    lines: list[str] = []
    for el in node.find_all(["p", "div", "li", "h1", "h2", "h3", "h4", "h5", "tr", "br", "table"], recursive=True):
        if el.name == "br":
            lines.append("")
            continue
        # 只取最内层的块，避免父 div 把整段重复一遍
        if el.find(["p", "div", "li", "tr"]):
            continue
        chunk = el.get_text(" ", strip=True)
        chunk = re.sub(r"[ \t\u00a0]+", " ", chunk)
        if chunk and not is_noise(chunk):
            lines.append(chunk)
    if not lines:
        text = node.get_text("\n", strip=True)
        lines = [re.sub(r"[ \t\u00a0]+", " ", line) for line in text.split("\n") if not is_noise(line)]
    return "\n".join(lines)


def best_block(soup: BeautifulSoup) -> tuple[object, str, str]:
    """返回 (节点, 正文, 用的是哪个选择器)"""
    body = soup.body or soup
    candidates = []
    for selector in CONTENT_SELECTORS:
        for node in body.select(selector):
            text = block_text(node)
            if len(text) >= MIN_BLOCK:
                candidates.append((len(text), node, selector))
    if candidates:
        candidates.sort(key=lambda item: -item[0])
        length, node, selector = candidates[0]
        return node, block_text(node), selector
    text = block_text(body)
    return body, text, "body"


def tidy(text: str) -> str:
    # 合并被网页硬折的中文行：上一行不以句末标点结尾、下一行是中文开头
    lines = text.split("\n")
    out: list[str] = []
    for line in lines:
        line = line.strip()
        if not line:
            if out and out[-1] != "":
                out.append("")
            continue
        if out and out[-1] and not re.search(r"[.。!?！？:：;；)）\]】”\"']$", out[-1]) \
           and re.match(r"^[\u4e00-\u9fff]", line) and re.search(r"[\u4e00-\u9fff]$", out[-1]):
            out[-1] = out[-1] + line
            continue
        out.append(line)
    return "\n".join(out).strip()


# 题型标题、选项、题号：这些必须独占一行，不能被合并
KEEP_ALONE = re.compile(
    r"^(PART\b|SECTION\b|Section\b|Part\b|[A-D][\).、]|\d{1,3}[\).、]|"
    r"[ⅠⅡⅢⅣⅤⅥⅦ]|[①②③④⑤⑥⑦⑧⑨⑩]|【|\[[A-Z])"
)


def unwrap(text: str) -> str:
    """网页把每个短语塞进独立 <p>，这里把同一段里的碎片接回去。

    判断只看标点：上一行没有句末标点就说明这句没说完，直接接上；
    上一行写完了（带句末标点）而下一行以小写开头，也是被硬折的同一句。
    题型标题、题号、选项一律不参与合并。
    """
    out: list[str] = []
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            if out and out[-1] != "":
                out.append("")
            continue
        prev = out[-1] if out else ""
        if prev and not KEEP_ALONE.match(line):
            ends_sentence = re.search(r"[.。!?！？:：;；]\"?'?$", prev)
            glue = f"{prev} {line}" if prev[-1].isascii() and line[0].isascii() else prev + line
            if not ends_sentence:
                out[-1] = glue
                continue
            if re.match(r"^[a-z,;]", line):
                out[-1] = glue
                continue
        out.append(line)
    return "\n".join(out).strip()


# 正文真正的开头：试卷标题或第一个 PART（网页里大小写不统一：PART I / Part I / Part Ⅰ）
BODY_START = re.compile(
    r"(TEST\s+FOR\s+ENGLISH\s+MAJORS|TEST\s+FOR\s+ENGLISH|PART\s+(?:I|1|Ⅰ)\b|Part\s+(?:I|1|Ⅰ)\b)",
    re.I,
)
BODY_END = re.compile(
    r"(【编辑|（责任编辑|\(责任编辑|相关阅读|相关文章|相关内容|阅读排行榜|网友热搜|热门推荐|"
    r"上一篇：|下一篇：|声明：|免责声明|转载注明)",
)


def trim_body(text: str) -> str:
    """砍掉站点页头页脚，只留试卷正文。"""
    lines = text.split("\n")
    start = 0
    for i, line in enumerate(lines[:60]):
        if BODY_START.search(line):
            start = i
            # 命中行前面往往还挂着「发布时间 / 发布人 / 字号」，从这里切掉
            lines[i] = line[BODY_START.search(line).start():]
            break
    end = len(lines)
    for i in range(start, len(lines)):
        if BODY_END.search(lines[i]):
            end = i
            break
    return "\n".join(lines[start:end]).strip()


def extract(path: Path) -> tuple[str, str]:
    soup = load(path)
    prune(soup)
    node, text, selector = best_block(soup)
    # 顺序有讲究：先合并碎片行，站点头部（发布时间 / TEST FOR / ENGLISH MAJORS 分几行）才会并成一行，
    # 之后才认得出正文要从哪里开始。
    return trim_body(unwrap(tidy(text))), selector


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", nargs="*", help="只探测：打印每份文件的正文长度与前几行")
    ap.add_argument("--text", help="要抽取的 HTML")
    ap.add_argument("--out", help="输出 txt 路径")
    args = ap.parse_args()

    if args.probe:
        for pattern in args.probe:
            for path in sorted(Path(".").glob(pattern)):
                try:
                    text, selector = extract(path)
                except Exception as error:  # noqa: BLE001
                    print(f"{path}  解析失败 {error}")
                    continue
                head = text.replace("\n", " ⏎ ")[:160]
                print(f"{path.as_posix()}  [{selector}] {len(text)} 字\n    {head}\n")
        return 0

    if not args.text:
        ap.error("要么 --probe 要么 --text")
    path = Path(args.text)
    text, selector = extract(path)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"{path.name} -> {args.out}  [{selector}] {len(text)} 字")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
