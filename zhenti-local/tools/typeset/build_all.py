"""批量重排 data/cet6 下所有套卷。

逐套起子进程跑，一套超时或报错都不影响后面的。跑完会打印一份覆盖清单。
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools" / "typeset"
PY = sys.executable


def run(args: list[str], timeout: int) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            [PY, "-u", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, "timeout"
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
        return False, " | ".join(tail)
    return True, (proc.stdout or "").strip().splitlines()[-1] if proc.stdout.strip() else ""


def main() -> None:
    only = sys.argv[1] if len(sys.argv) > 1 else ""
    papers = sorted((ROOT / "data" / "cet6").glob("*/*/read.pdf"))
    if only:
        papers = [p for p in papers if only in p.as_posix()]
    print(f"共 {len(papers)} 套", flush=True)

    ok: list[tuple[str, str]] = []
    failed: list[tuple[str, str]] = []
    started = time.time()

    for i, pdf in enumerate(papers, 1):
        pid = pdf.parent.relative_to(ROOT / "data").as_posix()
        t0 = time.time()
        good, msg = run(["tools/typeset/parse_paper.py", pid], timeout=150)
        if not good:
            failed.append((pid, f"parse {msg}"))
            print(f"[{i:>2}/{len(papers)}] FAIL parse {pid}  {msg}", flush=True)
            continue
        good, msg = run(["tools/typeset/render_paper.py", pid], timeout=240)
        if not good:
            failed.append((pid, f"render {msg}"))
            print(f"[{i:>2}/{len(papers)}] FAIL render {pid}  {msg}", flush=True)
            continue
        ok.append((pid, msg))
        print(f"[{i:>2}/{len(papers)}] {pid:18s} {time.time()-t0:5.1f}s  {msg}", flush=True)

    print("=" * 60, flush=True)
    print(f"成功 {len(ok)} 套，失败 {len(failed)} 套，用时 {(time.time()-started)/60:.1f} 分钟", flush=True)
    for pid, why in failed:
        print(f"  失败 {pid}  {why}", flush=True)


if __name__ == "__main__":
    main()
