# zhenti.burningvocabulary.cn 逆向笔记

用 **rea**（`capture-browser-scenario`）对站点做的结构勘察记录。目的：搞清楚一套真题从列表页到「正文 / 听力 / 答案」各自是怎么来的，然后照着搭一套自己的本地系统。

勘察时间：2026-10-18。工具：rea 6.7.0 CLI（本机 Chrome 155 启动，headless）。

---

## 1. 站点形态

| 项 | 观察结果 |
|---|---|
| 类型 | 服务端渲染的多页站，不是 SPA |
| 后端 | `nginx/1.27.0`，响应头带 `x-ser: i2580102_c29070` |
| 静态资源 | 阿里云 OSS + CDN：`res-zhenti.burningvocabulary.cn`（Tengine，带 `x-oss-*` / `ali-swift-*` / `eagleid`） |
| 前端 | Bootstrap 4.5.3 + 自写 JS；PWA（`webapp.webmanifest` + `service_worker.js?v=20`） |
| 埋点 | 51.la（`sdk.51.la/js-sdk-pro.min.js` → `collect-v6.51.la/v6/collect`） |

## 2. URL 规律

```
列表页   /{kaoyan|cet4|cet6|tem4|tem8}
单套页   /{考试}/{YYYY-MM}/{套号}        例：/cet6/2025-12/01
缩略图   res-.../images/read/{考试}/{YYYY-MM}/{套号}/thumbnail.webp
        （旧卷退回 thumbnail_moz.jpg）
```

六级列表实测：**2012–2026年6月，共 83 套**，按半年分组，每个分组节点带 `data-paper-period="2026年6月"`，套卷节点带 `data-version="free|..."`。

## 3. 详情页的内联配置（核心）

详情页 `<head>` 里塞了两个全局变量（rea 抓 DOM 直接可取）：

```js
window.winGlobal = {
  "docInfo": { "title":"2025年12月英语六级真题(第1套)", "aStatus":3, "aiInstructor":0, "stStatus":3 },
  "price":   { "money_fee":9.9, "money_fee_for_sentenceTranslation":10 }
};

var globalConfig = {
  "filePath": "cet6/2025-12/01",
  "pdfHost": "https://res-zhenti.burningvocabulary.cn",
  "fnameVersion": 1,
  "audioDuration": 1543209.75,
  "fn":  { "f1":[...10 个字符], "f2":[...22 个字符] },
  "an":  { "a2":[...15 个字符], "a3":[...17 个字符] },
  "newAnswer": { "ciphertext": "...", "p": "...", "n": "...", "data": "..." },
  "newListenSpli": { "CONVERSATION 1":"ls2_621u", "Q1.":"ls2_bc3h", ... },
  "hasListeningText": true,
  "sentenceTranslationStatus": 1
};
```

## 4. 资产 URL 生成规则（已交叉验证）

站点把自己的资源名打散成字符数组，取出来**拼接后整体反转**：

```js
hash = [...fn.f1, ...fn.f2].reverse().join("")   // 真题正文 PDF
hash = [...an.a2, ...an.a3].reverse().join("")   // 听力音频
pdf = `${pdfHost}/images/read/${filePath}/${pdfHash}.pdf?v=${fnameVersion}`
mp3 = `${pdfHost}/images/read/${filePath}/${audioHash}.mp3?v=1`
```

对 `/cet6/2025-12/01` 实测：

| 资产 | 推导结果 | 实测 |
|---|---|---|
| PDF | `49e947c865b26a1756791aeb3619835e.pdf?v=1` | 200，`application/pdf`，663,776 B |
| MP3 | `40d2fe4909bb348fea60cf5084cf88f1.mp3?v=1` | 200，`audio/mpeg`，12,345,722 B（25:43） |

**交叉验证方式**：rea 的 network 事件里抓到浏览器真实请求的 PDF URL，与按规则算出来的完全一致；MP3 用 HEAD 验的 200。
两份资产**无 cookie、无 token、无签名**，直链即可取。

## 5. 阅读与播放是怎么实现的

- 正文不是 HTML，是 **pdf.js 渲染的 PDF**：`viewer.min.css` + `zhenti.viewer_2-14-316.js` + `pdf.worker_2-14-316.js`。
- 听力用 `openplayer 2.8.3` 播，配 `audioDuration` 做进度条。
- **DOM 里抓不到题目文本**（canvas 画的），要文本只能解析 PDF 本身。

### 5.1 「点词即查」是怎么做的（拆过他们的 viewer）

1. pdf.js 铺完文字层后，他们遍历每个文字块，把 `innerText` 里的英文单词用正则包成自定义元素：
   `t.replace(/\b([a-z\-]{1,100})\b/gi, "<aword>$1</aword>")`，并记下 `_awordConfig = {left, top}`。
   所以"点词"不是靠选区，而是**每个词本身就是一个可点的元素**。
2. 点击 → `POST /api/dictionary/get_df?token=…`（会员版）或 `/api/dictionary/get_simp_dict?token=…`（简版）。
   两个接口**都要 token**，空 token 直接返回 `{"code":"9997","msg":"error"}` —— 查词是付费权益，不是前端算出来的。
3. 弹窗结构：`word_head`（词 + 音标）/ `word_define`（词性 + 释义）/ 关闭按钮，浮在词下方，被点的词加波浪下划线。
4. 圈画是**独立 canvas 覆盖层**：`lineWidth` / `strokeStyle` / `globalAlpha` 都在 viewer 里，
   荧光笔 = 低 alpha 的粗线，橡皮按笔迹命中删除。批注另有文本框类型（`annotate.jpg` 里那些 D1/C2/B3 编号）。

对应的本地实现（不依赖他们的 token）：

| 环节 | 他们 | 这里 |
|---|---|---|
| 切词 | `innerText.replace(/\b(\w+)\b/, "<aword>")` | `wordify()`：`matchAll` 后包 `<aw>`，先转义再拼，避免 `&amp;` 里的 `amp` 被误切 |
| 词典 | 服务端付费接口 | `data/dict.json`（ECDICT 裁剪，2.1 万词条 + 1 万条变形映射），`/api/dict` 查 |
| 变形词 | 接口内部处理 | 先查原词，查不到走 `forms` 映射，命中就标"xxx → 原形 yyy" |
| 圈画 | canvas 覆盖层 | 同样是 canvas 覆盖层，但坐标存**相对页面的 0~1**，线宽存**占页宽的比例**，所以缩放不错位、字号不变形 |
| 存储 | 服务端账号 | 每套一个 `ink.json`，跟着题库走 |

## 6. 答案与付费

- 答案**不在 DOM 里**。页面只有一个 `.answer_btn`，点击后走 worker。
- worker：`/javascripts/read_zhenti_web_worker.js?version=03aad8a1`，挂在 `window.__readZhentiWorker`。
  该文件里打包了 **TweetNaCl**（`crypto_secretbox` / `crypto_box_open` / `crypto_box_keypair`），
  `newAnswer` 的 `ciphertext + p + n + data` 就是喂给它的密钥材料。属于自写轻量混淆，不是真加密，但**解密逻辑在客户端**。
- 真正走服务端的付费内容：
  - `/api/listening/textGet`（听力原文）
  - `/api/answerExpansion/textGet`（答案扩展）
  - `/api/answerAnasysis/textGet|textSave`（解析）
  - `/api/sentence/translation/get?subSid&sid&matchType&pathName`（句子翻译）
- 其他接口：`/api/data/update|delete`、`/api/order/getDetail|renew`、`/api/dictionary/get_df|get_simp_dict`、`/api/invite/getMyInviteInfo`、`/view/recordFrame`。

### 6.1 实际取的姿势（2026-10 补）

`newAnswer` 不是等接口返回的，它**在试卷页 HTML 里内联**，页面加载时就已经把密文塞给 worker 了：
`.answer_btn` 只负责把解出来的东西显示出来。所以：

1. 在**已登录、且设备绑定过的**那个页面里同源 `fetch('/cet6/2022-12/01')`，拿 HTML；
2. 按括号配平从 `newAnswer: [...]` 里抠出密文（正则抠不准，字符串里有 `]`）；
3. 新建 `new Worker('/javascripts/read_zhenti_web_worker.js?version=…')`，
   `postMessage({ type: 'decryp_msg_ans', resData: { data: newAnswer } })`；
4. 监听回包 `type === 'decryp_msg_ans_ed'`，`resData` 就是 `["1-C", "2-B", …]`。

全程不碰 TweetNaCl，站点改算法也不影响。落地：`tools/fetch-answers.mjs`。

同一条路对别的类型也开着（`decryp_msg_listening`、`decryp_msg_sentence_translation` 等），
但听力原文那步**卡在服务端**：`/api/listening/textGet` POST 出去 30 秒不回包，
所以这条只对答案可用。

顺带两个实测结论：
- 复制 profile 目录**带不走登录态**（session cookie 不落盘），只能给同一份 profile 加
  `--remote-debugging-port` 重启一次。
- `cet6/2022-06/03` 的试卷页是 **404**，站上就没这套的答案。

## 7. 设备绑定（实测证据）

用**同一账号**在两个不同会话里访问真题详情页：

| 会话 | 结果 |
|---|---|
| rea 启动的全新 profile：`/login?uid=…` → `/me` | 正常，显示「专业版 有效期至 2026年11月26日 状态:正常」 |
| 内置浏览器的 profile：`/cet6/2025-12/01` | 服务端返回 `设备使用受限，请在原设备使用。` |
| rea 启动的全新 profile：登录后 → `/cet6/2025-12/01` → 点「查答案」 | `.answer_btn` 不存在，动作超时 |

结论：**会员账号与设备绑定**，换个 profile 就只剩匿名能力（正文 PDF / 听力仍可直连，答案不行）。
这一层是服务端校验，我没有去伪造指纹绕过它。

`robots.txt` 也写得很清楚：

```
User-agent: *
Disallow: /login
Disallow: /logout
Disallow: /admin/
Disallow: /api/
Sitemap: https://zhenti.burningvocabulary.cn/sitemap.xml
```

用户协议第六条：平台所有内容（文字/图片/音频/视频）受知识产权保护；未经书面同意不得用于商业用途。

## 8. 本地系统怎么对应

| 站点能力 | 本地实现 | 状态 |
|---|---|---|
| 列表页（按半年分组、套号） | 全量索引 `data/papers.json`（83 套）+ 首页筛选/搜索 | ✅ |
| 列表页缩略图 | 本地 `cover.webp` 优先，否则 CSS 占位封面（不热链 CDN） | ✅ |
| pdf.js 阅读、翻页、缩放、适宽 | `read.js` + 本地 vendored pdf.js 4.10.38 | ✅ |
| 听力播放 | HTML5 audio + Range 分段请求 | ✅ |
| 倍速 | `<select>` 0.75x–2.0x | ✅ |
| 进度记录 | `data/<套>/progress.json`，翻页/听力位置自动落盘 | ✅ |
| 笔记 | `data/<套>/notes.md`，可拿去做目录同步 | ✅ |
| 生词本 | `data/study/wordbook.json`（跨套共享） | ✅ |
| 错题本 | `data/study/wrong.json`（跨套共享，含"我选/正确答案"） | ✅ |
| AB 复读 | 播放器 A/B 打点循环 | ✅ |
| 答题卡 + 自动判分 | `data/<套>/sheet.json`（我的作答）+ `answers.json`（标准答案）对照 | ✅ |
| 一键把判错题记进错题本 | 答题卡按钮批量写入 | ✅ |
| 答案本体 | `data/<套>/answers.json` | ✅ 61/76 套自动取（见 6.1），其余留空 |
| 句子翻译 / 听力原文 / 解析 | 站点服务端付费能力 | ❌ 不在本地做 |
| pdf.js 手写批注 / 高亮 | 独立 canvas 覆盖层 | ✅ 画笔 / 荧光笔 / 橡皮 / 撤销，按页存 `ink.json` |
| 点词查词（音标 + 词性 + 释义） | 文字层切词 + 本地 ECDICT 全量库（SQLite 77 万条，带四六级/考研/雅思标签） | ✅ 不联网 |
| pdf.js 文字层（选中 / 复制 / 查找） | `TextLayer` + `--scale-factor` | ✅ |
| 划词入生词本 | 选区浮出按钮 → `data/study/wordbook.json` | ✅ |
| 分段限时（写作/听力/阅读/翻译） | 阅读器工具栏计时器，墙上时间重算 + localStorage 持久化 | ✅ |

## 9. 踩到的坑（都是真踩过的）

1. **PowerShell 管道会毁掉 UTF-8**：`& node x.mjs | Out-File` 会把原生命令输出按 GBK 重解码，JSON 直接坏、中文全乱码。
   必须 `cmd /c "node x.mjs > file"` 保留原始字节，再用 Node 解析。
2. **`<input>` 的 `value` 属性不会跟着 `.value` 变**：往 DOM 里断言页码要另设一个 `<span id="pageLabel">`，
   否则永远读到 HTML 里写死的初始值。
3. **pdf.js 依赖 `requestAnimationFrame`**：标签页 `visibility: hidden` 时 rAF 不触发，
   `page.render().promise` 永远不 resolve（没有报错，就是卡住）。窗口可见时一切正常 —— 排查时先看 `document.visibilityState`。
4. res-zhenti 的 CDN 响应对同一资源会返回 200 / 304 混合，做校验时以 body 字节 + `content-length` 为准。
5. **pdf.js 一个 canvas 同时只允许一个 render**：翻页与"适宽"并发会抛
   `Cannot use the same canvas during multiple render() operations`，之后整个渲染管线卡死。渲染必须串行化。
6. **flex/grid 子项 `min-height` 默认 `auto`**：长内容把兄弟节点顶出视口 —— 阅读器底部的听力播放条就是这样被
   `overflow:hidden` 裁掉的。`.viewer-scroll` / `.tabbody` / `.viewer-col` 都要显式 `min-height: 0`。
7. **PowerShell 的 `$PID` 是只读自动变量**：`$pid = ...` 赋值失败后它仍是当前 shell 自己的进程号，
   于是"精确杀进程"变成了"杀自己"（exit 255）。变量名别叫 `$pid`。
8. **`.ps1` 没有 UTF-8 BOM 时 Windows PowerShell 5.1 按 ANSI 读**：中文注释会让脚本直接解析失败（"字符串缺少终止符"）。
   脚本保持 ASCII-only。
9. **rea 的 `fill` 动作在本项目页面上会挂住**（`Analysis operation timed out`），
   但 `click` / `wait_for_timeout` 正常。截图场景只用后两者；需要操作页面状态时改用数据驱动
   （例如先把 `progress.json` 设成目标状态，再让页面自己恢复）。
10. **rea 的 `viewport` 属于 `environment.viewport`**（`{width,height,device_scale_factor}`），放在顶层会报
    `unknown_argument`；`fill` 用 `value: {source:"literal",value:"…"}`，不是 `text`。
