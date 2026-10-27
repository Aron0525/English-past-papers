"""结构体检：按题号核对每套卷子重排版后题目是否齐全。"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from parse_paper import parse_pdf

ROOT = Path(__file__).resolve().parents[2]


def audit(pid: str) -> None:
    data = parse_pdf(ROOT / "data" / pid / "read.pdf")
    blocks = data["blocks"]
    kinds = Counter(b["t"] for b in blocks)
    qs = [b for b in blocks if b["t"] in ("question", "stmt")]
    nums = [b["num"] for b in qs]
    dup = [n for n, c in Counter(nums).items() if c > 1]
    missing = [n for n in range(1, 56) if n not in nums]
    no_opt = [b["num"] for b in qs if b["t"] == "question" and len(b.get("options") or []) != 4]
    bank = sum(len(b.get("items") or []) for b in blocks if b["t"] == "bank")
    print(f"{pid:16s} blocks={len(blocks):4d} q={len(nums):3d} 缺={len(missing):2d} 重复={dup} "
          f"选项异常={no_opt} bank={bank} 标题={kinds.get('headline', 0)}")
    if missing:
        print(f"    缺题号 {missing}")
    _ = kinds


if __name__ == "__main__":
    targets = sys.argv[1:]
    if not targets:
        targets = ["cet6/2016-06/02", "cet6/2016-06/03", "cet6/2016-12/01", "cet6/2016-12/02",
                   "cet6/2016-12/03", "cet6/2017-12/01", "cet6/2017-12/02", "cet6/2017-12/03",
                   "cet6/2019-06/01", "cet6/2019-06/02", "cet6/2019-06/03",
                   "cet6/2020-12/01", "cet6/2020-12/02"]
    for t in targets:
        try:
            audit(t)
        except Exception as exc:  # noqa: BLE001
            print(f"{t:16s} ERR {exc}")
