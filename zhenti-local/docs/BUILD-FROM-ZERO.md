# 从零复刻「本地真题备考工作台」

> 这份文档假设你手上有一堆真题 PDF、几段听力音频，想要一个只在自己电脑上跑的备考工作台。
> 读完并照着做，你能得到一个和本仓库 `zhenti-local/` 结构一致、可以继续往上加功能的系统。
>
> 参考实现就在同目录下（`server.mjs`、`public/`、`tools/`），文中的行号与文件路径都对得上。
> 但**不要照抄**，照抄只能得到一个跑起来的壳；文档里每个阶段都写了「为什么这样设计」和「验收标准」，那才是可复用的部分。

---

## 0. 先搞清楚要造什么

### 0.1 这套系统解决的问题

市面上的真题站点把「看清一卷纸」拆成了几件互相绑定的事，注册、会员、设备绑定、在线看、不能下载、答案另收费。你想做的只是「打开、读、听、做题、记笔记、下次接着上次的位置」。

本地工作台把这五件事拆开，每一件都落到你自己硬盘上的一个文件里。

| 你在界面上的动作 | 落到磁盘上 |
|---|---|
| 翻到第 12 页 | `data/cet6/2025-12/01/progress.json` |
| 听听力听到 08:31 | 同上，`audioTime` 字段 |
| 写一段笔记 | `data/cet6/2025-12/01/notes.md` |
| 点选答题卡第 7 题选 B | `data/cet6/2025-12/01/sheet.json` |
| 荧光笔划了一句 | `data/cet6/2025-12/01/ink.json` |
| 双击一个单词 | 不进磁盘，现查 `data/dict.db` |
| 把生词加进生词本 | `data/study/wordbook.json` |

这个映射关系决定了整个架构。**没有数据库、没有账号、没有云端**，文件系统就是状态层。好处是备份=复制文件夹，坏处是并发写入要自己防（第 3 节讲）。

### 0.2 成品规模（给你一个心理预期）

| 项 | 数量 |
|---|---|
| 索引里的套卷 | 180 套（六级 83 / 四级 67 / 专四 15 / 专八 15） |
| 本地真的收了正文的 | 161 套 |
| 有听力音频的 | 88 套 |
| 有标准答案的 | 68 套 |
| `data/` 占用 | 2.21 GB |
| 手写代码 | 约 6100 行（服务端 477 + 前端 2700 + 工具 2900） |

真正属于「应用」的代码只有 `server.mjs` + `public/` 四个文件，约 2700 行。其余全是往 `data/` 里搬东西的工具。

### 0.3 复刻路线图

八个阶段，每个阶段都能独立跑通、独立验收。**不要跳**，第 1 阶段的 50 行代码是你后面所有调试的基准。

```
阶段 0  环境与目录            → 有 node、有 public/ data/
阶段 1  最小闭环              → 浏览器能显示一页 PDF
阶段 2  题库索引              → 首页能列出所有套卷
阶段 3  阅读器                → 连续滚动、翻页、缩放不卡
阶段 4  听力                  → 能拖进度条、能倍速
阶段 5  学习数据              → 进度/笔记/答题卡刷新不丢
阶段 6  文字层与圈画          → 能点词查词、能画线、缩放不错位
阶段 7  数据流水线            → 批量把素材灌进 data/
阶段 8  质检与运维            → 改坏了能当场发现
```

阶段 7 是工作量最大的一段（占全部时间的六成以上），但它和 1 到 6 是解耦的。前六个阶段只要 `data/` 里有一套卷子就能跑，第七阶段负责把一套变成一百套。

---

## 1. 项目架构

### 1.1 一句话架构

**一个零依赖的 Node HTTP 服务，把一个目录树当数据库，前端两页（目录页 + 阅读器），工具脚本负责往目录树里搬数据。**

四层，从上到下依次是。

```
┌──────────────────────────────────────────────────────────────┐
│  浏览器（public/）                                            │
│   index.html + app.js     目录、筛选、搜索                    │
│   read.html + read.js     阅读器业务（笔记/答题卡/生词/解析）  │
│   viewer.js               PDF 渲染内核（可独立复用）           │
│   vendor/pdfjs/           pdf.js 4.10.38（唯一第三方前端库）   │
└───────────────────────────┬──────────────────────────────────┘
                            │ fetch /api/*  ·  GET /data/*
┌───────────────────────────▼──────────────────────────────────┐
│  服务层（server.mjs，477 行，只用 node: 内置模块）             │
│   静态资源  GET /public/*                                     │
│   题库文件  GET /data/*（支持 Range 206，音频拖动靠它）        │
│   学习 API  /api/papers /api/paper /api/dict /api/ink …       │
└───────────────────────────┬──────────────────────────────────┘
                            │ fs 读写（原子写 .tmp + rename）
┌───────────────────────────▼──────────────────────────────────┐
│  数据层（data/，纯文件）                                      │
│    papers.json            180 套元数据索引                    │
│    <exam>/<period>/<set>/ 每套一个目录                        │
│    dict.db                ECDICT 全量词库（SQLite）           │
│    study/                 跨套共享的生词本、错题本            │
└───────────────────────────▲──────────────────────────────────┘
                            │ 只在开发时跑，不进运行时
┌───────────────────────────┴──────────────────────────────────┐
│  工具层（tools/，Node + Python 混合）                         │
│   ingest*.mjs    采集/复制入库                                │
│   tem/*.py       网页归档 → 重排 → PDF                        │
│   ocr/ocr-pdf.py 扫描件补隐形文字层                           │
│   build-*.py     词库、逐题解析                               │
│   check/status   语法自检、只读体检                           │
└──────────────────────────────────────────────────────────────┘
```

### 1.2 目录结构（真实版）

```
zhenti-local/
├─ server.mjs                 服务端全部逻辑（路由 + 静态 + Range + 原子写）
├─ start.bat / start.sh       启动器（找 node、顺延端口、开浏览器）
├─ package.json               只有 scripts，没有 dependencies
├─ public/
│  ├─ index.html              目录页骨架（51 行，只放容器）
│  ├─ app.js                  目录页逻辑（取数 → 渲染 → 交互）
│  ├─ read.html               阅读器骨架（200 行，工具栏 + 侧栏全部按钮）
│  ├─ read.js                 阅读器业务（1109 行，最长的单文件）
│  ├─ viewer.js               PDF 渲染内核（722 行，导出 createViewer）
│  ├─ app.css                 全站样式（509 行，首页与阅读器共用）
│  └─ vendor/pdfjs/           pdf.min.mjs + pdf.worker.min.mjs
├─ data/
│  ├─ papers.json             索引（只有元数据，没有正文）
│  ├─ dict.db                 词库 82 MB
│  ├─ dict.json               旧版精简词库（兜底）
│  ├─ study/{wordbook,wrong}.json
│  └─ cet6/2025-12/01/
│     ├─ read.pdf             试卷（重排版存在时是 read.clean.pdf）
│     ├─ listen.m4a           听力（扩展名按真实格式）
│     ├─ analysis.pdf         答案解析
│     ├─ analysis.json        逐题解析（可选）
│     ├─ answers.json         标准答案（可选）
│     ├─ meta.json            来源 URL、字节数、sha256、audioRef
│     ├─ progress.json        页码 / 听力位置 / 缩放（运行时生成）
│     ├─ sheet.json           我的作答（运行时生成）
│     ├─ ink.json             圈画笔迹（运行时生成）
│     └─ notes.md             笔记
└─ tools/
   ├─ ingest.mjs              清单 → 探测格式 → 下载 → 写 meta → 补索引
   ├─ ingest-cet4.mjs         本地目录 → 硬链接入库
   ├─ ingest-legacy.mjs       补旧考次
   ├─ tem/ingest-tem.py       网页归档 → 抽取 → 重排 → 打印 PDF
   ├─ tem/extract.py          BeautifulSoup 正文定位
   ├─ tem/build_paper_pdf.py  正文 → HTML → 无头 Edge 打印
   ├─ tem/extract-answers.py  答案表正则抽取（带校验）
   ├─ build-analysis.py       analysis.pdf → analysis.json
   ├─ ocr/ocr-pdf.py          扫描件补隐形文字层
   ├─ build-dict-full.py      ECDICT.csv → dict.db
   ├─ fetch-answers.mjs       借站点 Worker 解密答案（CDP）
   ├─ cdp.mjs                 80 行 CDP 客户端
   ├─ check.mjs               全量 node --check
   ├─ status.mjs              只读体检
   ├─ browser-check.mjs       浏览器里真点一遍
   └─ restart-server.ps1      按端口安全重启
```

### 1.3 一次点击的完整链路

以「从首页点进 2025 年 12 月第 1 套，双击一个单词」为例，六次网络往返，每一步都有对应的代码。

```
①  GET /api/papers
    server 读 data/papers.json，再对每一套调 localState()
    → 检查 read.pdf / listen.* / answers.json / analysis.pdf / cover.*
    → 算出 local、started、sheet 三个运行时字段
    → 返回 { exams, papers: [...], counts }
    app.js 拿到后按 exam 分页签、按 groupLabel 分组渲染

②  GET /read.html?id=cet6/2025-12/01        静态文件

③  GET /api/paper?id=cet6/2025-12/01
    并发读 6 个文件（meta/notes/progress/answers/sheet/analysis）
    → 听力文件名不固定，这里由服务端判定后返回 audioFile
    → pdfFile 优先 read.clean.pdf，其次 read.pdf，都没有就是 null
    read.js 拿 pdfFile 去 ④，拿 answers 去渲染答题卡

④  GET /data/cet6/2025-12/01/read.pdf
    serveFile() 先看 content-type，再看 req.headers.range
    阅读器首屏只渲可见页，PDF 其余部分由 pdf.js 自己按需 range 请求

⑤  GET /data/cet6/2025-12/01/read.pdf    （带 Range: bytes=…）
    pdf.js 拿到第 5 页的字节段，渲 canvas，再铺文字层
    renderText() 把每个 span 的英文单词包成 <aw>，这一步是查词的前提

⑥  GET /api/dict?word=discipline
    词库查 dict.db 的 w 表，没命中查 f 表（变形→原形），再没命中给前缀候选
    viewer.js 把结果填进 #dictPop 的浮层
```

关键设计在这里已经出现三次。**服务端负责「判定」，前端不猜文件名**。听力是 mp3 还是 m4a、正文是 read.pdf 还是 read.clean.pdf、这一套有没有答案，全部由 `/api/paper` 一次说清。这条规矩省掉了前端一半的分支判断。

### 1.4 四份数据契约

想复刻，先背下这四份格式，后面所有工具都是往这四个框里填东西。

**(1) `data/papers.json` 全量索引**

```json
{
  "generatedAt": "2026-10-18",
  "groupOrder": ["cet6", "cet4", "tem4", "tem8"],
  "exams": [{ "id": "cet6", "name": "大学英语六级", "short": "六级",
              "source": "https://zhenti.burningvocabulary.cn/cet6" }],
  "papers": [
    {
      "id": "cet6/2026-06/02",
      "exam": "cet6",
      "period": "2026-06",
      "set": "02",
      "title": "2026年6月英语六级真题(第2套)",
      "group": "2026年6月",
      "groupLabel": "2026年 - 上半年",
      "latest": true,
      "thumbnail": "https://…/thumbnail.webp",
      "source": "https://…/cet6/2026-06/02",
      "files": {
        "pdf":      { "name": "read.pdf", "bytes": 1362228, "sha256": "4b4f…" },
        "audio":    { "name": "listen.m4a", "bytes": 4619865, "sha256": "4a13…" },
        "analysis": { "name": "analysis.pdf", "bytes": 758472, "sha256": "61d1…" }
      }
    }
  ]
}
```

`id` 的形状 `exam/YYYY-MM/NN` 是全系统的第一约定。它同时是目录路径、URL 参数、API 主键、圈画文件的归属键。`server.mjs` 用一条正则把这个约定写成硬约束。

```js
const validPaperId = (id) =>
  typeof id === "string" && /^[a-z0-9]+\/\d{4}-\d{2}\/[0-9a-z]+$/i.test(id);
```

为什么不用数据库自增 id，理由有三个。目录名和 id 一致，出问题时用资源管理器就能定位；索引文件可以直接 diff，加一套卷就是加一段 JSON；换机器只要复制文件夹，路径不会失效。

**(2) `data/<套>/meta.json` 单套档案**

```json
{
  "id": "cet6/2026-06/02",
  "title": "2026年6月英语六级真题(第2套)",
  "source": "https://…/cet6/2026-06/02",
  "files": {
    "pdf": { "name": "read.pdf", "bytes": 1362228, "sha256": "4b4f…",
             "format": "pdf", "declaredExt": "pdf", "source": "A",
             "url": "https://raw.githubusercontent.com/…/cet6_2026_06_2.pdf",
             "originalName": "cet6_2026_06_2.pdf" }
  },
  "capabilities": { "answers": false, "listeningText": false, "sentenceTranslation": false },
  "audioRef": "cet6/2026-06/01",
  "audioRefNote": "本套没有独立可下载音频，复用同考次听力素材",
  "ingestedFrom": "cet6/sources/CET6-MASTER.md",
  "ingestedAt": "2026-10-20T16:57:27.949Z"
}
```

三个字段值得单独讲。

`url` 记下真实来源，是为了三个月后重新下载或核对字节数时不用再猜。
`sha256` 让「这份文件和索引里记的是不是同一份」可验证，重下不重复。
`audioRef` 解决官方多套卷共用听力的问题。第 3 套往往没有独立音频，服务端找不到自己的 `listen.*` 就顺着 `audioRef` 去同考次另一套目录里找，前端只显示「复用 xxx」。

**(3) 每套目录里的运行时文件**

| 文件 | 写入者 | 内容 |
|---|---|---|
| `progress.json` | `POST /api/progress` | `{page, audioTime, scale, view:{mode,zoomKind}, updatedAt}` |
| `sheet.json` | `POST /api/sheet` | `{count, answers:{"7":"B"}, updatedAt}` |
| `answers.json` | 工具写入 | `{"1":"C","2":"B","notes":"…"}` |
| `ink.json` | `POST /api/ink` | `{pages:{"1":[{t,c,w,p:[[x,y],…]}]}, updatedAt}` |
| `notes.md` | `POST /api/notes` | 纯 Markdown |

`answers.json` 和 `sheet.json` 必须分开。前者是标准答案，可能来自站点、可能来自归档抽取；后者是我的作答。合成一个文件，就会出现「换了一份答案把我的作答覆盖了」这种事。

**(4) `data/study/*.json` 跨套集合**

```json
[
  { "key": "cet6/2025-12/01::discipline", "word": "discipline",
    "paper": "2025年12月英语六级真题(第1套)", "at": "2026-10-22T10:00:00.000Z" }
]
```

`key` 用 `套卷id::词` 拼成，天然去重。删一条就是按 key 过滤。

### 1.5 为什么坚持零依赖

`package.json` 里没有 `dependencies`，服务端只用 `node:http`、`node:fs`、`node:path`、`node:crypto`、`node:url`，词库用 `node:sqlite`。

这个选择的代价和收益都很明确。

代价是你要自己写路由、自己写静态文件服务、自己处理 Range、自己做路径穿越防护。这些在 Express + `express.static` 里是免费的。

收益有三条。第一，三年后打开这个项目，它还能跑，不会因为某个依赖的主版本升级而崩。第二，`git clone` 之后不需要 `npm install`，没有 `node_modules` 这个黑洞。第三，出问题时栈只有两层（你的代码 + Node 内置模块），排查快得多。

实际写下来，`server.mjs` 477 行，其中静态文件服务 40 行、Range 25 行、原子写 8 行。这 73 行就是全部「框架费」。**如果你只是做个自用工具，这笔交易是划算的；如果要做多人协作的产品，一开始就该上框架。**

前端唯一的外部依赖是 pdf.js，而且是 vendored（`public/vendor/pdfjs/`，两个文件 1.7 MB），不走 CDN。理由是离线可用，而且版本锁死之后 API 不会突然变。

> 注意区分，仓库根目录还有一份 `package.json` 只依赖 `playwright-core`，那是给根目录下的截图/浏览器脚本用的，不属于工作台本体。`zhenti-local/` 自己不带任何 npm 依赖。

---

## 2. 一步一步搭

### 阶段 0 · 环境与骨架

**要装什么**

| 用途 | 需要 | 是否必需 |
|---|---|---|
| 跑服务、前端 | Node 18+（推荐 22 / 24） | 必需 |
| 词库 SQLite（`node:sqlite`） | Node 22.5+，Node 24 开箱可用 | 可选，失败会退回 dict.json |
| 灌数据、OCR、重排 | Python 3.10+ | 只在阶段 7 需要 |
| 解析 PDF（pymupdf）、抓 HTML（beautifulsoup4 + lxml） | `pip install pymupdf beautifulsoup4 lxml` | 阶段 7 |
| 扫描件识别 | `pip install rapidocr` | 阶段 7.4 |
| 重排 PDF（reportlab） | `pip install reportlab` | 阶段 7.3 进阶 |
| 打印 PDF | 本机 Edge 或 Chrome | 阶段 7.3 |

Python 依赖装进虚拟环境，不要污染全局。

```bash
cd zhenti-local
python -m venv .venv
.venv/Scripts/activate          # Windows
pip install pymupdf beautifulsoup4 lxml rapidocr reportlab
```

**建目录**

```bash
mkdir -p public/vendor/pdfjs data/study tools
```

从 [pdf.js 的 release](https://github.com/mozilla/pdf.js/releases) 取 4.10.38 的 `pdf.min.mjs` 与 `pdf.worker.min.mjs`，放进 `public/vendor/pdfjs/`。这两个文件名里的 `.mjs` 不能改，代码里是按路径 import 的。

**验收**，两条命令都不报错。

```bash
node -v          # v22 或 v24
python -c "import pymupdf, bs4; print('ok')"
```

---

### 阶段 1 · 最小闭环（50 行，先看见一页纸）

这一步的目标只有一个，**浏览器里出现一页真题 PDF**。所有花哨功能都建立在这 50 行上，所以自己手敲一遍，不要复制。

先放一份测试文件 `data/demo/read.pdf`（随便一份真题就行）。

`server-min.mjs` 全文如下。

```js
import { createServer } from "node:http";
import { createReadStream, existsSync, statSync } from "node:fs";
import { extname, join, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(fileURLToPath(new URL(".", import.meta.url)));
const PUBLIC = join(ROOT, "public");
const DATA = join(ROOT, "data");

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".pdf": "application/pdf",
  ".mp3": "audio/mpeg",
  ".m4a": "audio/mp4",
};

/** 拼路径，但不允许跑出 base 目录 */
const safeJoin = (base, relative) => {
  const target = resolve(base, relative.replace(/^([/\\])+/, ""));
  if (target !== base && !target.startsWith(base + sep)) return null;
  return target;
};

createServer((req, res) => {
  const url = new URL(req.url ?? "/", "http://localhost");
  const isData = url.pathname.startsWith("/data/");
  const base = isData ? DATA : PUBLIC;
  const relative = decodeURIComponent(isData ? url.pathname.slice(6) : url.pathname);
  const target = safeJoin(base, relative === "/" ? "index.html" : relative);

  if (!target || !existsSync(target) || !statSync(target).isFile()) {
    res.writeHead(404, { "content-type": "text/plain; charset=utf-8" });
    return res.end("not found");
  }
  const info = statSync(target);
  res.writeHead(200, {
    "content-type": MIME[extname(target).toLowerCase()] ?? "application/octet-stream",
    "content-length": info.size,
  });
  createReadStream(target).pipe(res);
}).listen(8787, "127.0.0.1", () => {
  console.log("http://127.0.0.1:8787/");
});
```

`public/read-min.html` 全文如下。

```html
<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>最小阅读器</title>
<style>body{margin:0;background:#525659;padding:20px;text-align:center}
canvas{background:#fff;box-shadow:0 4px 18px rgba(0,0,0,.4)}</style></head>
<body>
<canvas id="c"></canvas>
<script type="module">
import * as pdfjsLib from "/vendor/pdfjs/pdf.min.mjs";
pdfjsLib.GlobalWorkerOptions.workerSrc = "/vendor/pdfjs/pdf.worker.min.mjs";

const doc = await pdfjsLib.getDocument("/data/demo/read.pdf").promise;
const page = await doc.getPage(1);

const viewport = page.getViewport({ scale: 1.4 });
const canvas = document.getElementById("c");
const ratio = window.devicePixelRatio || 1;          // 高分屏必须乘

canvas.width = Math.floor(viewport.width * ratio);
canvas.height = Math.floor(viewport.height * ratio);
canvas.style.width = `${Math.floor(viewport.width)}px`;
canvas.style.height = `${Math.floor(viewport.height)}px`;

await page.render({
  canvasContext: canvas.getContext("2d"),
  viewport,
  transform: [ratio, 0, 0, ratio, 0, 0],             // 不传这行，字会糊
}).promise;
console.log("pages:", doc.numPages);
</script>
</body></html>
```

启动 `node server-min.mjs`，打开 `http://127.0.0.1:8787/read-min.html`。

**验收三件事**

1. 纸上出现了真题第一页。
2. 控制台打印了总页数，没有 404。
3. 按 F12 切到手机模拟（DPR 变成 2 或 3）再刷新，页面**仍然清晰**，说明 `transform` 和 `canvas.width` 那两处 DPR 处理是对的。

**这里最容易错的两处**

`page.render` 忘了传 `transform`，画面在普通屏上看不出问题，到 MacBook 的 2 倍屏上整页发虚。
`canvas.width` 设成了 CSS 像素（没乘 DPR），结果渲染被浏览器放大，同样发虚。

---

### 阶段 2 · 题库索引（让目录变成数据）

阶段 1 是「打开一个写死的文件」。这一步要把「打开哪个文件」变成数据驱动的。

**先手写三条，然后再生成**

新建 `data/papers.json`，只写三套，格式照 1.4 节。手写的目的是让你亲手碰到那个 `id` 约定，写错一次（比如写成 `cet6-2025-12-01`）你就知道为什么服务端要用正则卡住它。

然后写一个一次性脚本，扫 `data/` 生成完整的 `papers` 数组。判据很简单，目录深度为 3 且形如 `<exam>/<YYYY-MM>/<NN>` 就是一套。

```js
// tools/scan-papers.mjs  （一次性，跑完可以留作参考）
import { readdirSync, statSync, writeFileSync, readFileSync } from "node:fs";
import { join } from "node:path";

const DATA = "data";
const index = JSON.parse(readFileSync(join(DATA, "papers.json"), "utf8"));
const have = new Set(index.papers.map((p) => p.id));

for (const exam of readdirSync(DATA)) {
  const examDir = join(DATA, exam);
  if (!statSync(examDir).isDirectory()) continue;
  for (const period of readdirSync(examDir)) {
    if (!/^\d{4}-\d{2}$/.test(period)) continue;
    for (const set of readdirSync(join(examDir, period))) {
      const id = `${exam}/${period}/${set}`;
      if (have.has(id)) continue;
      const [year, month] = period.split("-");
      index.papers.push({
        id, exam, period, set,
        title: `${year}年${Number(month)}月真题(第${Number(set)}套)`,
        group: `${year}年${Number(month)}月`,
        groupLabel: `${year}年 - ${Number(month) <= 6 ? "上半年" : "下半年"}`,
        latest: false,
        source: "",
      });
    }
  }
}
writeFileSync(join(DATA, "papers.json"), JSON.stringify(index, null, 2) + "\n");
console.log(`共 ${index.papers.length} 套`);
```

**加接口**

`/api/papers` 不能只把索引吐出来。前端要知道「哪套能点开」，而这件事只能问文件系统。

```js
const localState = async (paper) => {
  const dir = paperDir(paper.id);
  if (!dir || !existsSync(dir)) {
    return { ...paper, local: { pdf: false, audio: false, answers: false }, started: false };
  }
  const pdf = existsSync(join(dir, "read.pdf")) || existsSync(join(dir, "read.clean.pdf"));
  const audio = ["listen.mp3", "listen.m4a", "listen.wav"].some((n) => existsSync(join(dir, n)));
  const progress = pdf ? await readJson(join(dir, "progress.json"), null) : null;
  return {
    ...paper,
    local: { pdf, audio, answers: existsSync(join(dir, "answers.json")) },
    progress,
    started: Boolean(progress) && ((progress.page ?? 1) > 1 || (progress.audioTime ?? 0) > 5),
  };
};
```

`started` 的判据是 `page > 1` 或者听过 5 秒以上。拿「打开过」当判据，误点一下就变成「已开始」，筛选项立刻失去意义。

**渲染**

`app.js` 的结构是三段式，取数 → 组装 → 挂事件，全程不引框架。

```js
const state = { index: null, exam: "all", filter: "all", query: "" };

const boot = async () => {
  const [index, overview] = await Promise.all([
    (await fetch("/api/papers")).json(),
    (await fetch("/api/overview")).json(),
  ]);
  state.index = index;
  buildExamTabs();
  renderStats();
  renderOverview(overview);
  render();
};

const render = () => {
  const papers = (state.exam === "all" ? state.index.papers : state.index.papers.filter((p) => p.exam === state.exam))
    .filter(matchesFilter);
  // 按 groupLabel 分组，有收录的排卡片，没收录的压成一行芯片
};
```

用原生 DOM 拼字符串，不做虚拟 DOM。180 套卷子的 DOM 规模下，一次 `innerHTML` 重建大约几毫秒，没有性能问题。**在没有性能问题的地方上框架，是给自己加负担。**

搜索用 160ms 防抖，`haystack` 把标题、期次、套号、考试名全拼进去，这样输入 `2025-12`、`第2套`、`六级` 都能命中。

**验收三件事**

1. 首页把 `data/` 下所有套卷列出来，按考试类型分页签，页签上带数量。
2. 在 `data/` 里手动 `mkdir cet6/2019-12/01` 并放一个 `read.pdf`，刷新页面，**不改代码**就能看到它从「未收录芯片」变成可点的卡片。
3. 搜索 `2025-12` 只剩那一个考次。

第 2 条是整个架构的分水岭。做到了，说明「数据驱动」这条线通了；做不到，后面加多少功能都是在写死。

---

### 阶段 3 · 阅读器内核（这一段决定后面所有体验）

`viewer.js` 是项目里最值得读的文件。它导出 `createViewer({...})`，内部维护一个状态机，对外只暴露 `load / goTo / setZoom / setMode / setTool / undoInk / clearInk`。

结构是这样一棵 DOM 树，每个页面三层叠着。

```
.viewer-scroll              滚动容器（overflow:auto）
└─ .pages
   └─ .spread               一行（单页模式 1 个 .page，双页模式 2 个）
      └─ .page              相对定位，尺寸 = 页面基准尺寸 × scale
         ├─ canvas          正文（pdf.js 画进来）
         ├─ canvas.inkLayer 笔迹（透明，z-index 1）
         └─ .textLayer      文字层（透明，铺在最上面）
```

**四条硬约束，违反了就出玄学 bug**

**① 一个 canvas 同一时间只能有一个 render。** 翻页和缩放撞在一起会抛 `Cannot use the same canvas during multiple render() operations`，之后整个渲染管线卡死，白屏，没有报错。所以渲染必须串行排队。

```js
let rendering = false;
let renderAgain = false;

const renderVisible = async () => {
  if (rendering) { renderAgain = true; return; }   // 途中来的需求不丢，标记后补一轮
  rendering = true;
  try {
    for (;;) {
      renderAgain = false;
      for (;;) {
        // 只挑可见、且当前 scale 还没渲过的页，离当前页近的优先
        const todo = state.pages
          .filter((v) => v.visible && v.renderedScale !== state.scale)
          .sort((a, b) => Math.abs(a.num - state.page) - Math.abs(b.num - state.page))[0];
        if (!todo) break;
        await renderOne(todo);
      }
      if (!renderAgain) break;
    }
  } finally {
    rendering = false;
  }
};
```

这个双层循环是「合并请求」的经典写法。外层处理「渲染途中又有新请求」，内层处理「可见页还没渲完」。

**② 只渲可见页。** 一套卷子 10 到 14 页，全渲也不是不行，但缩放到 200% 时每页 canvas 有 1200×1600 像素，内存会撑爆。用 `IntersectionObserver` 观察每一页，`rootMargin: "700px 0px"` 让上下各预渲约两页，滚动时就不会看到白块。

```js
const observer = new IntersectionObserver((entries) => {
  for (const entry of entries) {
    const view = state.pages[Number(entry.target.dataset.page) - 1];
    if (view) view.visible = entry.isIntersecting;
  }
  renderVisible();
}, { root: scrollEl, rootMargin: "700px 0px" });
```

**③ 缩放前记住位置，缩放后还原。** 否则按一下 `+`，你正在读的那段文字会跳走。

```js
const anchor = () => {
  const view = state.pages[state.page - 1];
  const top = scrollEl.getBoundingClientRect().top;
  const rect = view.el.getBoundingClientRect();
  return { page: view.num, ratio: (top - rect.top) / rect.height };  // 停在页内百分之几处
};

const restoreAnchor = (mark) => {
  const view = state.pages[mark.page - 1];
  const top = scrollEl.getBoundingClientRect().top;
  const rect = view.el.getBoundingClientRect();
  scrollEl.scrollTop += rect.top - top + mark.ratio * rect.height - PAGE_GAP;
};
```

用「页号 + 页内比例」而不是 `scrollTop` 的绝对值，因为缩放后总高度变了，绝对像素没有意义。

**④ 字号跟着 scale 走。** pdf.js 4.x 的文字层用 CSS 变量算字号，`calc(var(--scale-factor) * 12px)`。容器上不设这个变量，所有字的定位会挤成一坨（视觉上看不出来，因为文字层是透明的，但选区全错）。

```js
view.textEl.style.setProperty("--scale-factor", String(state.scale));
```

**滚动联动页码**

连续滚动模式下，页码不是「点出来的」，是算出来的。取视口内可见面积最大的那一页。

```js
const syncPageFromScroll = () => {
  const top = scrollEl.getBoundingClientRect().top;
  const bottom = top + scrollEl.clientHeight;
  let best = null, bestArea = 0;
  for (const view of state.pages) {
    const rect = view.el.getBoundingClientRect();
    const area = Math.max(0, Math.min(rect.bottom, bottom) - Math.max(rect.top, top));
    if (area > bestArea) { bestArea = area; best = view; }
  }
  if (best && best.num !== state.page) { state.page = best.num; updateChrome(); notify(); }
};
```

滚动事件里包一层 `requestAnimationFrame` 节流，`{ passive: true }` 让浏览器不等你的 handler。

**验收四件事**

1. 一路滚到最后一页，中间不出现长时间白块。
2. 按住 `+` 连点十下，控制台没有 `Cannot use the same canvas`。
3. 在 75% 缩放下滚到某段文章中间，切到 150%，视线里还是那段文章。
4. 切到双页模式，左右两页并排，翻页一次走两页。

**一个反直觉的坑**，标签页切到后台（`visibility: hidden`）时，pdf.js 的 `page.render().promise` 永远不 resolve，不报错，就是卡住。因为 pdf.js 内部依赖 `requestAnimationFrame`，而隐藏标签页不触发 rAF。用无头浏览器截图排查时，先确认 `document.visibilityState` 是 `visible`。

---

### 阶段 4 · 听力（Range 不是可选优化，是必需品）

`<audio src="/data/xxx/listen.m4a">` 这样写能播，但拖进度条会卡十几秒甚至直接失败。原因是没有 Range 支持，浏览器要么等整个文件下完，要么放弃 seek。

服务端 25 行。

```js
const serveFile = (req, res, path, download = false) => {
  const contentType = MIME[extname(path).toLowerCase()] ?? "application/octet-stream";
  stat(path).then((info) => {
    const range = req.headers.range;
    if (range && /^bytes=\d*-\d*$/.test(range)) {
      const [rawStart, rawEnd] = range.replace("bytes=", "").split("-");
      let start = rawStart === "" ? info.size - Number(rawEnd) : Number(rawStart);
      let end = rawStart === "" || rawEnd === "" ? info.size - 1 : Number(rawEnd);
      start = Math.max(0, Math.min(start, info.size - 1));
      end = Math.max(start, Math.min(end, info.size - 1));
      res.writeHead(206, {
        "content-type": contentType,
        "content-length": end - start + 1,
        "content-range": `bytes ${start}-${end}/${info.size}`,
        "accept-ranges": "bytes",
      });
      createReadStream(path, { start, end }).pipe(res);
      return;
    }
    res.writeHead(200, {
      "content-type": contentType,
      "content-length": info.size,
      "accept-ranges": "bytes",       // 这句是告诉浏览器「可以按段要」
    });
    createReadStream(path, { start: 0, end: info.size - 1 }).pipe(res);
  });
};
```

三个细节容易漏。第一，状态码必须是 **206** 而不是 200，且必须带 `content-range`。第二，`accept-ranges: bytes` 在 200 响应里也要给，浏览器看到它才敢发第一段 range 请求。第三，`bytes=-500` 这种「只要最后 500 字节」的写法要把 start 算成 `size - 500`。

**格式嗅探，这个问题一定会在真实数据上出现**

采集来的文件里，名字叫 `listening.mp3`、文件头却是 `ftyp`（MP4 容器）的一大批。按 URL 后缀当 mp3 发给浏览器，`audio/mpeg` 解码器拿到 AAC 数据，直接播不了，报错还很难读。

所以在**入库时**嗅探前 16 字节，按真实格式命名与给 MIME。

```js
const formatOf = (buf) => {
  if (buf.subarray(0, 4).toString("latin1") === "%PDF") return "pdf";
  if (buf.subarray(4, 8).toString("latin1") === "ftyp") return "m4a";   // offset 4 才是 ftyp
  if (buf.subarray(0, 3).toString("latin1") === "ID3") return "mp3";
  if (buf[0] === 0xff && (buf[1] & 0xe0) === 0xe0) return "mp3";
  if (buf.subarray(0, 4).toString("latin1") === "RIFF") return "wav";
  return "unknown";
};
```

服务端对应的 MIME 表里 `.m4a` 必须是 `audio/mp4`。

**播放器本身**

`<audio>` 原生能力就够，不需要任何播放器库。要自己实现的只有四件。

进度条用 `<input type="range" min="0" max="1000">`，`timeupdate` 里更新，用户正按着的时候不要抢（`seek.matches(":active")` 时跳过写入）。

AB 复读在 `timeupdate` 里判 `currentTime >= b` 就跳回 `a`。

倍速直接设 `audio.playbackRate`，0.75 到 2.0 五档。

播放位置记忆每 15 秒存一次，另外 `pause` 时存一次，`beforeunload` 用 `navigator.sendBeacon` 补最后一次（普通 fetch 在卸载页面时会被取消）。

```js
window.addEventListener("beforeunload", () => {
  navigator.sendBeacon?.("/api/progress", new Blob([JSON.stringify({
    id: paperId, page: viewer.state.page, audioTime: $("audio").currentTime,
  })], { type: "application/json" }));
});
```

**验收两件事**

1. 拖进度条到 20 分钟处，**立刻**出声，不需要等。
2. 把 `serveFile` 里的 Range 分支临时注掉，再拖进度条，体验明显变差。亲手做一次这个对比，你就不会忘记为什么这 25 行必须写。

---

### 阶段 5 · 学习数据（重点在「不丢」）

这一层的功能都简单，难的是可靠性。四种数据（进度 / 笔记 / 答题卡 / 圈画）都在高频写入，任何一次写坏就是用户数据损坏。

**原子写，8 行，必须用**

```js
const writeFileAtomic = async (path, text) => {
  await mkdir(resolve(path, ".."), { recursive: true });
  const temp = `${path}.tmp`;      // 先写同目录临时文件
  await writeFile(temp, text, "utf8");
  await rename(temp, path);        // rename 在同一分区上是原子的
};
```

`rename` 在 NTFS 和 ext4 上都是原子操作。写到一半断电，磁盘上要么是旧的完整文件，要么是新的完整文件，不会出现半截 JSON。直接把 `writeFile` 指向目标文件，崩一次就得到一个 0 字节的 `progress.json`，下次启动 `JSON.parse` 抛错，进度全没。

**输入要清洗，不要相信前端**

`/api/sheet` 收到的东西可能来自任何地方（包括你自己手写的 curl）。服务端统一裁一遍。

```js
const clean = {};
for (const [key, value] of Object.entries(answers ?? {})) {
  const number = Number(key);
  if (!Number.isInteger(number) || number < 1 || number > 1000) continue;
  const text = String(value ?? "").trim().toUpperCase().slice(0, 4);
  if (text) clean[String(number)] = text;
}
```

圈画的点也要裁。一次最多 2000 笔、一笔最多 20000 个点、坐标保留四位小数。不做这一步，一个写错的脚本能给你生成 200 MB 的 `ink.json`。

**保存要防抖，还要串行**

前端每次翻页都会触发保存。防抖 700ms。但防抖不够，两次 POST 同时在路上时，先发的可能后到，后到的旧数据会覆盖新数据。圈画的保存用一条 Promise 链排队。

```js
let inkQueue = Promise.resolve();
const scheduleInkSave = () => {
  clearTimeout(ink.saveTimer);
  ink.saveTimer = setTimeout(() => {
    inkQueue = inkQueue.then(() => api("/api/ink", { id: paperId, pages: ink.pages }));
  }, 700);
};
```

服务端这边 `POST /api/progress` 做的是「读旧值 + 合并新值」，不做整份覆盖，只更新传来的字段。这样页码和听力位置互不干扰。

```js
const current = await readJson(join(dir, "progress.json"), {});
const next = {
  page: Number(page) || current.page || 1,
  audioTime: Number(audioTime) || current.audioTime || 0,
  scale: Number(scale) || current.scale || 1,
  view: { mode: view?.mode ?? current.view?.mode ?? "continuous" },
};
```

**答题卡的关键设计，默认不判分**

选完一题立刻显示对错，等于把答案摆在眼前，做题就失去意义。所以判分要有两个条件同时成立，有标准答案，且这一题的答案被显式展开过。

```js
const sheetState = { count: 55, answers: {}, revealed: new Set() };

const updateSheetStats = () => {
  let right = 0, wrong = 0;
  for (const [q, mine] of Object.entries(sheetState.answers)) {
    if (!mine || !correct[q] || !sheetState.revealed.has(q)) continue;  // 没展开就不计入
    if (mine === correct[q]) right += 1; else wrong += 1;
  }
};
```

`revealed` 只存在内存里，刷新就清空。这个「刷新后重新藏起来」的行为是有意的。

另外题量（`count`）只决定界面排多少格，不影响已存数据。把 55 改成 30 再改回来，第 31 到 55 题的作答还在。

**验收四件事**

1. 写笔记时直接关掉浏览器，重开笔记还在（防抖 600ms 内可能丢最后一句，这是有意的取舍）。
2. 用 `curl` 往 `/api/sheet` 塞 `{"answers":{"abc":"ZZZZZZ"}}`，服务端返回 `answered: 0`，文件没有被污染。
3. 答题卡选完十题，刷新，十题都还在，且没有任何一题显示对错。
4. 看解析 PDF 时翻页，回到试题，试题的阅读进度没有被解析的页码覆盖（`state.viewing !== "paper"` 时跳过保存）。

---

### 阶段 6 · 文字层、查词、圈画（这一段是「好用」和「能看」的分界线）

#### 6.1 铺文字层

`page.render` 之后，再渲一次 `TextLayer`。

```js
const renderText = async (view, page, viewport) => {
  view.textEl.replaceChildren();
  view.textTask = new pdfjsLib.TextLayer({
    textContentSource: page.streamTextContent(),
    container: view.textEl,
    viewport,
  });
  await view.textTask.render();
};
```

此时页面上已经可以用鼠标选中文字、`Ctrl+F` 搜索。但还不能「点词」。

#### 6.2 把每个英文单词切成可点元素

站点原来的做法是把 `innerText` 用正则包成自定义标签，本地实现叫 `wordify`，比原版多一步转义顺序的处理。

```js
const WORD_RE = /[A-Za-z][A-Za-z'’-]*/g;

const wordify = (text) => {
  let out = "", last = 0;
  for (const match of text.matchAll(WORD_RE)) {
    out += escapeHtml(text.slice(last, match.index));   // 先转义非单词部分
    out += `<aw>${escapeHtml(match[0])}</aw>`;          // 单词单独包
    last = match.index + match[0].length;
  }
  return out + escapeHtml(text.slice(last));
};
```

顺序很重要。如果先 `innerHTML` 拼好再转义，`&amp;` 里的 `amp` 会被正则当成一个单词切出来；如果先转义整段再跑正则，`&amp;` 变成 `&amp;amp;`，正则又会在 `amp` 上命中。**先切分、各自转义、再拼接**，三个动作分开做。

只处理叶子 `span`（有子元素的 span 是定位容器，动了会乱版），长度小于 2 或没有两个连续字母的跳过。

点击用事件委托挂在容器上，不挂在每个 `<aw>` 上。一套卷子有几千个词，逐个绑监听器会明显拖慢首屏。

```js
pagesEl.addEventListener("click", (event) => {
  if (ink.tool !== "cursor") return;
  const node = event.target.closest?.("aw");
  if (!node) return;
  // 用户正在划选一段话时不要弹窗，否则每次划词都会被查词框打断
  const selection = window.getSelection();
  if (selection && !selection.isCollapsed && selection.toString().trim()) return;
  showDict(node.textContent.trim(), node);
});
```

#### 6.3 词库

小规模和大规模两条路，先做小的。

**小规模**（2 万词，够用），扫所有 PDF 抽词表，再拿 ECDICT 裁剪。

```bash
python tools/collect-words.py     # 扫 read.pdf → data/wordlist.json
python tools/build-dict.py        # wordlist + ecdict.csv → data/dict.json（约 2.5 MB）
```

查词时先查原词，没命中查变形映射（`books → book`、`went → go`），再没命中就返回 `hit: false`，前端如实显示「词库里没有这个词，可能是人名或专名」。**不要编一个释义糊弄用户**，这一点在自用工具里同样重要，查错词比查不到更浪费生命。

**大规模**（77 万词，基本不会查不到），转 SQLite。

```bash
python tools/build-dict-full.py --source .cache/ecdict.csv --out data/dict.db
```

ECDICT 的 `exchange` 字段形如 `p:went/d:gone/i:going/3:goes`，键是变形类型，值是该词条的变形。反过来建 `form → lemma` 索引，遇到 `0:go` 表示「本词是 go 的变形」。

```python
if key == "0":
    forms.append((word.lower(), value))        # 本词 → 原形
elif key in FORM_KEYS:
    forms.append((value.lower(), word))        # 变形 → 本词
```

服务端用 `node:sqlite` 的 `DatabaseSync` 预编译四条语句，只读打开，不加载全表。

```js
const { DatabaseSync } = await import("node:sqlite");
dictDb = new DatabaseSync(dbPath, { readOnly: true });
dictPrepared = {
  word: dictDb.prepare("SELECT word, k, t, d, pos, tag FROM w WHERE word = ?"),
  form: dictDb.prepare("SELECT lemma FROM f WHERE form = ?"),
  like: dictDb.prepare("SELECT word FROM w WHERE word LIKE ? ORDER BY length(word) LIMIT 8"),
};
```

`node:sqlite` 在 Node 22 上是实验特性，可能需要 `--experimental-sqlite`；Node 24 直接可用。代码里对打开失败做了兜底，退回 `dict.json`，所以老 Node 上只是候选词少一点，不会崩。

那八条 `like` 查询是给「查不到」准备的。查 `disciplined` 没命中变形表时，按前缀给出 `discipline / disciplinary / disciplinarian`，用户点一下就能查对的那个。

#### 6.4 圈画，坐标存 0~1 是唯一正确的选择

三层 canvas 叠着，笔迹画在中间那层透明 canvas 上。

```css
.page { position: relative; }
.inkLayer { position: absolute; inset: 0; z-index: 1; }
.page:not(.drawing) .inkLayer { pointer-events: none; }   /* 光标模式下别挡文字层 */
.page.drawing .textLayer { pointer-events: none; }       /* 画笔模式下别抢事件 */
```

坐标处理是全部关键。存设备像素，换个缩放比例就全错位；存 CSS 像素，换 DPR 也会错。唯一稳的存法是**相对页面的比例**。

```js
const pointOf = (event, view) => {
  const box = view.el.getBoundingClientRect();
  return [
    Math.min(Math.max((event.clientX - box.left) / box.width, -0.02), 1.02),
    Math.min(Math.max((event.clientY - box.top) / box.height, -0.02), 1.02),
  ];
};
```

线宽同理，存「占页宽的比例」（约 0.0022，荧光笔 0.02）。画的时候再乘回去，放大缩小时笔迹会跟着纸一起变粗变细，视觉上才自然。

```js
ctx.lineWidth = Math.max(0.6, stroke.w * width);
```

画线用二次贝塞尔平滑。直接 `lineTo` 每个点，手抖的锯齿很明显。

```js
ctx.moveTo(points[0][0] * width, points[0][1] * height);
for (let i = 1; i < points.length - 1; i += 1) {
  const [x1, y1] = points[i];
  const [x2, y2] = points[i + 1];
  ctx.quadraticCurveTo(x1 * width, y1 * height, ((x1 + x2) / 2) * width, ((y1 + y2) / 2) * height);
}
```

橡皮不是「画白色」，是「删掉命中的整笔」。判据是点到线段的距离小于阈值。

```js
const distanceToStroke = (stroke, point) => {
  let best = Infinity;
  for (let i = 1; i < stroke.p.length; i += 1) {
    const [x1, y1] = stroke.p[i - 1], [x2, y2] = stroke.p[i];
    const dx = x2 - x1, dy = y2 - y1;
    const lenSq = dx * dx + dy * dy;
    const t = lenSq === 0 ? 0 : Math.min(Math.max(((point[0] - x1) * dx + (point[1] - y1) * dy) / lenSq, 0), 1);
    best = Math.min(best, Math.hypot(point[0] - (x1 + t * dx), point[1] - (y1 + t * dy)));
  }
  return best;
};
```

采样点要做距离过滤，`hypot < 0.0015` 的点直接丢弃，不然一笔能存几千个点，`ink.json` 迅速膨胀。

**验收三件事**

1. 在 50% 缩放下圈住一句话，切到 200%，笔迹仍然贴在原来的字上。
2. 点任意一个单词，浮层出现音标和释义；点人名（比如 `Kohler`），浮层如实说词库里没有。
3. 关掉页面再打开，笔迹还在，且没有错位。

第 1 条如果做不到，回去检查 `pointOf` 有没有除以 `box.width`。

---

### 阶段 7 · 数据流水线（占全部工作量六成）

前面六个阶段只要 `data/` 里有一套卷子就能跑。现在把一套变成一百套。

流水线的通用原则，五条，违反任何一条都会在某个时刻反噬。

**只增不删。** 所有脚本都只写新文件、只补字段。新增一套不该让已有九十九套的进度消失。
**已存在就跳过。** 重复跑只会补失败的，不会重下一遍 1.3 GB。
**先探测再落地。** URL 后缀不可信，字节数不可信，「100% 完整」的清单也不可信，落盘前嗅一次。
**宁可缺，不要错。** 抽不出答案就留空不判分；格式不明就跳过不猜。
**写索引用原子写。** `papers.json` 是 140 KB 的单文件，写坏一次全站打不开。

#### 7.1 清单驱动下载（`tools/ingest.mjs`，405 行）

适用场景是「有一份人工验证过的直链清单」（Markdown 表格），要把它们搬进 `data/`。

流程六步。

**第一步，解析清单。** 清单是分层 Markdown，`## CET6 2025.12` 开考次，`**试题**` 开类别，`- \`url\` 名字 [200]` 是条目。

```js
let m = line.match(/^## CET6 (\S+)/);          if (m) { sess = m[1]; cat = null; continue; }
m = line.match(/^\*\*(.+?)\*\*/);               if (m && sess) { cat = m[1]; continue; }
m = line.match(/^- `(\S+)`\s+(.+?)\s+\[(\d+)/); if (m && sess && cat) rows.push({ sess, cat, url: m[1], name: m[2], status: Number(m[3]) });
```

**第二步，认出这条链接属于第几套。** 这一步的难点是文件名不统一，有 `cet6_2022_09_2-3.pdf` 这种合订本，有「全 3 套」这种打包，也有只有「第N套」这种中文描述。

```js
const setsOf = (row) => {
  let m = decoded.match(/\/cet6\/(\d{4})_(\d{2})_(\d)(?![0-9])/);
  if (m) return [Number(m[3])];

  m = decoded.match(/cet6_(\d{4})_(\d{2})_(\d)(?:-(\d))?(?=[_.\-])/);   // 合订本
  if (m) {
    const from = Number(m[3]), to = m[4] ? Number(m[4]) : from;
    const out = [];
    for (let i = from; i <= to && i <= 9; i += 1) out.push(i);
    return out;
  }

  m = hay.match(/第\s*([1-3一二三])\s*套/);
  if (m) return [CN_NUM[m[1]]].filter(Boolean);

  m = hay.match(/全\s*([1-9一二三])\s*套/);
  if (m) return CN_NUM[m[1]] === 1 ? [1] : [];    // 三套合订本不映射到单独一套
  return [];
};
```

认不出来返回空数组，宁可漏一条，也不要把合订本错配成第 2 套然后覆盖掉真正的第 2 套。

**第三步，嗅真实格式。** 每个候选链接发一个 `Range: bytes=0-15` 的请求，拿到前 16 字节和总长度。

```js
const sniff = async (url) => {
  const res = await fetch(url, { headers: { Range: "bytes=0-15" }, signal: AbortSignal.timeout(60_000) });
  if (!res.ok && res.status !== 206) return null;
  const buf = Buffer.from(await res.arrayBuffer());
  const total = Number(res.headers.get("content-range")?.split("/")[1] ?? res.headers.get("content-length") ?? 0);
  return { magic: buf, bytes: total };
};
```

这一步同时解决了两个问题，格式不对的链接能当场筛掉，总字节数也能在下载前汇总（`--dry` 会打印「预计下载 1.3 GB」）。

**第四步，同一套里挑一条最优。** 评分维度是「真实格式是否匹配」优先于「源站优先级」。

```js
const SRC_ORDER = ["A", "C", "B", "D", "E", "G", "H", "I", "J", "M", "Z"];
const score = (entry) => wanted.indexOf(entry.format);    // wanted 例如 ["pdf"]
const usable = probed.filter((e) => score(e) >= 0);
usable.sort((a, b) => (score(a) - score(b)) || (rank(a.row) - rank(b.row)));
```

A 源（1e5e11）最全，C 源（0609x）次之，B 源（cettong）三件套规整但音频名不实。源优先级写成一个数组，改顺序就改策略，不用改逻辑。

**第五步，下载并落盘。** 重试五次，指数退避，先写 `.part` 再 rename。

```js
for (let attempt = 0; attempt < 5; attempt += 1) {
  if (attempt) await new Promise((done) => setTimeout(done, 1500 * attempt));
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(300_000) });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const buf = Buffer.from(await res.arrayBuffer());
    if (!buf.length) throw new Error("空文件");
    await mkdir(dirname(dest), { recursive: true });
    await writeFile(`${dest}.part`, buf);
    await rename(`${dest}.part`, dest);
    return { bytes: buf.length, sha256: sha256(buf), format: formatOf(buf.subarray(0, 16)) };
  } catch (error) { lastError = error; }
}
```

三分钟超时、五次重试、退避，是针对 GitHub raw 的脾气调出来的。raw.githubusercontent 对并发很敏感，大文件经常被重置（表现为 `terminated`），不加退避反而更容易全挂。

**第六步，收尾两件事。** 给没有独立音频的套写 `audioRef`，然后把索引原子写回。

```js
let sharedCount = 0;
for (const t of targets) {
  if (hasOwnAudio(t)) continue;
  const donor = targets.find((o) => o !== t && o.period === t.period && hasOwnAudio(o));
  if (!donor) continue;
  meta.audioRef = donor.id;
  meta.audioRefNote = "本套没有独立可下载音频，复用同考次听力素材";
  sharedCount += 1;
}
```

**验收三件事**

```bash
node tools/ingest.mjs --dry                # 打印每一套的「试题✓pdf 解析✓pdf 听力✓mp3」与总字节
node tools/ingest.mjs --only 2019.06       # 只灌一个考次
node tools/ingest.mjs                      # 全量
```

1. `--dry` 的输出里，`试题✗` 的那几套和预期一致（源站本来就没有）。
2. 跑完 `data/cet6/2019-06/` 下有三个文件加一个 `meta.json`，`sha256` 与 `bytes` 都对得上。
3. 再跑一遍，全程输出「跳过」，网络流量为零。

#### 7.2 本地目录入库（`tools/ingest-cet4.mjs`）

四级那批是已经整理好的本地目录，`CET4_近十年/<YYYY-MM>/第N套/{试卷,答案解析,听力}/*`。这时不需要下载，只需要把文件名规整成工作台认的那几个。

```js
// 硬链接优先，跨盘失败退回复制
const linkOrCopy = async (src, dest) => {
  await mkdir(dirname(dest), { recursive: true });
  if (existsSync(dest)) return "skip";
  try { await link(src, dest); return "link"; }
  catch { await copyFile(src, dest); return "copy"; }
};
```

硬链接的好处是同一份字节在磁盘上只占一份空间，源目录删了也不影响（因为 link 计数还在）。跨盘符时硬链接会失败，退回 `copyFile`。

这套脚本是「本地已有素材」的模板。**如果你手上的资料是整理好的文件夹，照着这个写，别去写爬虫。**

#### 7.3 网页归档 → 带文字层的 PDF（`tools/tem/`，这是全项目最巧的一段）

有些卷次公开渠道只有网页（当年的真题站存档），没有 PDF。网页没法直接进阅读器，得先变成 PDF。而「截图转 PDF」不行，那种 PDF 没有文字层，不能选中、不能查词、不能用文字层切词。

正确做法是**抽文字 → 重新排版 → 让浏览器打印**。浏览器打印出来的 PDF 有真实文字层。

**第一步，从 HTML 里找到正文（`extract.py`）**

不依赖原站 CSS，只做四件事，删噪音、找正文容器、合并碎片行、砍掉页头页脚。

找正文容器靠一份常见选择器名单，按可信度排，取文本最长的那个。

```python
CONTENT_SELECTORS = [
    "article",
    ".article-content", ".article_content", ".articleCon", ".artContent",
    ".content", "#content", ".main-content", ".post-content", ".entry-content",
    ".detail-content", ".news-content", ".TRS_Editor", ".text", ".art_context",
    ".article", ".detail", ".newsContent", "#artibody", ".article-body",
]
```

删噪音分两层。先按标签删（`script/style/nav/header/footer/aside/form/button…`），再按 class 和 id 正则删（`nav|menu|footer|sidebar|share|comment|related|advert|banner|breadcrumb|copyright`）。

合并碎片行是个细节活。很多站点把每个短句塞进独立的 `<p>`，抽出来是一行一句。判据只看标点，上一行没有句末标点就是这句没说完，直接接上；上一行写完了但下一行以小写开头，也是被硬折的同一句。题型标题、题号、选项一律不参与合并。

```python
KEEP_ALONE = re.compile(r"^(PART\b|SECTION\b|Section\b|Part\b|[A-D][\).、]|\d{1,3}[\).、]|…)")

if prev and not KEEP_ALONE.match(line):
    ends_sentence = re.search(r"[.。!?！？:：;；]\"?'?$", prev)
    if not ends_sentence:
        out[-1] = glue
        continue
```

砍页头页脚用「正文起止标记」。起点是试卷标题或第一个 PART（大小写不统一，`PART I` / `Part Ⅰ` 都要认），终点是「责任编辑」「相关阅读」「免责声明」这类。

```python
BODY_START = re.compile(r"(TEST\s+FOR\s+ENGLISH\s+MAJORS|TEST\s+FOR\s+ENGLISH|PART\s+(?:I|1|Ⅰ)\b|Part\s+(?:I|1|Ⅰ)\b)", re.I)
BODY_END = re.compile(r"(【编辑|（责任编辑|\(责任编辑|相关阅读|相关文章|阅读排行榜|网友热搜|热门推荐|上一篇：|下一篇：|声明：|免责声明|转载注明)")
```

**顺序有讲究**，先 `unwrap` 合并碎片，再 `trim_body` 找起止。反过来做，站点头部的「发布时间 / TEST FOR / ENGLISH MAJORS」被拆成三行，就认不出正文该从哪开始了。

**第二步，分块（`build_paper_pdf.py`）**

拿到纯文本之后，要判断每一行是什么，标题、题干、选项、正文。四种类型，四条判据。

```python
RE_PART = re.compile(r"^(PART|SECTION)\b")       # 题型标题
RE_QUESTION = re.compile(r"^\d{1,3}[.)、]\s*")    # 题干
RE_OPTION = re.compile(r"^[A-D][).、]\s+")        # 选项
# 剩下的是正文，按标点决定接上一段还是另起
```

难的是网页常把「PART I DICTATION [10 MIN] Listen to the following…」挤在一行，标题后面紧跟指令。得把标题切出来、剩下的当正文。切的位置用「指令开始词」判断。

```python
TAIL_STOP = re.compile(r"\b(Listen to|In this section|You will hear|Now listen|Questions?\s+\d|Write|Read the following|There are)\b")
```

还有一类是整篇只有一行（回忆版常见），得先按句子切成不超过 520 字一段，否则整卷变成一个巨大的 `<p>`。

**第三步，无头浏览器打印**

排版用「一行一段 HTML + 一份打印专用 CSS」，然后让 Edge 自己吐 PDF。

```python
cmd = [
    find_browser(),
    "--headless=new",
    "--disable-gpu",
    "--no-first-run",
    "--no-pdf-header-footer",         # 不加这行，页脚会印上 file:/// 和日期
    f"--user-data-dir={profile}",     # 临时 profile，避免和你正在用的浏览器抢锁
    f"--print-to-pdf={pdf_path}",
    html_path.as_uri(),               # 必须绝对路径，Edge 是独立进程，cwd 不是你的 cwd
]
subprocess.run(cmd, capture_output=True, text=True, timeout=180)
```

打印 CSS 里三个关键点。

```css
@page { size: A4; margin: 16mm 15mm 15mm 15mm; }
p { text-align: justify; }
p.q, h2.part { page-break-after: avoid; }   /* 题干和标题不要孤零零留在页底 */
```

`page-break-after: avoid` 是排版质感的关键。不写它，会出现「题干在页底、选项在下页」这种断法。

生成完用 PyMuPDF 验一下有没有文字层，这是必须做的。

```python
import pymupdf
doc = pymupdf.open("read.pdf")
text = "".join(p.get_text() for p in doc)
assert len(text) > 3000, f"只有 {len(text)} 字，可能打成了图片"
```

**验收三件事**

```bash
python tools/tem/extract.py --probe "../tem4_archive/collected/2016/*.html"
python tools/tem/ingest-tem.py --exam tem4 --dry
python tools/tem/ingest-tem.py --exam all
```

1. `--probe` 打印每份文件用的选择器、抽到的字数、开头 160 字。开头是试卷标题而不是「首页 登录 注册」，说明 `trim_body` 生效了。
2. `--dry` 里每一套的「卷✓/✗ 解析✓/✗ 听力✓/✗」和你手上的素材对得上。
3. 生成的 `read.pdf` 在阅读器里能选中文字、能点词。这一条不成立，前面两步全白做。

**这一步必须诚实标注质量。** 网页抽出来的卷子常常缺题型（2015 专四只有听写和听力），回忆版不是原卷。`meta.json` 里写清楚。

```python
def quality_from_text(text, fallback, exam="tem4"):
    parts = set(detect_parts(text))
    core = {"listening", "reading", "writing"} if exam == "tem4" else {"listening", "reading", "translation", "writing"}
    missing = [k for k in core if k not in parts]
    if "listening" in missing or "reading" in missing:
        return "不全（缺听说读写主干，只能当参考资料）"
    return "完整" if not missing else "部分（缺" + "、".join(PART_CN[m] for m in missing) + "）"
```

界面上读作「部分（缺完形、翻译）」，比假装完整有用得多。

#### 7.4 扫描件补隐形文字层（`tools/ocr/ocr-pdf.py`，157 行）

有一批卷子是纯图片 PDF，选不中、搜不到、查不了词。不必重新排版，只要**在原位置上叠一层看不见的文字**。

```python
# 1. 按 200 dpi 渲染成图
pix = page.get_pixmap(dpi=200)
pix.save(png)

# 2. RapidOCR 识别每一行（英文模型）
engine = RapidOCR(params={"Det.lang_type": "en", "Rec.lang_type": "en"})
result = engine(str(png))
boxes, texts = result.boxes, result.txts

# 3. 按原坐标以「不可见模式」写回去
scale = 72.0 / 200            # 图像像素 → PDF 点
page.insert_text(
    pymupdf.Point(x0 * scale, y1 * scale - 1),
    clean,
    fontsize=max(4.0, height * scale * 0.82),
    fontname="helv",
    render_mode=3,            # 这一行是关键：3 = 不可见
    color=None,
)
doc.saveIncr()                # 增量保存，原内容不动
```

四个坑。

`render_mode=3` 是 PyMuPDF 的「隐形文字」模式，页面上完全看不出来，但文字层里真实存在，pdf.js 能选中、能框词。
内置 `helv` 字体只有拉丁字形，写中文会整行失败，所以先过滤成纯 ASCII。
`saveIncr()` 只追加不改写，配合事前备份到 `.cache/ocr/backup/`，出问题能回滚。
同一套不允许两个进程同时跑（都在对同一个文件 `saveIncr()`），批量前先看一眼进程列表。

判断哪些页要 OCR，分两层。整本前 3 页合计不到 200 字，当扫描件，全书都交出去；否则只挑单页不到 120 字的那几页。这样重跑是幂等的，不会给已经补好的页盖第二层。

```python
SCAN_THRESHOLD = 200      # 前 3 页可用字符数
PAGE_MIN_CHARS = 120      # 单页低于这个字数就当这页没字
```

代价是慢。CPU 上大约 20 秒一页，136 页跑了一小时出头。这是可以接受的，因为只跑一次。

**验收两件事**

1. `python tools/ocr/ocr-pdf.py --list` 列出的待补页数和你估计的一致。
2. 补完之后，同一页在阅读器里能选中文字，**页面上看不出任何变化**（截图对比，或者直接盯着看）。

#### 7.5 答案与逐题解析

**答案有三种来源，可靠性从高到低。**

来源一，站点自己的解密能力（六级 61 套）。思路是「不逆向算法，直接借它的 Worker 干活」。站点把答案密文内联在试卷页的 `globalConfig.newAnswer` 里，解密由它自己的 Web Worker 完成。所以在已登录的同源页面里抓 HTML、抠出密文、扔给它自己的 Worker，就能拿回明文。

三个前提，一个已登录的浏览器开着调试端口，调用处在同源页面，Worker 路径没变。

```js
// 抠密文不能正则，字符串里有 ]，要按括号配平
const start = html.indexOf('"newAnswer"');
const braceStart = html.indexOf("{", start);
let depth = 0, end = -1, inStr = false, esc = false;
for (let i = braceStart; i < html.length; i++) {
  const c = html[i];
  if (inStr) { if (esc) esc = false; else if (c === "\\") esc = true; else if (c === '"') inStr = false; continue; }
  if (c === '"') { inStr = true; continue; }
  if (c === "{") depth++;
  else if (c === "}") { depth--; if (depth === 0) { end = i + 1; break; } }
}
```

拿到的明文是 `["1-C", "2-B", …]`，落盘前转成本地格式。

```bash
node tools/fetch-answers.mjs 9223          # 需要 9223 上开着已登录的 Edge
node tools/distribute-answers.mjs          # 拆成每套的 answers.json
```

`distribute-answers.mjs` 做两件事，把 `"1-C"` 拆成 `{"1":"C"}`，同一题号重复时以最后一次为准。每取 10 套落一次盘，中断不白跑。

来源二，归档答案解析页里抽（专四专八 7 套）。只认两种写得直白的格式，`1-5 CDBAC` 和 `1. C 2. A`。抽完自己校验，区间必须连续、每题只能有一个答案、总数至少 15 题，任何一条不满足整套跳过。

```python
def is_sane(answers: dict[int, str]) -> bool:
    if len(answers) < MIN_COUNT: return False
    numbers = sorted(answers)
    span = numbers[-1] - numbers[0] + 1
    allowed_gap = max(3, int(span * 0.15))
    return len(numbers) >= span - allowed_gap
```

**这条「宁缺勿错」的规则要写进代码，不能只写在注释里。** 一套卷子 15 套没答案，界面上显示「本地还没有答案，只记录作答」，比给一份错答案好得多。

来源三，解析 PDF 里抽（不可靠，最后才用）。2013 到 2015 那批卷子的 `analysis.pdf` 里覆盖不到 20 题，2015 还是扫描件，硬抽会把题干选项当成答案。**这类一律留空**，`answers.json` 干脆不生成。

**逐题解析的抽取（`build-analysis.py`，297 行）**

把 `analysis.pdf` 的文字按页摊平，用四个正则识别结构。

```python
PART_RE = re.compile(r"^Part\s+([IVX]+)\s*(.*)$")
SECTION_RE = re.compile(r"^Section\s+([ABC])\b\s*(.*)$")
QUESTION_RE = re.compile(r"^(\d{1,2})[.、]\s+(\S.*)$")
PASSAGE_RE = re.compile(r"^Passage\s+(One|Two)\b[—\- ]*(.*)$", re.I)
```

难点是跨行合并。PDF 里一句解析被折成三行，合的时候中英文之间不能乱加空格，行尾连字符要判断是断词还是复合词。

```python
if out.endswith("-") and re.search(r"[A-Za-z]-$", out):
    merged = (head + tail_word).lower()        # selfdiscipline
    hyphenated = f"{head}-{tail_word}".lower() # self-discipline
    if tail_word and word_exists(merged) and not word_exists(hyphenated):
        out = out[:-1] + line                  # 是断词，接上
    else:
        out += line                            # 是复合词，保留连字符
```

`word_exists` 查的是 `data/dict.db`。**这里体现了词库的第二个用途**，它不只是给用户查词，也是文本处理的判据。

听力部分比较特殊。官方 `analysis.pdf` 对听力通常只给「答案 + 概要」，没有逐题解析。所以逐题解析走补充数据 `tools/listening/<套卷id>.json`，结构是原文分段加题干选项。

没有补充数据时，那 25 题照样挂上答案，但标 `note: "pending-transcript"`，界面上显示「这一套听力只提供答案，暂无逐题解析」。等拿到原文再补，不要编。

#### 7.6 词库与汇总

三条命令，顺序不能反。

```bash
python tools/collect-words.py     # 扫所有 read.pdf 抽词 → data/wordlist.json
python tools/build-dict.py        # 裁剪 → data/dict.json（2.5 MB）
python tools/build-dict-full.py   # 全量转 SQLite → data/dict.db（82 MB）
```

加了新卷子之后要重跑 `collect-words`，否则新卷子里的词在精简词库里查不到。用全量 `dict.db` 就没这个问题，代价是 82 MB 磁盘。

还有一条汇总命令，把散在 173 个目录里的笔记、错题、生词拼成一份可打印的复习总纲。

```bash
node tools/collect-notes.mjs      # → data/notes-all.md
```

它只读文件系统，不需要服务在跑。**这是「数据用文件存」的红利**，写个脚本就能把全部数据重新组织一遍，不用求 API 支持。

---

### 阶段 8 · 质检与运维

自用工具最容易烂在「改完不知道有没有改坏」。所以要有三条防线。

**第一道，静态检查（`tools/check.mjs`，41 行）**

把所有 `.js` / `.mjs` 过一遍 `node --check`。

```js
for (const file of files) {
  try {
    execFileSync(process.execPath, ["--check", join(ROOT, file)], { stdio: "pipe" });
    console.log(`ok   ${file}`);
  } catch (error) {
    failed += 1;
    console.log(`FAIL ${file}\n${String(error.stderr).trim()}`);
  }
}
```

为什么需要这个。真实事故是「调格式时把注释和下一行合并成一行，后半句变成注释内容」，某个接口运行时才炸 500，报 `limit is not defined`。静态检查当场拦住。

**第二道，只读体检（`tools/status.mjs`，109 行）**

不开服务，直接读文件系统，打印索引规模、每套的文件大小与进度、生词错题数量。它的第一行注释写明「这个脚本不写任何文件、不删任何东西」，因为早先有两个脚本会删 `progress.json`，用户数据丢过一次。

**第三道，浏览器真点一遍（`tools/browser-check.mjs`）**

查词和圈画全靠 DOM 事件和 canvas，静态检查看不出「文字层没切开」「笔迹没落盘」。这个脚本用 CDP 连一个 Chrome，点一个词、画一笔，然后读 `ink.json` 验证。

```bash
chrome --headless=new --remote-debugging-port=9333 --user-data-dir=<临时目录> about:blank
node tools/browser-check.mjs 9333 cet6/2024-06/01
```

**重启服务（`tools/restart-server.ps1`）**

改完后端要重启。这里有个反例值得记住，**不要按命令行模糊匹配杀进程**。

```powershell
# 曾经这么写，结果把两个不属于本项目的 node 一起杀了
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*server.mjs*" } | ...
```

正确做法是按端口或 PID 精确定位。`restart-server.ps1` 用 `Get-NetTCPConnection -LocalPort` 拿 OwningProcess，只杀那一个。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\restart-server.ps1 -Port 8787
```

另外，PowerShell 脚本要存成带 BOM 的 UTF-8，或者干脆只写 ASCII。Windows PowerShell 5.1 读没有 BOM 的 `.ps1` 会按 ANSI 解码，中文注释直接让脚本解析失败。

**启动器的三个小设计**

`start.bat` 里有三处值得抄。

找 node 时先 `where node`，找不到再试几个固定路径，最后给出可操作的提示（「装 Node 18+，或者改 start.bat 里的兜底路径」），而不是一句「找不到命令」。

端口被占自动顺延，8787 到 8799。

```bat
:findport
netstat -ano | findstr /r /c:":%PORT% .*LISTENING" >nul
if errorlevel 1 goto portok
set /a PORT+=1
if %PORT% gtr 8799 (echo 8787-8799 都被占用了 & pause & exit /b 1)
goto findport
```

等两秒再开浏览器。不等的话，浏览器比服务先起来，看到一次白屏。

```bat
start "zhenti-opener" /min cmd /c "ping -n 3 127.0.0.1 >nul & start http://127.0.0.1:%PORT%/index.html"
```

`start.sh` 里端口检测不能用 `netstat` 加 `findstr`，改用 node 试监听。

```bash
port_free() {
  "$NODE" -e "const s=require('net').createServer();s.once('error',()=>process.exit(1));s.listen(Number(process.argv[1]),'127.0.0.1',()=>s.close(()=>process.exit(0)));" "$1" >/dev/null 2>&1
}
```

---

## 3. 技术栈与实现细节

### 3.1 全表

| 层 | 技术 | 版本 / 形态 | 干什么 | 为什么是它 |
|---|---|---|---|---|
| 运行时 | Node.js | 22 或 24 | 服务端 + 所有 `.mjs` 工具 | 一台机器上不用装第二套运行时 |
| 服务 | `node:http` | 内置 | HTTP 服务、路由、静态、Range | 需求只有 6 个路由，框架是负担 |
| 服务 | `node:fs/promises` | 内置 | 读写题库与学习数据 | 文件系统即数据库 |
| 服务 | `node:sqlite` | 内置（22.5+） | 查 77 万词条词库 | 免装 better-sqlite3，只读查询够用 |
| 前端 | 原生 ES Module | 浏览器内置 | 三个页面，无构建 | 没有构建步骤，改完刷新即可 |
| 前端 | pdf.js | 4.10.38，vendored | PDF 渲染 + 文字层 | 唯一能同时给出 canvas 与可选文字层的方案 |
| 样式 | 原生 CSS | 509 行 | 全站 | 一个 CSS 变量控制侧栏宽度就够了 |
| 采集 | `fetch` | Node 内置 | 下载、嗅探、重试 | 不需要 axios |
| 采集 | CDP（WebSocket） | 80 行自写 | 借用已登录浏览器 | 无第三方依赖，Node 22 自带 WebSocket |
| 解析 | PyMuPDF | 1.24+ | 读 PDF 文字、渲染页、写隐形文字 | 比 pdfplumber 快，能改 PDF |
| 解析 | BeautifulSoup + lxml | 4.x | 从归档 HTML 找正文 | 选择器名单 + 长度打分，够用且稳 |
| 打印 | 无头 Edge / Chrome | `--headless=new` | HTML → 带文字层 PDF | 免装 wkhtmltopdf，文字层质量最好 |
| OCR | RapidOCR | PP-OCRv6 英文模型 | 扫描件转文字 | 离线、免 key，英文识别够准 |
| 排版 | ReportLab | 4.x | 重排卷面（进阶） | 精确控制字号行距，避免打印 CSS 的不可控 |
| 词库源 | ECDICT | 77 万条，MIT | 音标、释义、考纲标签、词形 | 唯一免费且带四六级/考研标签的中英词典 |
| 桌面端 | 无 | 不适用 | 浏览器直接开 | 见 3.2 的对比 |

### 3.2 为什么不用那些「更专业」的东西

| 常见选择 | 这个项目的做法 | 判断依据 |
|---|---|---|
| Express / Fastify | `node:http` + 手写路由 | 6 个 GET、7 个 POST。Express 省下的是路由和静态服务，加起来 70 行。为 70 行引入一个依赖树，三年后升级的风险大于收益 |
| React / Vue | 原生 DOM + 模板字符串 | 一次渲染 180 个卡片，`innerHTML` 重建耗时个位数毫秒。没有列表虚拟化需求，没有复杂状态同步 |
| `pdfjs-dist`（npm） | vendored 两个文件 | 不想有 `npm install`。而且 pdf.js 的 ESM 构建直接 `import` 就能用，bundler 在这里没有价值 |
| 现成播放器库 | `<audio>` + 60 行 | 需要的功能是倍速、±10s、AB 循环、记忆位置，全是原生 API。播放器库反而会封装掉 `currentTime` |
| SQLite 存所有数据 | 只有词库用 SQLite | 学习数据是「一套卷一个文件」，文件系统天然分片。用数据库反而要写迁移、要防并发、备份变成导库 |
| Electron / Tauri | 浏览器 + 本地服务 | 打包体积从 0 变成 60 MB 起，换来的是「不用开命令行」。自用工具，双击 `start.bat` 已经够 |
| Scrapy / Playwright 爬全站 | 清单驱动 + 一次性 CDP | 目标不是镜像全站，是按索引补齐。清单驱动可重跑、可断点、可审计；爬虫跑一遍出问题要重跑 |
| wkhtmltopdf | 无头 Edge | Edge 自带、支持现代 CSS、文字层质量好。wkhtmltopdf 对 flex 和 `@page` 支持糟糕 |

一句话总结取舍原则。**凡是「只用一次」的环节，选最省事的；凡是「每次打开都要跑」的环节，选最可控的。** 前者是 Python 工具，后者是那 2700 行前端与服务端。

### 3.3 80 行的 CDP 客户端

`tools/cdp.mjs` 是整个采集链路里最值得单独读的文件，因为它把「控制一个真实浏览器」压缩到了 80 行。

```js
export const connect = async (port, matcher = () => true) => {
  const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  const pages = targets.filter((t) => t.type === "page");
  const target = pages.find(matcher) ?? pages[0];

  const ws = new WebSocket(target.webSocketDebuggerUrl);
  const pending = new Map();
  let seq = 0;

  ws.addEventListener("message", (event) => {
    const msg = JSON.parse(event.data);
    if (msg.id && pending.has(msg.id)) {
      const entry = pending.get(msg.id);
      pending.delete(msg.id);
      if (msg.error) entry.reject(new Error(JSON.stringify(msg.error)));
      else entry.resolve(msg.result);
    }
  });

  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++seq;
    pending.set(id, { resolve, reject });
    ws.send(JSON.stringify({ id, method, params }));
  });

  const evaluate = async (expression) => {
    const result = await send("Runtime.evaluate", {
      expression,
      awaitPromise: true,      // 页面里返回 Promise 时会等它 resolve
      returnByValue: true,     // 结果转成 JSON，而不是对象句柄
      userGesture: true,       // 让事件被当成用户操作，绕过部分自动播放限制
    });
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.exception?.description ?? "页面执行出错");
    return result.result.value;
  };

  return { ws, send, on, evaluate, waitFor, navigate, close: () => ws.close() };
};
```

三个要点。

`awaitPromise: true` 让页面里的 `(async () => {...})()` 直接返回值。没有它，你拿到的是一个 Promise 句柄。
`returnByValue: true` 把结果序列化成 JSON。没有它，拿回来的是 `objectId`，还得再发一次请求取值。
`pending` 这个 Map 是请求与响应的配对表。CDP 的响应带 `id`，事件不带，所以「有 id 就 resolve，没 id 就是事件」这一条分支就够了。

有了它，`fetch-answers.mjs` 里那段「抓 HTML → 配平括号抠密文 → 扔给站点 Worker → 收明文」就变成了一次 `evaluate`。

### 3.4 为什么把 `viewer.js` 和 `read.js` 拆开

`viewer.js` 只干一件事，把 PDF 渲染出来。它不知道什么叫「笔记」「答题卡」「生词本」。需要外部世界的信息时，走依赖注入。

```js
export const createViewer = ({ scrollEl, pagesEl, paperId, api, flash, onChange, onStudyChanged, titleOf }) => {
  // 内部只调 api()、flash()、onChange()，不直接 fetch，不直接碰业务 DOM
};
```

`read.js` 负责业务，把 `api` 和 `flash` 传进去。

```js
const viewer = createViewer({
  scrollEl: $("viewerScroll"),
  pagesEl: $("pagesBox"),
  paperId,
  api,                                    // 统一带上错误处理的 fetch
  flash,                                  // 顶部一行提示，1.6 秒消失
  titleOf: () => state.paper?.meta?.title ?? paperId,
  onChange: () => scheduleSave(),          // 页码/缩放变了 → 防抖存进度
  onStudyChanged: async () => { study = await api("/api/study"); renderStudy(); },
});
```

收益很直接。答案解析要复用同一个阅读器（侧栏里放大看解析 PDF），如果 viewer 和业务耦合，就得写第二套渲染逻辑。拆分之后，`openAnalysisFullscreen()` 只是换了 URL 再 `load()` 一次。

```js
await viewer.load(`/data/${paperId}/${state.paper.analysisFile}`, { page: 1, zoomKind: "fitWidth" });
```

代价是 `viewer.js` 里出现了 `document.getElementById("dictPop")` 这种对全局 DOM 的直接引用。严格说这是漏抽象，但它省掉了十几层回调，对这个规模的工具是划算的。**如果哪天要把 viewer 抽成独立 npm 包，这十几处就是要先改的地方。**

### 3.5 文字层是怎么和 canvas 对齐的

pdf.js 的 `TextLayer` 干的事，比看起来复杂。它的做法是给每一段文字生成一个绝对定位的 `span`，位置和旋转由 PDF 里的文字矩阵算出来。

```js
new pdfjsLib.TextLayer({ textContentSource: page.streamTextContent(), container: view.textEl, viewport })
```

`viewport` 里带着当前 `scale`，所以 span 的位置已经按缩放算好了。但**字号不是**。4.x 版本把字号写成 CSS 表达式。

```css
.textLayer span { font-size: calc(var(--scale-factor) * 12px); }
```

所以缩放之后必须重设那个变量，否则所有 span 的字号还是旧比例，位置对但字形大小不对，选区会错位。

```js
view.textEl.style.setProperty("--scale-factor", String(state.scale));
```

文字层的 CSS 还有两条不能少。

```css
.textLayer { position: absolute; inset: 0; opacity: 0; line-height: 1; }
.textLayer span { color: transparent; }
.textLayer ::selection { background: rgba(106, 27, 154, .3); }
```

`opacity: 0` 而不是 `visibility: hidden`，因为后者会让文字无法选中；`color: transparent` 保留选中高亮；`line-height: 1` 防止行高把 span 撑开。

**文字层是「看不见但决定了能不能用」的一层。** 截图看不出它存不存在，所以测试方法只能是划选一段看选区是否贴合，或者 `Ctrl+F` 搜一个词。

### 3.6 解析 PDF 为什么放在侧栏，而不是新标签页

站点原来的做法是点「查看解析」跳转或弹窗，结果是你忘了刚才那道题在卷子哪一页。

这里的做法是**右侧栏内嵌一个独立的 pdf.js 实例**，主阅读器保持不动。

```js
const ana = { url: "", doc: null, zoom: 1, current: 1, pages: [], rendering: false, pending: false };
```

侧栏渲染同样要串行（一个 canvas 一条渲染队列的规则对每个实例都成立），但它的宽度是「侧栏宽度的倍数」，所以缩放逻辑和主阅读器不同。

```js
const anaWidth = () => Math.max(180, Math.round((($("anaScroll").clientWidth || 380) - 24) * ana.zoom));
```

只有「字太小看不清」时才点「全屏」，这时才切到左侧主阅读器，并且**先记住试题的页码与缩放**，返回时原样恢复。

```js
if (state.viewing !== "analysis") {
  state.paperView = { page: viewer.state.page, scale: viewer.state.scale,
                      zoomKind: viewer.state.zoomKind, mode: viewer.state.mode };
  state.viewing = "analysis";
  await viewer.load(`/data/${paperId}/${state.paper.analysisFile}`, { page, zoomKind: "fitWidth" });
}
```

`state.viewing` 这个字段还有一个副作用必须处理，看解析时不能存试题的阅读进度，否则会出现「读了半天解析，回到试题发现页码跳到第 1 页」。

```js
function saveProgress() {
  if (!paperId || state.viewing !== "paper") return;
  // …
}
```

**这类「一个字段影响两处行为」的地方，是自用工具最容易漏的。** 写的时候顺手在字段旁边注释清楚它同时在管什么。

### 3.7 性能账

三个数字决定了很多设计。

**180 套索引，每次打开首页要读 180 次 `existsSync`。** 单次大约 30 微秒，合计 5 毫秒，可以忽略。但如果每套都 `JSON.parse` 它的 `meta.json`，就变成 180 次磁盘读，冷启动会到 200 毫秒以上。所以 `localState()` 只在需要时读 `meta.json`（找 `audioRef` 时），其余状态全靠 `existsSync` 判断。

**一页 canvas 在 200% 缩放下是 1200×1600，4 字节每像素约 7.7 MB。** 一套 14 页全渲就是 107 MB，再乘以 DPR 的平方。所以只能渲可见页，且侧栏解析的 DPR 要封顶。

```js
const ratio = Math.min(window.devicePixelRatio || 1, 2);   // 侧栏解析，封顶 2
```

主阅读器不封顶，因为那是用户主动放大的，要清楚。

**一套卷子有 3000 到 6000 个单词。** 每个都绑监听器会让首屏明显变卡，所以用事件委托。同理，查词浮层的定位用 `getBoundingClientRect` 每次现算，不做缓存，因为滚动一次缓存就失效了。

### 3.8 安全边界（自用工具也要有）

绑 `127.0.0.1` 而不是 `0.0.0.0`。同一局域网的其他设备连不上，这是最简单也最有效的一条。

路径穿越用两道防线。正则先卡 `paperId` 的形状，再 `safeJoin` 卡解析后的绝对路径。

```js
const safeJoin = (base, relative) => {
  const target = resolve(base, normalize(relative).replace(/^([/\\])+/, ""));
  if (target !== base && !target.startsWith(base + sep)) return null;   // 逃出 base 就拒
  return target;
};
```

只卡字符串 `../` 不够，`%2e%2e%2f` 解码后一样能穿。所以 `decodeURIComponent` 之后必须走路径规范化 + 前缀比对。

请求体上限 1 MB。

```js
for await (const chunk of req) {
  size += chunk.length;
  if (size > 1_000_000) throw new Error("body too large");
  chunks.push(chunk);
}
```

不设上限，一个手滑的脚本 POST 一个 500 MB 的 JSON 就能把内存吃满。

词库以 `readOnly: true` 打开,`new DatabaseSync(dbPath, { readOnly: true })`。查询接口不该有写权限，这是最小权限原则里最容易做到的一条。

`fetch-answers.mjs` 那条链路涉及「用你自己的登录态「借」站点的解密 Worker」，边界写在 `README.md` 和 `docs/REVERSE-ENGINEERING.md` 里。只取你自己账号能看到的内容，不绕过设备绑定，不重写解密算法，不批量镜像。**这条线在技术上可以再往前一步，但项目刻意停在这里。**

---

## 4. 踩坑清单

按「现象 → 根因 → 解法」记，都是真踩过的。

| 现象 | 根因 | 解法 |
|---|---|---|
| 阅读器白屏，控制台无报错 | 标签页 `visibility: hidden` 时 pdf.js 的 `render().promise` 永不 resolve（内部依赖 rAF） | 排查先看 `document.visibilityState`；截图场景用 `--headless=new` 且别把窗口最小化 |
| 报 `Cannot use the same canvas during multiple render() operations`，之后整页卡死 | 翻页与缩放并发调同一个 canvas 的 `render()` | 渲染串行化，`renderVisible()` 的双层队列 |
| 缩放后点词的位置全错 | 文字层字号是 CSS 表达式，靠 `--scale-factor` 变量 | 每次 `applySizes()` 都重设该变量 |
| 笔迹放大后错位 | 坐标存了设备像素或 CSS 像素 | 存相对页面的 0~1，线宽存占页宽的比例 |
| 听力能播但不能拖进度条 | 服务端返回 200，没实现 206 与 `content-range` | 实现 Range，并始终带 `accept-ranges: bytes` |
| 音频播不了，控制台报解码错误 | 文件名 `.mp3`，内容是 AAC（`ftyp`） | 入库时嗅探文件头，按真实格式命名，MIME 用 `audio/mp4` |
| `progress.json` 变成 0 字节，进度丢失 | `writeFile` 直写目标文件，写到一半崩 | `.tmp` + `rename` 原子写 |
| 两次保存后数据倒退 | 两个 POST 并发，先发的后到，旧数据覆盖新数据 | Promise 链串行化，或服务端做合并写 |
| 第 3 套没有听力 | 官方多套共用一份音频，采集源里本来就没有 | `meta.audioRef` 指向同考次有音频的那套，服务端顺着找 |
| 一套卷子只有 26 题以后能判分 | 第 3 套的答案只提供后半段，前 25 题与前两套共用 | 如实留空，`answers.json` 里不写就没有判分，界面上不显示对错 |
| 扫描件选不中文字 | 纯图片 PDF，没有文字层 | OCR + `render_mode=3` 写隐形文字，`saveIncr()` 增量保存 |
| 打印出来的 PDF 页脚印着 `file:///...` 和日期 | 没关页眉页脚 | `--no-pdf-header-footer` |
| 打印出来的 PDF 没有文字层 | 用了「截图转 PDF」或 CSS 把文字渲成图 | 用浏览器 `--print-to-pdf`，生成后用 PyMuPDF 断言字数 |
| 题干和选项被切在两页 | 没有设置分页控制 | `p { page-break-after: avoid }` 加在题干与标题上 |
| `&amp;` 被切成单词 `amp` | 先拼 HTML 再转义，或先转义再切词 | 先按正则切分、各自转义、再拼接 |
| 划选一段话查词框老是弹出来 | 点击 `aw` 时没检查选区状态 | `selection && !selection.isCollapsed` 时不弹 |
| 侧栏折叠后播放条被裁掉 | flex/grid 子项 `min-height` 默认 `auto`，长内容把兄弟顶出视口 | `.viewer-scroll` / `.tabbody` / `.viewer-col` 显式 `min-height: 0` |
| 页码输入框断言永远读到 1 | `<input>` 的 `value` 属性不随 `.value` 变 | 另设 `<span id="pageLabel">` 供断言 |
| PowerShell 管道后 JSON 全乱码 | 原生命令输出经 `|` 走 GBK 重解码 | `cmd /c "node x.mjs > file"` 保留字节 |
| 精确杀进程变成杀掉自己 | `$PID` 是只读自动变量，赋值失败仍是当前 shell 的 PID | 变量别叫 `$pid`；按端口找 OwningProcess |
| `.ps1` 报「字符串缺少终止符」 | 无 BOM 的 UTF-8 被按 ANSI 读，中文注释破坏语法 | 存成带 BOM，或只写 ASCII |
| 改完代码某接口 500 `limit is not defined` | 调格式时把注释和下一行语句合成了一行 | 改完跑 `npm run check` |
| 重排脚本把内容弄丢一半 | 网页抽取把多个段落合成了一个 `<p>`，或分块判据过严 | 跑 `check_quality.py` 逐套比对原卷与重排版的文本量 |
| 两个 OCR 进程互相覆盖同一份 PDF | 都在对同一个文件 `saveIncr()` | 批量前检查 python 进程，或按目录加锁 |

---

## 5. 工作量与路线建议

按一个人、有素材、熟悉 JS 的前提估。

| 阶段 | 产出 | 依赖 | 大致投入 |
|---|---|---|---|
| 0 环境 | 目录骨架、pdf.js 就位 | 无 | 半小时 |
| 1 最小闭环 | 50 行服务 + 一页渲染 | 一份 PDF | 1 小时 |
| 2 索引与首页 | 索引文件 + `/api/papers` + 目录页 | 3 套以上素材 | 半天 |
| 3 阅读器内核 | 连续滚动、缩放、双页 | 阶段 1 | 一到两天 |
| 4 听力 | Range、倍速、AB、位置记忆 | 音频素材 | 半天 |
| 5 学习数据 | 进度、笔记、答题卡、生词错题 | 阶段 2 | 一天 |
| 6 文字层与圈画 | 查词、笔迹、词库 | 阶段 3、6.3 词库 | 两到三天 |
| 7.1 清单下载 | `ingest.mjs` | 一份验证过的直链清单 | 一到两天 |
| 7.3 网页转 PDF | 抽取、重排、打印 | Python + Edge | 两到三天 |
| 7.4 OCR | 隐形文字层 | RapidOCR | 一天（跑起来很慢，写代码快） |
| 7.5 答案与解析 | 三种来源 + 逐题解析 | 阶段 7.1 | 两到三天 |
| 8 质检 | 三条防线 + 启动器 | 全部 | 一天 |

**一条重要的建议，先做「能用的一套」，再做「一百套」。** 阶段 1 到 6 全程只需要一套卷子。很多人卡在「先把 180 套下下来」，结果素材还没齐就失去了兴趣。反过来，一套卷子把所有交互打磨顺了，后面批量灌数据只是跑脚本。

阶段 7 里最容易被低估的是 7.3（网页转 PDF）。原因是垃圾进垃圾出，抽取质量差一点，后面每套都要人工看一遍。**抽取脚本写完，一定要抽 5 套不同来源的卷子目视检查，再批量跑。**

---

## 6. 换一个题库怎么改

这套架构和「英语真题」没有强绑定。换成法考题、考研数学、驾照题库、公司内部培训材料，改动量如下。

**不用改的（80%）**

`server.mjs` 全部逻辑、`viewer.js` 全部逻辑、原子写、Range、答题卡、进度、笔记、生词本、圈画、质检工具。

**要改的（20%）**

| 位置 | 改什么 | 说明 |
|---|---|---|
| `papers.json` 的 `exams` | 换成你的分类 | `id` 保持小写英文，`short` 是页签上的两三个字 |
| `app.js` 的 `EXAM_FALLBACK` | 同上 | 索引里有就用索引的，这里只是兜底与排序 |
| `read.js` 的 `SECTIONS` | 题型分段表 | 只对题号固定的考试有意义。题号不固定就返回 `null`，界面上不显示分段标题 |
| `read.js` 的 `optionsFor()` | 选项范围 | 英语是 A–D 与 A–O，别的题库可能是 A–F 或者判断题 |
| `tools/` 的采集脚本 | 换成你的数据源 | 结构照 7.1 抄，只改解析清单和挑文件的规则 |
| `meta.json` 的字段 | 加你的元信息 | 比如「科目」「难度」「考点」，前端不认识的字段会被忽略，不会报错 |
| 词库 | 换成你的词典 | 英语用 ECDICT；别的语种换成对应词典，表结构照 `w` / `f` 两张表 |

**最需要重写的部分**是「把素材变成 `data/` 结构」的那一段。你的素材可能是 Word、可能是扫描件、可能是某个系统的导出，抽取逻辑必然不同。但抽取的**输出契约**不变，仍然是 `read.pdf` + `listen.*` + `analysis.pdf` + `meta.json`。

**判断能不能复刻的最短路径**，先问一句「我的素材能不能变成『一个带文字层的 PDF 加一个音频文件』」。能，这套架构直接套；不能（比如资料是交互式 HTML 题库），要改的是阅读器那一层，工作量翻倍。

---

## 7. 交付前自测清单

照着勾，全过才算是复刻完成。

**基础**

- [ ] `node server.mjs --port 8787` 能起，`127.0.0.1:8787` 能开
- [ ] 端口被占时自动顺延，不报错退出
- [ ] `start.bat` 双击能起，且浏览器不是白屏
- [ ] 首页列出所有已收录套卷，未收录的压成芯片
- [ ] 在 `data/` 手动加一套，刷新即出现，**没改任何代码**
- [ ] 搜索 `2025-12`、`第2套`、`六级` 都能命中

**阅读器**

- [ ] 滚到最后一页，中间无长时间白块
- [ ] 连点放大十次，无 `Cannot use the same canvas`
- [ ] 缩放前后视线停在同一段文字上
- [ ] 双页模式翻页一次走两页
- [ ] 切到后台十分钟再回来，渲染没卡死
- [ ] 「下载 PDF」是真的存盘，不是新开标签页

**音频**

- [ ] 拖进度条立刻出声
- [ ] 倍速 0.75 与 2.0 都正常
- [ ] AB 复读到点自动跳回
- [ ] 关页面再进，播放位置接得上
- [ ] 第 3 套显示「复用 xxx」

**数据**

- [ ] 写笔记后刷新还在
- [ ] 答题卡选十题，刷新还在，且没有一题显示对错
- [ ] 点「答案」才出对错，点「全部隐藏」能收回
- [ ] 把题量从 55 改到 30 再改回，31–55 的作答还在
- [ ] 用 `curl` 塞非法数据，服务端拒绝且文件未污染
- [ ] `progress.json` 在断电式关闭后仍是完整 JSON（可接受丢最后一次）

**文字层与圈画**

- [ ] `Ctrl+F` 能在 PDF 里搜到词
- [ ] 点任意单词出音标与释义
- [ ] 点人名如实说「词库里没有」
- [ ] 变形词能回原形（`books → book`）
- [ ] 50% 与 200% 下笔迹都贴在同一行字上
- [ ] 橡皮点中哪笔删哪笔
- [ ] 撤销只撤最后一笔，清页只清当前页

**工具链**

- [ ] `npm run check` 全绿
- [ ] `npm run status` 输出与实际目录一致
- [ ] `ingest --dry` 的计划与实际下载一致
- [ ] 重复跑 ingest 全程「跳过」，零流量
- [ ] `build-analysis.py` 对有一套能出 `analysis.json`
- [ ] `ocr-pdf.py --list` 的待补页数正确

**诚实性**

- [ ] 没有原卷的套卷，界面明说「只有答案解析」，不是空白页
- [ ] 没有答案的套卷，界面明说「不判分」，不是全错
- [ ] 重排版生成的 PDF，`meta.json` 里写了来源文件与 `quality`
- [ ] 词库查不到时返回 `hit: false`，不给编造的释义

---

## 附录 A · API 一览

| 方法 | 路径 | 入参 | 说明 |
|---|---|---|---|
| GET | `/api/papers` | 无 | 全量索引 + 每套 `local` / `progress` / `started` / `sheet` + `counts` |
| GET | `/api/paper` | `?id=` | meta、笔记、进度、答案、作答、逐题解析、`pdfFile`、`audioFile` |
| GET | `/api/dict` | `?word=` | 查词，含变形回原形与前缀候选 |
| GET | `/api/ink` | `?id=` | 该套笔迹 |
| POST | `/api/ink` | `{id, pages}` | 存笔迹，坐标 0~1 |
| POST | `/api/progress` | `{id, page, audioTime, scale, view}` | 合并式更新 |
| POST | `/api/sheet` | `{id, count, answers}` | 存作答，题量与数据解耦 |
| POST | `/api/notes` | `{id, content}` | 写 `notes.md` |
| GET | `/api/study` | 无 | 生词本 + 错题本 |
| POST | `/api/study` | `{collection, item}` 或 `{collection, remove}` | 增改 / 删 |
| GET | `/api/overview` | 无 | 学习概览 |
| GET | `/data/*` | `?download=1` 时发附件 | 题库文件，支持 Range |

## 附录 B · npm 脚本

```bat
npm start                       :: node server.mjs --port 8787
npm run check                   :: 全量 node --check
npm run status                  :: 只读体检
npm run digest                  :: 生成 data/notes-all.md
npm run index                   :: 给已收录套卷补 sizes + sha256
npm run ingest                  :: 灌六级（读 ../cet6/sources/CET6-MASTER.md）
npm run ingest -- --dry         :: 只看计划
npm run ingest -- --only 2019.06
npm run ingest:legacy           :: 补 2013.06-2015.12
npm run dict:words              :: 扫 PDF 抽词表
npm run dict:build              :: 裁 ECDICT → dict.json
npm run dict:full               :: ECDICT 全量 → dict.db
npm run answers                 :: 取答案（需 9223 上的已登录浏览器）
npm run answers:split           :: 拆到每套的 answers.json
npm run ocr:list                :: 列出待补文字层的页
npm run ocr                     :: 全部补一遍
```

## 附录 C · 命名约定

| 东西 | 约定 | 例子 |
|---|---|---|
| 套卷 id | `exam/YYYY-MM/NN` | `cet6/2025-12/01` |
| 考试 id | 小写英文，无连字符 | `cet6` `cet4` `tem4` `tem8` |
| 期次 | `YYYY-MM`，考试月 | `2025-12` |
| 套号 | 两位数字符串 | `01` `02` `03` |
| 正文 | `read.pdf`，重排版优先 `read.clean.pdf` | 无 |
| 听力 | `listen.<真实格式>` | `listen.m4a` |
| 解析 | `analysis.pdf` / `analysis.json` | 无 |
| 标准答案 | `answers.json`，键为纯数字字符串 | `{"7":"B"}` |
| 我的作答 | `sheet.json` | 无 |
| 笔迹 | `ink.json`，按页号分组 | `{"pages":{"1":[…]}}` |
| 学习数据 | `data/study/<集合>.json`，数组 | `wordbook.json` |

**目录名不要出现空格和中文。** 这个约定省掉了后面一百次 URL 编码的麻烦。

---

## 结语

这个项目里没有一项技术是新的。pdf.js 十几年前就有，Range 请求是 HTTP/1.1 的东西，`fs.rename` 的原子性比 Node 还老。

它值钱的地方在于**把一堆琐碎的正确性做到了位**。文字层要设 `--scale-factor`，笔迹坐标要归一化，写 JSON 要原子，音频要 206，`&amp;` 要先切后转义，页脚要关掉。每一条都是几十行的事，漏一条就是一次「这功能怎么有时候不对」。

复刻的意义也不在于得到一个一模一样的目录。**你真正要带走的是那 25 条踩坑记录和每个阶段的验收标准**，因为换一个题材，坑还是这些坑，只是出现的顺序变了。


