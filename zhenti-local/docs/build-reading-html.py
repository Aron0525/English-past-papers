# -*- coding: utf-8 -*-
"""长 Markdown → 单栏阅读页 HTML（零改造版）。

与同目录 md2reading_html.py 的区别（**这是推荐默认用法**）：
  该脚本要求源 md 里手写「## 目录」小节 + 正文 <a id="..."> 锚点对，长文档维护成本高，
  且「## 目录」后必须紧跟 `---` 否则目录抽不到。
  本脚本改为直接消费 python-markdown 的 `md.toc_tokens` 生成侧边栏——
  目录项与正文标题 id **出自同一次渲染**，天然对齐，源 md 零改造。

用法：
  python md2reading_auto.py <input.md> [output.html] [--subtitle "..."] [--title "..."]

依赖：markdown、pygments（pip install markdown pygments）

产出：单文件 HTML，零外部依赖，可离线双击打开。
功能：左侧固定目录（层级缩进 + 当前章节滚动高亮 + 搜索过滤 + 正文命中标题高亮）、
      顶部阅读进度条、窄屏抽屉式侧边栏、深色主题、代码高亮。
"""
import argparse
import json
import pathlib
import re
import sys

import markdown
from pygments.formatters import HtmlFormatter


LIGHT_CSS = """
:root{--bg:#ffffff;--bg-elev:#f6f8fa;--bg-code:#f6f8fa;--border:#e6e8eb;
--border-2:#d0d7de;--text:#1f2328;--text-dim:#57606a;--text-mute:#6e7781;
--accent:#6a1b9a;--accent-2:#2563eb;}
.sb-title{background:linear-gradient(90deg,#6a1b9a,#2563eb 70%);
-webkit-background-clip:text;background-clip:text;color:transparent;}
::selection{background:rgba(106,27,154,.18);}
#progress{background:linear-gradient(90deg,#6a1b9a,#2563eb);}
.nav-item.d1{color:#24292f;}
.nav-item{color:#3d444d;}
#toc .nav-item:not(.active){color:#3d444d;}
#toc .nav-item.d2:not(.active){color:#57606a;}
.nav-item.active{color:#6a1b9a;}
#content h2,#content h3,#content h4{color:#1f2328;}
#content strong{color:#111827;}
#content em{color:#3d444d;}
#content td,#content li,#content p{color:#24292f;}
blockquote{color:#3d444d;background:#f6f8fa;}
thead th,#content table th{background:#eef1f4;color:#1f2328;}
kbd{background:#eef1f4;border-color:#d0d7de;color:#3d444d;box-shadow:none;}
.codehilite,pre,pre code{background:#f6f8fa;color:#1f2328;}
#content code{background:#eef1f4;color:#1f2328;border:1px solid #e6e8eb;}
#q{background:#ffffff;color:#1f2328;border-color:#d0d7de;}
#qcount,.sb-sub,.sb-foot{color:#6e7781;}
#content table{display:table;width:100%;table-layout:auto;}
#content table th:first-child,#content table td:first-child{width:1%;white-space:nowrap;}
#content table td,#content table th{word-break:normal;overflow-wrap:normal;}
#content table code{white-space:nowrap;word-break:keep-all;}
"""


CODE_CSS = "\n/* pygments 浅色配色 */\n" + HtmlFormatter(style="friendly").get_style_defs(".codehilite") + "\n"


def build(src_path: pathlib.Path, out_path: pathlib.Path, subtitle: str, title_override: str):
    text = src_path.read_text(encoding="utf-8")

    md = markdown.Markdown(
        extensions=["toc", "tables", "fenced_code", "codehilite"],
        extension_configs={
            "toc": {"toc_depth": "2-4", "anchorlink": False, "permalink": False},
            "codehilite": {"guess_lang": False, "linenums": False, "css_class": "codehilite"},
        },
    )
    body = md.convert(text)
    tokens = md.toc_tokens

    def flatten(nodes, depth=0, out=None):
        if out is None:
            out = []
        for n in nodes:
            out.append({"id": n["id"], "name": n["name"], "level": n["level"], "depth": depth})
            flatten(n.get("children", []), depth + 1, out)
        return out

    flat = flatten(tokens)
    if not flat:
        print("ERROR: nav items == 0，目录抽取失败（源文档是否没有任何 h2/h3？）", file=sys.stderr)
        return 1

    # ---- 自检：目录里每一项都必须在正文里真实存在；id 不得重复 ----
    body_ids = set(re.findall(r'<h[1-6][^>]*\bid="([^"]+)"', body))
    nav_ids = [t["id"] for t in flat]
    missing = [i for i in nav_ids if i not in body_ids]
    dups = sorted({i for i in nav_ids if nav_ids.count(i) > 1})
    if missing:
        print(f"ERROR: 目录中有 {len(missing)} 项在正文找不到锚点: {missing[:5]}", file=sys.stderr)
        return 1
    if dups:
        print(f"ERROR: 锚点 id 重复: {dups}", file=sys.stderr)
        return 1

    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", body, re.S)
    doc_title = title_override or (re.sub(r"<[^>]+>", "", h1.group(1)).strip() if h1 else src_path.stem)
    if h1:
        body = re.sub(r"<h1[^>]*>.*?</h1>", "", body, count=1, flags=re.S)

    nav_json = json.dumps(flat, ensure_ascii=False)
    html_text = TEMPLATE.replace("__DOC_TITLE__", doc_title) \
                       .replace("__SUBTITLE__", subtitle) \
                       .replace("__NAV_JSON__", nav_json) \
                       .replace("__BODY__", body)

    html_text = html_text.replace("</style>", LIGHT_CSS + CODE_CSS + "</style>", 1)
    out_path.write_text(html_text, encoding="utf-8")
    print(f"nav items: {len(flat)}")
    print(f"正文标题锚点: {len(body_ids)}")
    print(f"输出: {out_path}")
    print(f"大小: {out_path.stat().st_size / 1024:.1f} KB")
    return 0


TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__DOC_TITLE__</title>
<style>
:root {
  --bg:        #0d1117;
  --bg-elev:   #161b22;
  --bg-code:   #10151c;
  --border:    #262d38;
  --border-2:  #30363d;
  --text:      #e6edf3;
  --text-dim:  #8b949e;
  --text-mute: #6e7681;
  --accent:    #58a6ff;
  --accent-2:  #a371f7;
  --sb-w:      316px;
}
* { box-sizing: border-box; }
html, body {
  margin: 0; padding: 0; height: 100%;
  background: var(--bg); color: var(--text);
  font-family: -apple-system, "Segoe UI", "Microsoft YaHei", "PingFang SC", Roboto, sans-serif;
  font-size: 15.5px; line-height: 1.78;
  -webkit-font-smoothing: antialiased;
}
#app { display: flex; height: 100vh; overflow: hidden; }

/* ---------------- 侧边栏 ---------------- */
#sidebar {
  width: var(--sb-w); flex: 0 0 var(--sb-w);
  background: var(--bg-elev); border-right: 1px solid var(--border);
  display: flex; flex-direction: column; overflow: hidden;
  position: relative; z-index: 30;
}
.sb-head { padding: 18px 18px 12px; border-bottom: 1px solid var(--border); }
.sb-title {
  font-size: 15px; font-weight: 700; letter-spacing: .2px; line-height: 1.4;
  background: linear-gradient(90deg, #58a6ff, #a371f7 70%);
  -webkit-background-clip: text; background-clip: text; color: transparent;
}
.sb-sub { font-size: 11.5px; color: var(--text-mute); margin-top: 5px; line-height: 1.5; }
.sb-search { padding: 11px 14px; border-bottom: 1px solid var(--border); }
#q {
  width: 100%; background: var(--bg); border: 1px solid var(--border-2);
  color: var(--text); border-radius: 7px; padding: 7px 10px; font-size: 13px;
  outline: none; transition: border-color .15s, box-shadow .15s; font-family: inherit;
}
#q:focus { border-color: var(--accent); box-shadow: 0 0 0 3px rgba(88,166,255,.14); }
#q::placeholder { color: var(--text-mute); }
#qcount { font-size: 11px; color: var(--text-mute); margin-top: 6px; min-height: 14px; }
#toc { flex: 1; overflow-y: auto; padding: 10px 8px 40px; }
#toc::-webkit-scrollbar, #main::-webkit-scrollbar { width: 9px; }
#toc::-webkit-scrollbar-thumb, #main::-webkit-scrollbar-thumb {
  background: #2b333d; border-radius: 5px; border: 2px solid var(--bg-elev);
}
.nav-item {
  display: block; padding: 5px 10px; border-radius: 6px; cursor: pointer;
  color: var(--text-dim); text-decoration: none; font-size: 13px; line-height: 1.5;
  border-left: 2px solid transparent; margin: 1px 0; transition: background .12s, color .12s;
}
.nav-item:hover { background: rgba(88,166,255,.08); color: var(--text); }
.nav-item.d1 { font-weight: 600; color: #c9d1d9; margin-top: 9px; }
.nav-item.d2 { padding-left: 22px; font-size: 12.5px; }
.nav-item.active {
  background: rgba(88,166,255,.13); color: var(--accent);
  border-left-color: var(--accent); font-weight: 600;
}
.nav-item.hidden { display: none; }
.sb-foot {
  padding: 9px 14px; border-top: 1px solid var(--border);
  font-size: 10.5px; color: var(--text-mute); line-height: 1.6;
}
kbd {
  background: #21262d; border: 1px solid var(--border-2); border-bottom-width: 2px;
  border-radius: 4px; padding: 0 4px; font-size: 10px; font-family: inherit;
}

/* ---------------- 正文 ---------------- */
#main { flex: 1; overflow-y: auto; position: relative; scroll-behavior: auto; }
#progress {
  position: fixed; top: 0; left: var(--sb-w); right: 0; height: 2px;
  background: linear-gradient(90deg, #58a6ff, #a371f7); width: 0;
  z-index: 40; transition: width .1s linear;
}
#content { max-width: 880px; margin: 0 auto; padding: 42px 44px 140px; }
#content h2 {
  font-size: 25px; font-weight: 700; margin: 60px 0 20px; padding: 0 0 12px;
  border-bottom: 1px solid var(--border-2); line-height: 1.35; scroll-margin-top: 20px;
}
#content h2:first-of-type { margin-top: 8px; }
#content h3 {
  font-size: 19px; font-weight: 650; margin: 40px 0 14px; line-height: 1.45;
  scroll-margin-top: 20px; color: #f0f6fc;
}
#content h4 { font-size: 16px; font-weight: 650; margin: 30px 0 11px; color: #d0d8e0; scroll-margin-top: 20px; }
#content p { margin: 13px 0; }
#content a { color: var(--accent); text-decoration: none; border-bottom: 1px solid rgba(88,166,255,.3); }
#content a:hover { border-bottom-color: var(--accent); }
#content strong { color: #f0f6fc; font-weight: 650; }
#content hr { border: none; border-top: 1px solid var(--border); margin: 46px 0; }
#content blockquote {
  margin: 18px 0; padding: 13px 18px; background: rgba(88,166,255,.055);
  border-left: 3px solid var(--accent); border-radius: 0 7px 7px 0; color: #c9d1d9;
}
#content blockquote p { margin: 6px 0; }
#content blockquote strong { color: var(--accent); }
#content ul, #content ol { margin: 13px 0; padding-left: 26px; }
#content li { margin: 6px 0; }
#content li > ul, #content li > ol { margin: 6px 0; }

/* 表格：必须显式 display:table，否则原样式下的 CJK 最小宽度会把表格压成一字一行 */
#content table {
  display: table; width: 100%; border-collapse: collapse;
  margin: 20px 0; font-size: 13.5px; table-layout: auto;
}
#content thead th {
  background: #1c2430; color: #f0f6fc; font-weight: 650; text-align: left;
  padding: 9px 12px; border: 1px solid var(--border-2); white-space: normal;
}
#content tbody td {
  padding: 8px 12px; border: 1px solid var(--border); vertical-align: top; line-height: 1.65;
}
#content tbody tr:nth-child(even) { background: rgba(255,255,255,.017); }
#content tbody tr:hover { background: rgba(88,166,255,.045); }

#content code {
  background: #1c2430; border: 1px solid var(--border);
  border-radius: 4px; padding: 1.5px 5px; font-size: 12.5px;
  font-family: "Cascadia Mono", Consolas, "MS Gothic", monospace;
  color: #79c0ff; word-break: break-word;
}
#content pre {
  background: var(--bg-code); border: 1px solid var(--border-2);
  border-radius: 9px; padding: 15px 17px; overflow-x: auto; margin: 18px 0; line-height: 1.62;
}
#content pre code {
  background: none; border: none; padding: 0; font-size: 12.8px; color: #c9d1d9;
  white-space: pre; display: block;
  font-family: "Cascadia Mono", Consolas, "MS Gothic", monospace;
}
.codehilite {
  background: var(--bg-code) !important; border: 1px solid var(--border-2);
  border-radius: 9px; margin: 18px 0; overflow-x: auto;
}
.codehilite pre { border: none; margin: 0; background: none; }
.codehilite::-webkit-scrollbar { height: 9px; }
.codehilite::-webkit-scrollbar-thumb { background: #2b333d; border-radius: 5px; }

/* pygments 深色高亮覆盖（monokai 原色在 #10151c 底上偏脏，按 GitHub Dark 重写） */
.codehilite .k, .codehilite .kc, .codehilite .kd, .codehilite .kn, .codehilite .kr, .codehilite .kt { color: #ff7b72; }
.codehilite .s, .codehilite .s1, .codehilite .s2, .codehilite .sb, .codehilite .sc, .codehilite .sd,
.codehilite .se, .codehilite .sh, .codehilite .si, .codehilite .sx, .codehilite .sr, .codehilite .ss { color: #a5d6ff; }
.codehilite .c, .codehilite .c1, .codehilite .cm, .codehilite .cs, .codehilite .ch { color: #8b949e; font-style: italic; }
.codehilite .nf, .codehilite .fm { color: #d2a8ff; }
.codehilite .nc, .codehilite .nn, .codehilite .ne { color: #ffa657; }
.codehilite .nb, .codehilite .bp, .codehilite .nv, .codehilite .vc, .codehilite .vg, .codehilite .vi { color: #ffa657; }
.codehilite .o, .codehilite .ow { color: #ff7b72; }
.codehilite .mi, .codehilite .mf, .codehilite .mh, .codehilite .m, .codehilite .mo { color: #79c0ff; }
.codehilite .na, .codehilite .nt, .codehilite .nd { color: #79c0ff; }
.codehilite .n, .codehilite .p, .codehilite .w { color: #e6edf3; }
.codehilite .err { color: #ff7b72; background: none; }

/* 移动端：抽屉式侧边栏（不要改成上下堆叠——window.scrollTo 在无头环境是空操作） */
#menuBtn {
  display: none; position: fixed; left: 14px; top: 14px; z-index: 60;
  width: 40px; height: 40px; border-radius: 9px; cursor: pointer;
  background: #1c2430; border: 1px solid var(--border-2); color: var(--text);
  font-size: 17px; line-height: 1;
}
#scrim { display: none; position: fixed; inset: 0; background: rgba(0,0,0,.55); z-index: 25; }
@media (max-width: 1000px) {
  #sidebar { position: fixed; top: 0; bottom: 0; left: 0; transform: translateX(-100%);
    transition: transform .22s ease; box-shadow: 0 0 40px rgba(0,0,0,.5); }
  #sidebar.open { transform: translateX(0); }
  #menuBtn { display: block; }
  #scrim.show { display: block; }
  #progress { left: 0; }
  #content { padding: 62px 20px 110px; }
  #content table { font-size: 12.5px; }
}
</style>
</head>
<body>
<div id="progress"></div>
<button id="menuBtn" aria-label="目录">☰</button>
<div id="scrim"></div>
<div id="app">
  <aside id="sidebar">
    <div class="sb-head">
      <div class="sb-title">__DOC_TITLE__</div>
      <div class="sb-sub">__SUBTITLE__</div>
    </div>
    <div class="sb-search">
      <input id="q" type="text" placeholder="搜索章节…" autocomplete="off" spellcheck="false">
      <div id="qcount"></div>
    </div>
    <nav id="toc"></nav>
    <div class="sb-foot"><kbd>/</kbd> 聚焦搜索 · <kbd>Esc</kbd> 清空 · 点击目录跳转</div>
  </aside>
  <main id="main">
    <article id="content">
__BODY__
    </article>
  </main>
</div>

<script>
const NAV = __NAV_JSON__;
const main = document.getElementById('main');
const tocEl = document.getElementById('toc');
const qEl = document.getElementById('q');
const qCount = document.getElementById('qcount');
const sidebar = document.getElementById('sidebar');
const scrim = document.getElementById('scrim');
const progress = document.getElementById('progress');

/* 建目录：数据来自 md.toc_tokens，锚点与正文同源，无需任何匹配逻辑 */
const frag = document.createDocumentFragment();
NAV.forEach(function (item) {
  const a = document.createElement('a');
  a.className = 'nav-item d' + item.depth;
  a.href = '#' + item.id;
  a.textContent = item.name;
  a.dataset.id = item.id;
  a.dataset.search = item.name.toLowerCase();
  a.addEventListener('click', function (ev) {
    ev.preventDefault();
    jumpTo(item.id);
    closeDrawer();
  });
  frag.appendChild(a);
});
tocEl.appendChild(frag);
const allLinks = Array.prototype.slice.call(tocEl.querySelectorAll('.nav-item'));

/* 跳转：容器内滚动。不要用 window.scrollTo（无头环境是空操作），也不要 smooth */
function jumpTo(id) {
  const el = document.getElementById(id);
  if (!el) return;
  const top = el.getBoundingClientRect().top - main.getBoundingClientRect().top + main.scrollTop - 14;
  main.scrollTo({ top: top, behavior: 'auto' });
  history.replaceState(null, '', '#' + id);
}

/* 滚动高亮 + 进度条 */
const targets = allLinks.map(function (a) { return document.getElementById(a.dataset.id); });
let ticking = false;
function onScroll() {
  if (ticking) return;
  ticking = true;
  requestAnimationFrame(function () {
    ticking = false;
    const anchor = main.getBoundingClientRect().top + 90;
    let curIdx = 0;
    for (let i = 0; i < targets.length; i++) {
      if (targets[i] && targets[i].getBoundingClientRect().top <= anchor) curIdx = i; else break;
    }
    allLinks.forEach(function (a, i) { a.classList.toggle('active', i === curIdx); });
    const a = allLinks[curIdx];
    if (a) {
      const at = a.offsetTop, ah = a.offsetHeight, st = tocEl.scrollTop, sh = tocEl.clientHeight;
      if (at < st || at + ah > st + sh) tocEl.scrollTop = at - sh / 2 + ah / 2;
    }
    const max = main.scrollHeight - main.clientHeight;
    progress.style.width = (max > 0 ? (main.scrollTop / max) * 100 : 0) + '%';
  });
}
main.addEventListener('scroll', onScroll, { passive: true });

/* 搜索：过滤目录 + 高亮正文中命中的标题 */
function clearMarks() {
  document.querySelectorAll('#content mark.sq').forEach(function (m) {
    const p = m.parentNode;
    p.replaceChild(document.createTextNode(m.textContent), m);
    p.normalize();
  });
}
function runSearch() {
  const q = qEl.value.trim().toLowerCase();
  clearMarks();
  if (!q) {
    allLinks.forEach(function (a) { a.classList.remove('hidden'); });
    qCount.textContent = '';
    return;
  }
  let hit = 0;
  allLinks.forEach(function (a) {
    const ok = a.dataset.search.indexOf(q) !== -1;
    a.classList.toggle('hidden', !ok);
    if (ok) hit++;
  });
  qCount.textContent = hit > 0 ? ('匹配 ' + hit + ' 个章节') : '无匹配章节';
  if (q.length >= 2) {
    allLinks.forEach(function (a) {
      if (a.classList.contains('hidden')) return;
      const h = document.getElementById(a.dataset.id);
      if (!h || h.querySelector('mark.sq')) return;
      const walker = document.createTreeWalker(h, NodeFilter.SHOW_TEXT, null);
      const nodes = [];
      let n;
      while ((n = walker.nextNode())) nodes.push(n);
      nodes.forEach(function (node) {
        const idx = node.nodeValue.toLowerCase().indexOf(q);
        if (idx === -1) return;
        const range = document.createRange();
        range.setStart(node, idx);
        range.setEnd(node, idx + q.length);
        const mark = document.createElement('mark');
        mark.className = 'sq';
        mark.style.cssText = 'background:rgba(210,153,34,.42);color:#fff;border-radius:3px;padding:0 2px;';
        range.surroundContents(mark);
      });
    });
  }
}
qEl.addEventListener('input', runSearch);
document.addEventListener('keydown', function (e) {
  if (e.key === '/' && document.activeElement !== qEl) { e.preventDefault(); qEl.focus(); }
  else if (e.key === 'Escape' && document.activeElement === qEl) { qEl.value = ''; runSearch(); qEl.blur(); }
});

/* 抽屉 */
function closeDrawer() { sidebar.classList.remove('open'); scrim.classList.remove('show'); }
document.getElementById('menuBtn').addEventListener('click', function () {
  sidebar.classList.toggle('open'); scrim.classList.toggle('show');
});
scrim.addEventListener('click', closeDrawer);

/* 加载时按 hash 定位（也让无头截图能直接验证锚点） */
window.addEventListener('load', function () {
  if (location.hash) {
    const id = decodeURIComponent(location.hash.slice(1));
    setTimeout(function () { jumpTo(id); }, 60);
  }
  onScroll();
});
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser(description="长 Markdown → 单栏阅读页 HTML（零改造）")
    ap.add_argument("input", help="输入 .md 路径")
    ap.add_argument("output", nargs="?", help="输出 .html 路径（默认同名 .html）")
    ap.add_argument("--subtitle", default="", help="侧边栏副标题（数据来源 / 版本 / 口径）")
    ap.add_argument("--title", default="", help="覆盖页面标题与侧边栏标题（默认取 md 的 h1）")
    args = ap.parse_args()

    src = pathlib.Path(args.input)
    if not src.exists():
        print(f"ERROR: 找不到输入文件 {src}", file=sys.stderr)
        return 1
    out = pathlib.Path(args.output) if args.output else src.with_suffix(".html")
    return build(src, out, args.subtitle, args.title)


if __name__ == "__main__":
    sys.exit(main())
