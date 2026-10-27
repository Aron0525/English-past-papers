#!/usr/bin/env python
"""把专四（tem4_archive）与专八（tem8）的网页归档灌进工作台。

这两门的素材不是 PDF，是当年从各站点存下来的网页（有的年份有真 PDF）。
处理方式：
    试卷：有 PDF 就用 PDF；只有网页的，抽正文 → 重排 → 无头 Edge 打印成带文本层的 PDF
    解析：答案解析网页同样打印成 analysis.pdf（点「查看解析」能读）
    听力：归档里的 mp3 原样放进 listen.mp3

专八没有原卷（公开渠道只拿到答案/解析），只挂 analysis.pdf，read.pdf 缺。

用法
    python tools/tem/ingest-tem.py --exam tem4 --dry
    python tools/tem/ingest-tem.py --exam all
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import extract as EX  # noqa: E402
import build_paper_pdf as BP  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
REPO = ROOT.parent
DATA = ROOT / "data"
CACHE = ROOT / ".cache" / "tem"

# 每年用哪几个文件。列表按优先级排：前面抽出来不够长就试下一个。
TEM4_SRC = REPO / "tem4_archive" / "collected"
TEM8_SRC = REPO / "tem8"

# 一份卷子正文少于这个字数就当没抽到（一套完整卷子正文都在 2 万字以上，
# 但回忆版 / 部分卷会短很多，所以门槛压得比较低，靠 quality 字段如实标注）
MIN_PAPER_CHARS = 3000
MIN_ANALYSIS_CHARS = 800

TEM4 = {
    2011: {"date": "2011-04-16", "quality": "完整",
           "paper": ["TEM4_2011_paper_yj.html"],
           "analysis": ["TEM4_2011_answer_yj.html", "TEM4_2011_answer_koolearn.html"]},
    2012: {"date": "2012-04-21", "quality": "完整",
           "paper": ["TEM4_2012_paper_yj.html"],
           "analysis": ["TEM4_2012_answer_yj.html", "TEM4_2012_answer_koolearn.html"]},
    2013: {"date": "2013-04-20", "quality": "完整",
           "paper": ["TEM4_2013_paper_yj.html"],
           "analysis": ["TEM4_2013_answer_yj.html", "TEM4_2013_answer_koolearn.html"]},
    2014: {"date": "2014-04-19", "quality": "完整",
           "paper": ["TEM4_2014_paper_yj.html"],
           "analysis": ["TEM4_2014_answer.html"]},
    2015: {"date": "2015-04-18", "quality": "部分（只拿到听写与听力部分）",
           "paper": ["TEM4_2015_paper_koolearn.html"],
           "analysis": ["TEM4_2015_answer.html"]},
    2016: {"date": "2016-04-23", "quality": "完整",
           "paper": ["TEM4_2016_paper_yj.html"],
           "analysis": ["TEM4_2016_answer.html"]},
    2017: {"date": "2017-04-22", "quality": "完整",
           "paper": ["TEM4_2017_paper_yingyushijie.html"],
           "analysis": ["TEM4_2017_paper_answers_koolearn.html"]},
    2018: {"date": "2018-04-21", "quality": "完整",
           "paper": ["TEM4_2018_paper_yingyushijie.txt"],
           "analysis": ["TEM4_2018_paper_answers_hujiang.html", "TEM4_2018_answer_koolearn.html"]},
    2019: {"date": "2019-04-20", "quality": "完整",
           "paper": ["TEM4_2019_paper_yingyushijie.txt"],
           "analysis": ["TEM4_2019_answer_xdf.html"]},
    2021: {"date": "2021-06-19", "quality": "完整",
           "paper": ["TEM4_2021_paper_nju.html"],
           "analysis": ["TEM4_2021_answer_huayan_sohu.html"]},
    2022: {"date": "2022-10-30", "quality": "完整",
           "paper": ["TEM4_2022_paper_bv.pdf"],
           "analysis": ["TEM4_2022_answer_360intedu.html"],
           "audio": ["TEM4_2022_listening_bv.mp3"]},
    2023: {"date": "2023-06-18", "quality": "完整",
           "paper": ["TEM4_2023_paper_bv.pdf"],
           "analysis": [],
           "audio": ["TEM4_2023_listening_bv.mp3"]},
    2024: {"date": "2024-06-16", "quality": "完整",
           "paper": ["TEM4_2024_paper.pdf", "TEM4_2024_paper_bv.pdf"],
           "analysis": ["TEM4_2024_answer_recall.html"],
           "audio": ["TEM4_2024_listening_bv.mp3"]},
    2025: {"date": "2025-06-15", "quality": "完整",
           "paper": ["TEM4_2025_paper.pdf", "TEM4_2025_paper_bv.pdf"],
           "analysis": [],
           "audio": ["TEM4_2025_listening_bv.mp3"]},
    2026: {"date": "2026-06-14", "quality": "回忆版（华研/有道整理，非官方原卷）",
           "paper": ["TEM4_2026_paper_recall.html"],
           "analysis": ["TEM4_2026_language_usage_answers.html"]},
}

TEM8 = {
    2011: {"date": "2011-03-19", "analysis_priority": ["答案_koolearn", "答案_hxen", "答案_book118"]},
    2012: {"date": "2012-03-17", "analysis_priority": ["答案_koolearn", "答案_沪江", "答案_hxen"]},
    2013: {"date": "2013-03-23", "analysis_priority": ["答案_koolearn", "答案_enfamily", "答案_圣才"]},
    2014: {"date": "2014-03-22", "analysis_priority": ["答案_新东方详细", "答案_沪江", "答案_英语世界"], "audio": ["2014_听力_和谐英语.mp3"]},
    2015: {"date": "2015-03-21", "analysis_priority": ["答案_新东方koolearn", "答案_英语世界"], "audio": ["2015_听力_和谐英语.mp3"]},
    2016: {"date": "2016-03-19", "analysis_priority": []},
    2017: {"date": "2017-03-18", "analysis_priority": []},
    2018: {"date": "2018-03-17", "analysis_priority": []},
    2019: {"date": "2019-03-23", "analysis_priority": []},
    2021: {"date": "2021-04-24", "analysis_priority": []},
    2022: {"date": "2022-11-19", "analysis_priority": [], "paper": ["2022_试卷.pdf"]},
    2023: {"date": "2023-04-22", "analysis_priority": []},
    2024: {"date": "2024-04-13", "analysis_priority": ["深度解析_新东方", "答案_沪江"], "paper": ["2024_试卷.pdf"]},
    2025: {"date": "2025-03-29", "analysis_priority": [], "paper": ["2025_试卷.pdf"], "analysis_md": ["2025_答案翻译作文听力_英语吖.md"]},
    2026: {"date": "2026-03-21", "analysis_priority": [], "analysis_md": ["2026_完整答案_回忆版.md"]},
}


def period_of(date: str) -> str:
    return date[:7]


def group_label(date: str) -> str:
    year, month = date[:4], int(date[5:7])
    if month == 6:
        return f"{year}年 - 上半年"
    if month == 12:
        return f"{year}年 - 下半年"
    if month in (3, 4):
        return f"{year}年 - 春季"
    return f"{year}年 - {month}月"


def title_of(exam_name: str, year: int, quality: str) -> str:
    tag = ""
    if "回忆版" in quality:
        tag = "（回忆版）"
    elif "部分" in quality:
        tag = "（部分）"
    return f"{year}年{exam_name}真题{tag}"


# 一套卷子该有的题型，用来判断归档页到底全不全
PART_KEYS = [
    ("dictation", r"DICTATION"),
    ("listening", r"LISTENING\s+COMPREHENSION|LISTENING"),
    ("language", r"LANGUAGE\s+USAGE|GRAMMAR\s+AND\s+VOCABULARY|GRAMMAR"),
    ("cloze", r"CLOZE"),
    ("reading", r"READING\s+COMPREHENSION|READING"),
    ("translation", r"TRANSLATION"),
    ("writing", r"WRITING|COMPOSITION"),
]


def detect_parts(text: str) -> list[str]:
    hit = []
    for key, pattern in PART_KEYS:
        if re.search(pattern, text, re.I):
            hit.append(key)
    return hit


PART_CN = {"dictation": "听写", "listening": "听力", "language": "语言知识", "cloze": "完形",
           "reading": "阅读", "translation": "翻译", "writing": "写作"}


def quality_from_text(text: str, fallback: str, exam: str = "tem4") -> str:
    """按正文里实际出现的题型给整套卷子定性，别照抄配置里的乐观说法。

    专四没有翻译题（那是专八的题型），所以翻译不算专四的固定要求。
    """
    parts = set(detect_parts(text))
    core = {"listening", "reading", "writing"} if exam == "tem4" \
        else {"listening", "reading", "translation", "writing"}
    optional = ("dictation", "language", "cloze") if exam == "tem4" else ("cloze",)
    missing = [k for k in core if k not in parts]
    if "listening" in missing or "reading" in missing:
        return "不全（缺听说读写主干，只能当参考资料）"
    missing += [k for k in optional if k not in parts]
    if not missing:
        return "完整"
    return "部分（缺" + "、".join(PART_CN[m] for m in missing) + "）"


def text_of(path: Path) -> str:
    if path.suffix.lower() in (".txt", ".md"):
        raw = path.read_text(encoding="utf-8", errors="ignore")
        # markdown 的 # 标题符号在 PDF 里没意义
        raw = re.sub(r"^#{1,6}\s*", "", raw, flags=re.M)
        return EX.trim_body(EX.unwrap(EX.tidy(raw)))
    text, _ = EX.extract(path)
    return text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exam", choices=["tem4", "tem8", "all"], default="all")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    CACHE.mkdir(parents=True, exist_ok=True)
    index_path = DATA / "papers.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index.setdefault("groupOrder", ["cet6", "cet4", "tem4", "tem8"])
    by_id = {p["id"]: p for p in index["papers"]}

    report: list[dict] = []

    def do(exam: str, exam_name: str, years: dict, src_root: Path):
        if not any(e["id"] == exam for e in index["exams"]):
            index["exams"].append({
                "id": exam, "name": exam_name,
                "short": "专四" if exam == "tem4" else "专八",
                "source": str(src_root),
            })
        for year in sorted(years):
            info = years[year]
            # 专八没有原卷，只有答案/解析网页，统一按「仅解析」标注
            info.setdefault("quality", "仅答案解析（无原卷）")
            year_dir = src_root / str(year)
            period = period_of(info["date"])
            set_id = "01"
            pid = f"{exam}/{period}/{set_id}"
            target = DATA / exam / period / set_id

            picked = {"paper": None, "analysis": None, "audio": None}

            # ---- 试卷 ----
            if info.get("paper"):
                for name in info["paper"]:
                    path = year_dir / name
                    if not path.exists():
                        continue
                    if path.suffix.lower() == ".pdf":
                        picked["paper"] = ("pdf", path, "")
                        break
                    text = text_of(path)
                    if len(text) >= MIN_PAPER_CHARS:
                        picked["paper"] = ("text", path, text)
                        break
                    else:
                        print(f"  跳过 {path.name}：正文只有 {len(text)} 字")

            # ---- 解析 ----
            analysis_candidates: list[Path] = []
            for name in info.get("analysis_md") or []:
                path = year_dir / name
                if path.exists():
                    analysis_candidates.append(path)
            for name in info.get("analysis") or []:
                path = year_dir / name
                if path.exists():
                    analysis_candidates.append(path)
            if not analysis_candidates and year_dir.exists():
                # 专八：按关键词挑解析页
                for key in info.get("analysis_priority") or []:
                    hits = sorted(year_dir.glob(f"*{key}*.html"))
                    analysis_candidates.extend(hits[:1])
                if not analysis_candidates:
                    # 文件名里带 paper/试卷的是正文不是答案，别拿去当解析
                    analysis_candidates = sorted(
                        p for p in year_dir.glob("*.html")
                        if not re.search(r"(paper|试卷|正文)", p.name, re.I)
                    )

            # 给候选打分：正文越长越好，营销腔越重越扣分
            # （「公众号/网课」是课程广告页；「已阅读5页还剩N页」是文库付费墙的截断预览，都当垃圾）
            # 这道闸只拦 glob 兜底捞进来的页；配置里点名的答案页是人工挑过的，不走这套
            SPAM = re.compile(
                r"公众号|网课|全程班|水平测试|领取|二维码|请加|免费获取|网盘|课程咨询"
                r"|已阅读\s*\d+\s*页|继续免费阅读|下载本文档|文档简介"
            )

            best = None
            if analysis_candidates:
                for path in analysis_candidates:
                    if path.suffix.lower() == ".pdf":
                        best = ("pdf", path, "")
                        break
                    text = text_of(path)
                    if best is None or len(text) > len(best[2]):
                        best = ("text", path, text)
                if best and best[0] == "text" and len(best[2]) < MIN_ANALYSIS_CHARS:
                    print(f"  跳过解析 {best[1].name}：只有 {len(best[2])} 字")
                    best = None
            elif year_dir.exists():
                scored: list[tuple[int, str, Path]] = []
                for path in sorted(year_dir.glob("*.html")):
                    if re.search(r"(paper|试卷|正文)", path.name, re.I):
                        continue
                    text = text_of(path)
                    spam = len(SPAM.findall(text))
                    if len(text) >= 600 and spam <= 3:
                        scored.append((len(text) - 300 * spam, text, path))
                scored.sort(key=lambda item: -item[0])
                if scored:
                    top = scored[:3]
                    if len(top) == 1:
                        best = ("text", top[0][2], top[0][1])
                    else:
                        # 把得分最高的几页拼成一份解析，各页用文件名做小标题
                        merged = "\n\n".join(f"【{item[2].stem}】\n\n{item[1]}" for item in top)
                        best = ("text", top[0][2], merged)
            if best:
                picked["analysis"] = best

            # ---- 听力 ----
            if info.get("audio"):
                for name in info["audio"]:
                    path = year_dir / name
                    if path.exists():
                        picked["audio"] = path
                        break

            flags = " ".join([
                f"卷{'✓' if picked['paper'] else '✗'}",
                f"解析{'✓' if picked['analysis'] else '✗'}",
                f"听力{'✓' if picked['audio'] else '✗'}",
            ])
            # 定性以抽出来的正文为准：配置写的「完整」常常乐观了
            quality = info["quality"]
            if picked["paper"] and picked["paper"][0] == "text":
                quality = quality_from_text(picked["paper"][2], quality, exam)
                if "回忆版" in info["quality"]:
                    quality = f"回忆版 · {quality}"
            elif picked["paper"]:
                quality = info["quality"] if "回忆版" in info["quality"] else "完整（原卷 PDF）"
            elif not picked["paper"]:
                quality = "仅答案解析（无原卷）"
            print(f"  {pid}  {flags}  [{quality}]")
            report.append({
                "id": pid,
                "paper": picked["paper"][1].name if picked["paper"] else None,
                "analysis": picked["analysis"][1].name if picked["analysis"] else None,
                "audio": picked["audio"].name if picked["audio"] else None,
                "quality": quality,
            })

            if args.dry:
                continue
            if not picked["paper"] and not picked["analysis"]:
                print(f"    这套什么也没有，跳过")
                continue

            target.mkdir(parents=True, exist_ok=True)
            files: dict = {}

            def write_pdf(kind: str, entry, title: str, meta: str) -> None:
                mode, path, text = entry
                dest = target / ("read.pdf" if kind == "pdf" else "analysis.pdf")
                if mode == "pdf":
                    shutil.copyfile(path, dest)
                    files[kind] = {"name": dest.name, "bytes": dest.stat().st_size, "origin": str(path),
                                   "originName": path.name, "rendered": False}
                    return
                tmp = CACHE / f"{exam}-{period}-{kind}.txt"
                tmp.write_text(text, encoding="utf-8")
                argv = ["build_paper_pdf.py", "--text", str(tmp), "--out", str(dest),
                        "--title", title, "--meta", meta]
                old = sys.argv
                sys.argv = argv
                try:
                    BP.main()
                except SystemExit as exc:
                    # build_paper_pdf 用 SystemExit 报错，别让它把整个导入带崩
                    print(f"    生成 PDF 失败（{dest.name}）：{exc}")
                    if dest.exists():
                        dest.unlink()
                    return
                finally:
                    sys.argv = old
                files[kind] = {"name": dest.name, "bytes": dest.stat().st_size, "origin": str(path),
                               "originName": path.name, "rendered": True}

            if picked["paper"]:
                meta_line = f"来源：{picked['paper'][1].parent.parent.name} 归档 · {picked['paper'][1].name} · {info['quality']}"
                write_pdf("pdf", picked["paper"], title_of(exam_name, year, quality), meta_line)
            if picked["analysis"]:
                write_pdf("analysis", picked["analysis"], f"{title_of(exam_name, year, info['quality'])} · 答案解析",
                          f"来源：{picked['analysis'][1].parent.name} 归档 · {picked['analysis'][1].name}")
            if picked["audio"]:
                dest = target / "listen.mp3"
                shutil.copyfile(picked["audio"], dest)
                files["audio"] = {"name": "listen.mp3", "bytes": dest.stat().st_size,
                                  "origin": str(picked["audio"]), "originName": picked["audio"].name}

            meta = {
                "id": pid, "exam": exam, "period": period, "set": set_id,
                "title": title_of(exam_name, year, quality),
                "examDate": info["date"],
                "quality": quality,
                "source": str(year_dir),
                "files": files,
                "capabilities": {
                    "answers": (target / "answers.json").exists(),
                    "analysis": "analysis" in files,
                    "audio": "audio" in files,
                    "listeningText": False,
                    "sentenceTranslation": False,
                },
                "note": (
                    ("解析由网页正文重排生成" if not picked["paper"] else "正文由网页重排，排版与原卷不完全一致")
                    + "；文字层可选中、可查词。"
                    if any(f.get("rendered") for f in files.values()) else ""
                ),
                "ingestedFrom": str(src_root),
                "ingestedAt": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
            }
            (target / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            record = {
                "id": pid, "exam": exam, "period": period, "set": set_id,
                "title": meta["title"], "group": f"{year}年",
                "groupLabel": group_label(info["date"]),
                "latest": year == max(years),
                "source": str(year_dir),
                "quality": quality,
                "files": {k: {"name": v["name"], "bytes": v["bytes"]} for k, v in files.items()},
                "localOrigin": True,
            }
            if pid in by_id:
                by_id[pid].update(record)
            else:
                index["papers"].append(record)

    if args.exam in ("tem4", "all"):
        print("TEM-4")
        do("tem4", "英语专业四级", TEM4, TEM4_SRC)
    if args.exam in ("tem8", "all"):
        print("TEM-8")
        do("tem8", "英语专业八级", TEM8, TEM8_SRC)

    if args.dry:
        print("\n--dry 只探测，未写入")
        return 0

    order = index["groupOrder"]
    index["papers"].sort(key=lambda p: (
        order.index(p["exam"]) if p["exam"] in order else 99,
        "".join(chr(0xFFFF - ord(c)) if c.isdigit() else c for c in str(p["period"])),
        str(p["set"]),
    ))
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    counts: dict[str, int] = {}
    for paper in index["papers"]:
        counts[paper["exam"]] = counts.get(paper["exam"], 0) + 1
    print(f"\npapers.json 共 {len(index['papers'])} 套 {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
