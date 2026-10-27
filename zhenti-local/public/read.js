import { createViewer } from "./viewer.js";
import * as pdfjsLib from "./vendor/pdfjs/pdf.min.mjs";

// 侧栏解析视图直接复用同一份 pdf.js；worker 与主阅读器共用
pdfjsLib.GlobalWorkerOptions.workerSrc = "./vendor/pdfjs/pdf.worker.min.mjs";

const params = new URLSearchParams(location.search);
const paperId = params.get("id") ?? "";

const $ = (id) => document.getElementById(id);
const state = {
  paper: null,
  viewing: "paper",      // paper | analysis（解析 PDF 在同一个阅读器里打开）
  paperView: null,       // 切去解析前记住试题的页码/缩放/模式
  saveTimer: null,
};

/* ---------------- helpers ---------------- */

const escapeHtml = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));

const api = async (path, body) => {
  const response = await fetch(path, body
    ? { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) }
    : undefined);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
};

const clock = (seconds) => {
  if (!Number.isFinite(seconds)) return "00:00";
  const total = Math.floor(seconds);
  const mm = String(Math.floor(total / 60)).padStart(2, "0");
  const ss = String(total % 60).padStart(2, "0");
  return `${mm}:${ss}`;
};

const flash = (text) => {
  $("saveState").textContent = text;
  window.clearTimeout(flash.timer);
  flash.timer = window.setTimeout(() => { $("saveState").textContent = ""; }, 1600);
};

/* ---------------- viewer ---------------- */

const viewer = createViewer({
  scrollEl: $("viewerScroll"),
  pagesEl: $("pagesBox"),
  paperId,
  api,
  flash,
  titleOf: () => state.paper?.meta?.title ?? paperId,
  onChange: () => scheduleSave(),
  onStudyChanged: async () => { study = await api("/api/study"); renderStudy(); },
});

const currentFile = () =>
  (state.viewing === "analysis" ? state.paper?.analysisFile : state.paper?.pdfFile)
  ?? state.paper?.analysisFile
  ?? null;

const refreshDownload = () => {
  const link = $("downloadPdf");
  const file = currentFile();
  if (!file) {
    link.hidden = true;
    return;
  }
  link.hidden = false;
  link.href = `/data/${paperId}/${file}?download=1`;
  const label = state.viewing === "analysis" || !state.paper?.pdfFile ? "解析" : "试卷";
  link.setAttribute("download", `${paperId.replace(/\//g, "_")}_${file}`);
  link.title = `下载${label} PDF（${file}）`;
  link.textContent = `下载${label}`;
};

/** 没有原卷的套卷（大部分专八只有答案解析）：正面说清楚手里有什么，别让人以为卡了。 */
const renderPaperless = () => {
  const paper = state.paper;
  const meta = paper?.meta ?? {};
  const bits = [
    meta.quality ? `<span class="pill">${escapeHtml(meta.quality)}</span>` : "",
    meta.examDate ? `<span class="muted">考试日期 ${escapeHtml(meta.examDate)}</span>` : "",
  ].filter(Boolean).join(" ");
  $("pagesBox").innerHTML = `
    <div class="paperless-notice">
      <h2>这一套没有收录到原卷 PDF</h2>
      <p>公开渠道只找到当年的答案与解析，原卷缺。下面的按钮在侧栏打开解析。</p>
      ${meta.note ? `<p>${escapeHtml(meta.note)}</p>` : ""}
      <p>${bits}</p>
      ${paper?.analysisFile ? `<button class="primary" id="paperlessAnalysis">在侧栏看解析 PDF →</button>` : ""}
    </div>`;
  $("paperlessAnalysis")?.addEventListener("click", () => openAnalysisAt());
  $("pageCount").textContent = "—";
  $("pageLabel").textContent = "无原卷";
  for (const id of ["prev", "next", "pageInput", "viewMode", "zoomIn", "zoomOut", "zoomSelect", "inkUndo", "inkClear"]) {
    const el = $(id);
    if (el) el.disabled = true;
  }
  for (const button of document.querySelectorAll(".tool, .swatch")) button.disabled = true;
};

/* ---------------- progress ---------------- */

function scheduleSave() {
  if (state.viewing !== "paper") return;   // 看解析时不覆盖试题的阅读进度
  window.clearTimeout(state.saveTimer);
  state.saveTimer = window.setTimeout(saveProgress, 700);
}

async function saveProgress() {
  if (!paperId || state.viewing !== "paper") return;
  try {
    await api("/api/progress", {
      id: paperId,
      page: viewer.state.page,
      audioTime: $("audio").currentTime || 0,
      scale: viewer.state.scale,
      view: { mode: viewer.state.mode, zoomKind: viewer.state.zoomKind },
    });
  } catch {
    return; // 进度是后台顺手存的，失败就不打扰
  }
  flash("已保存进度");
}

/* ---------------- audio ---------------- */

const setupAudio = () => {
  const audio = $("audio");
  const seek = $("seek");

  // 听力可能是 mp3 也可能是 m4a，还可能复用同考次另一套的，文件名一律由服务端判定
  const audioFile = state.paper?.audioFile;
  if (!audioFile) {
    document.querySelector(".audiobar")?.classList.add("is-empty");
    $("durTime").textContent = "无音频";
    return;
  }
  audio.src = audioFile.startsWith("/data/") ? audioFile : `/data/${paperId}/${audioFile}`;
  if (state.paper?.audioFrom) $("audioFrom").textContent = `复用 ${state.paper.audioFrom}`;
  $("audioFrom").hidden = !state.paper?.audioFrom;

  audio.addEventListener("loadedmetadata", () => {
    $("durTime").textContent = clock(audio.duration);
    if (state.paper?.progress?.audioTime) audio.currentTime = state.paper.progress.audioTime;
  });

  audio.addEventListener("timeupdate", () => {
    if (!audio.duration) return;
    const ratio = audio.currentTime / audio.duration;
    $("curTime").textContent = clock(audio.currentTime);
    if (!seek.matches(":active")) {
      seek.value = String(ratio * 1000);
      seek.style.setProperty("--pct", `${(ratio * 100).toFixed(2)}%`);
    }
    if (state.ab.a !== null && state.ab.b !== null && audio.currentTime >= state.ab.b) {
      audio.currentTime = state.ab.a;
    }
    if (Math.floor(audio.currentTime) % 15 === 0 && Math.floor(audio.currentTime) !== state.lastSavedSecond) {
      state.lastSavedSecond = Math.floor(audio.currentTime);
      scheduleSave();
    }
  });

  audio.addEventListener("pause", () => { $("play").textContent = "▶"; scheduleSave(); });
  audio.addEventListener("play", () => { $("play").textContent = "❚❚"; });
  $("play").addEventListener("click", () => (audio.paused ? audio.play() : audio.pause()));
  $("back10").addEventListener("click", () => { audio.currentTime = Math.max(0, audio.currentTime - 10); });
  $("fwd10").addEventListener("click", () => { audio.currentTime = Math.min(audio.duration || 0, audio.currentTime + 10); });
  seek.addEventListener("input", () => {
    if (!audio.duration) return;
    seek.style.setProperty("--pct", `${(Number(seek.value) / 10).toFixed(2)}%`);
    audio.currentTime = (Number(seek.value) / 1000) * audio.duration;
  });
  $("rate").addEventListener("change", (event) => { audio.playbackRate = Number(event.target.value); });

  state.ab = { a: null, b: null };
  $("markA").addEventListener("click", () => {
    state.ab.a = audio.currentTime;
    $("markA").classList.add("ab-active");
    if (state.ab.b !== null && state.ab.b <= state.ab.a) { state.ab.b = null; $("markB").classList.remove("ab-active"); }
    flash(`A = ${clock(state.ab.a)}`);
  });
  $("markB").addEventListener("click", () => {
    if (state.ab.a === null) return flash("先标 A 点");
    state.ab.b = audio.currentTime;
    if (state.ab.b <= state.ab.a) { state.ab.b = null; return flash("B 点要在 A 之后"); }
    $("markB").classList.add("ab-active");
    flash(`AB 复读 ${clock(state.ab.a)} → ${clock(state.ab.b)}`);
  });
  $("clearAB").addEventListener("click", () => {
    state.ab = { a: null, b: null };
    $("markA").classList.remove("ab-active");
    $("markB").classList.remove("ab-active");
    flash("已清除 AB");
  });
};

/* ---------------- study data ---------------- */

let study = { wordbook: [], wrong: [] };

const paperLink = (entry) => {
  const id = String(entry.key ?? "").split("::")[0];
  if (!id.includes("/")) return escapeHtml(entry.paper ?? "");
  return `<a href="/read.html?id=${encodeURIComponent(id)}">${escapeHtml(entry.paper ?? id)}</a>`;
};

const renderStudy = () => {
  const words = study.wordbook.slice().sort((a, b) => (b.at ?? "").localeCompare(a.at ?? ""));
  $("wordList").innerHTML = words.map((entry) => `
    <li>
      <div class="grow">
        <div class="w">${escapeHtml(entry.word)}</div>
        <div class="n">${escapeHtml(entry.note ?? "")} ${entry.paper ? `· ${paperLink(entry)}` : ""}</div>
      </div>
      <button class="del" data-collection="wordbook" data-key="${escapeHtml(entry.key)}" title="移除">✕</button>
    </li>`).join("");

  const wrong = study.wrong.slice().sort((a, b) => (b.at ?? "").localeCompare(a.at ?? ""));
  $("wrongList").innerHTML = wrong.map((entry) => `
    <li>
      <div class="grow">
        <div class="w">第 ${escapeHtml(entry.q)} 题${entry.answer || entry.correct ? ` · 我 ${escapeHtml(entry.answer ?? "—")}${entry.correct ? ` / 正 ${escapeHtml(entry.correct)}` : ""}` : ""}</div>
        <div class="n">${escapeHtml(entry.note ?? "")} ${entry.paper ? `· ${paperLink(entry)}` : ""}</div>
      </div>
      <button class="del" data-collection="wrong" data-key="${escapeHtml(entry.key)}" title="移除">✕</button>
    </li>`).join("");

  for (const button of document.querySelectorAll(".del")) {
    button.addEventListener("click", async () => {
      await api("/api/study", { collection: button.dataset.collection, remove: button.dataset.key });
      study = await api("/api/study");
      renderStudy();
    });
  }
};

const setupStudy = () => {
  $("addWord").addEventListener("click", async () => {
    const word = $("wordInput").value.trim();
    if (!word) return;
    await api("/api/study", {
      collection: "wordbook",
      item: { key: `${paperId}::${word.toLowerCase()}`, word, paper: state.paper?.meta?.title ?? paperId, at: new Date().toISOString() },
    });
    $("wordInput").value = "";
    study = await api("/api/study");
    renderStudy();
  });

  $("addWrong").addEventListener("click", async () => {
    const q = $("wrongQ").value.trim();
    if (!q) return;
    await api("/api/study", {
      collection: "wrong",
      item: {
        key: `${paperId}::${q}`,
        q,
        answer: $("wrongA").value.trim(),
        note: $("wrongNote").value.trim(),
        paper: state.paper?.meta?.title ?? paperId,
        at: new Date().toISOString(),
      },
    });
    $("wrongQ").value = ""; $("wrongA").value = ""; $("wrongNote").value = "";
    study = await api("/api/study");
    renderStudy();
  });
};

/* ---------------- 答案与解析 ---------------- */

const analysisOf = (q) => state.paper?.analysis?.questions?.[String(q)] ?? null;

// 四六级题号是固定的，可以按题号标出题型；专四专八各年题型结构不一样，不硬套
const SECTIONS = {
  cet6: [
    [8, "听力 Section A · 长对话"], [15, "听力 Section B · 篇章"], [25, "听力 Section C · 讲座/讲话"],
    [35, "阅读 Section A · 选词填空"], [45, "阅读 Section B · 段落匹配"], [50, "阅读 Section C · 仔细阅读（一）"],
    [Infinity, "阅读 Section C · 仔细阅读（二）"],
  ],
  cet4: [
    [7, "听力 Section A · 新闻"], [15, "听力 Section B · 长对话"], [25, "听力 Section C · 篇章"],
    [35, "阅读 Section A · 选词填空"], [45, "阅读 Section B · 段落匹配"], [50, "阅读 Section C · 仔细阅读（一）"],
    [Infinity, "阅读 Section C · 仔细阅读（二）"],
  ],
};

const examKind = () => String(paperId ?? "").split("/")[0];

const sectionName = (q) => {
  const table = SECTIONS[examKind()];
  if (!table) return null;   // 专四专八不按题号猜题型
  for (const [upper, label] of table) if (q <= upper) return label;
  return null;
};

/** 解析正文是整段文本，按换行拆段，保留中英文原样，不做任何改写。 */
const analysisHtml = (text) => String(text ?? "").split(/\n{2,}|\n/)
  .map((line) => line.trim()).filter(Boolean)
  .map((line) => `<p>${escapeHtml(line)}</p>`).join("");

/** 有原文选项数据时，把 A/B/C/D 列出来，省得来回翻卷子。 */
const choicesHtml = (choices) => {
  const entries = Object.entries(choices ?? {}).filter(([, value]) => value);
  if (!entries.length) return "";
  return `<ul class="ana-choices">${entries
    .map(([letter, value]) => `<li><b>${escapeHtml(letter)}</b><span>${escapeHtml(value)}</span></li>`)
    .join("")}</ul>`;
};

/* ---------------- 解析 PDF：默认在右侧栏打开 ---------------- */

const ana = { url: "", doc: null, zoom: 1, current: 1, pages: [], rendering: false, pending: false };

const anaWidth = () => {
  const box = $("anaScroll");
  const inner = (box?.clientWidth || 380) - 24;
  return Math.max(180, Math.round(inner * ana.zoom));
};

const anaPageLabel = () => (ana.doc ? `第 ${ana.current} / ${ana.doc.numPages} 页` : "…");

/** 逐页重画；缩放变化时宽度不同就重渲染，渲染串行排队（一个 canvas 同时只能一个 render）。 */
const renderAnaPages = async () => {
  if (!ana.doc) return;
  if (ana.rendering) { ana.pending = true; return; }
  ana.rendering = true;
  try {
    do {
      ana.pending = false;
      const width = anaWidth();
      for (const item of ana.pages) {
        if (item.width === width) continue;
        const pdfPage = await ana.doc.getPage(item.num);
        const base = pdfPage.getViewport({ scale: 1 });
        const ratio = Math.min(window.devicePixelRatio || 1, 2);
        const viewport = pdfPage.getViewport({ scale: (width / base.width) * ratio });
        item.canvas.width = Math.round(viewport.width);
        item.canvas.height = Math.round(viewport.height);
        item.canvas.style.width = `${width}px`;
        item.canvas.style.height = `${Math.round(viewport.height / ratio)}px`;
        await pdfPage.render({ canvasContext: item.canvas.getContext("2d"), viewport }).promise;
        item.width = width;
      }
    } while (ana.pending);
    $("anaZoomLabel").textContent = `${Math.round(ana.zoom * 100)}%`;
    $("anaPageLabel").textContent = anaPageLabel();
  } finally {
    ana.rendering = false;
  }
};

const loadAnaDoc = async (url) => {
  ana.url = url;
  ana.doc = null;
  ana.pages = [];
  ana.zoom = 1;
  ana.current = 1;
  $("anaScroll").innerHTML = '<p class="muted ana-empty">解析 PDF 载入中…</p>';
  $("anaPageLabel").textContent = "…";
  try {
    const doc = await pdfjsLib.getDocument(url).promise;
    if (ana.url !== url) return;
    ana.doc = doc;
    const box = document.createElement("div");
    box.className = "ana-pages";
    for (let num = 1; num <= doc.numPages; num += 1) {
      const wrap = document.createElement("div");
      wrap.className = "ana-page-wrap";
      wrap.dataset.page = String(num);
      const canvas = document.createElement("canvas");
      wrap.append(canvas);
      box.append(wrap);
      ana.pages.push({ num, el: wrap, canvas, width: 0 });
    }
    $("anaScroll").replaceChildren(box);
    await renderAnaPages();
    $("anaScroll").scrollTop = 0;
  } catch (error) {
    $("anaScroll").innerHTML = `<p class="muted ana-empty">解析 PDF 打不开：${escapeHtml(error.message)}</p>`;
  }
};

const scrollAnaTo = (num) => {
  const item = ana.pages.find((page) => page.num === Number(num));
  if (!item) return;
  const box = $("anaScroll");
  const top = item.el.getBoundingClientRect().top - box.getBoundingClientRect().top + box.scrollTop - 8;
  box.scrollTo({ top, behavior: "smooth" });
  ana.current = item.num;
  $("anaPageLabel").textContent = anaPageLabel();
};

const syncAnaPage = () => {
  if (!ana.pages.length) return;
  const box = $("anaScroll");
  const mark = box.getBoundingClientRect().top + 48;
  let current = 1;
  for (const item of ana.pages) if (item.el.getBoundingClientRect().top <= mark) current = item.num;
  // 滚到底部时最后一页可能还差几十像素没越过判定线，直接算它
  if (box.scrollTop + box.clientHeight >= box.scrollHeight - 6) current = ana.pages[ana.pages.length - 1].num;
  if (current !== ana.current) {
    ana.current = current;
    $("anaPageLabel").textContent = anaPageLabel();
  }
};

/** 点「查看解析」或某题的「解析 PDF 第 N 页」：侧栏展开、切到解析视图、滚到对应页。 */
const openAnalysisAt = async (page) => {
  if (!state.paper?.analysisFile) return flash("这一套还没有解析 PDF");
  if (document.body.classList.contains("panel-hidden")) togglePanel(false);
  const url = `/data/${paperId}/${state.paper.analysisFile}`;
  $("anaPane").hidden = false;
  if (ana.url !== url || !ana.doc) await loadAnaDoc(url);
  if (page) scrollAnaTo(page);
};

/** 侧栏太窄看不清时，仍在左侧阅读器里全屏看。 */
const openAnalysisFullscreen = async (page) => {
  if (!state.paper?.analysisFile) return flash("这一套还没有解析 PDF");
  $("anaPane").hidden = true;
  if (state.viewing !== "analysis") {
    state.paperView = {
      page: viewer.state.page, scale: viewer.state.scale,
      zoomKind: viewer.state.zoomKind, mode: viewer.state.mode,
    };
    state.viewing = "analysis";
    $("openAnalysis").hidden = true;
    $("backToPaper").hidden = !state.paper?.pdfFile;
    $("paperTitle").textContent = `${state.paper.meta.title} · 答案解析`;
    await viewer.load(`/data/${paperId}/${state.paper.analysisFile}`, { page: page ?? 1, zoomKind: "fitWidth", mode: "continuous" });
  } else if (page) {
    await viewer.goTo(page);
  }
  refreshDownload();
};

const backToPaper = async () => {
  const view = state.paperView ?? { page: 1, zoomKind: "fitWidth", mode: "continuous" };
  state.viewing = "paper";
  $("anaPane").hidden = true;
  $("openAnalysis").hidden = !state.paper?.analysisFile;
  $("backToPaper").hidden = true;
  $("paperTitle").textContent = state.paper.meta.title;
  await viewer.load(`/data/${paperId}/${state.paper.pdfFile ?? "read.pdf"}`, view);
  await viewer.loadInk();
  refreshDownload();
};

const showTab = (name) => {
  for (const button of document.querySelectorAll(".tabs button")) button.classList.toggle("active", button.dataset.tab === name);
  for (const panel of document.querySelectorAll(".tabbody section")) panel.classList.toggle("active", panel.dataset.panel === name);
  // 手动切页签时收起侧栏里的解析视图，回到正常侧栏
  if ($("anaPane")) $("anaPane").hidden = true;
  if (document.body.classList.contains("panel-hidden")) togglePanel(false);
};

/** 跳到某一题的解析：切到答案页、展开对应卡片、滚到它。 */
const showAnalysis = (q) => {
  showTab("answers");
  const card = document.querySelector(`#answersBody details[data-q="${q}"]`);
  if (!card) return flash(`第 ${q} 题暂时没有解析数据`);
  card.open = true;
  card.scrollIntoView({ block: "start", behavior: "smooth" });
};

const renderAnswers = () => {
  const body = $("answersBody");
  const answers = state.paper?.answers;
  const analysis = state.paper?.analysis;
  const transcripts = analysis?.listening ?? [];
  if (!answers && !analysis) {
    body.innerHTML = `
      <div class="hint">
        <p><strong>这一套还没有本地答案与解析数据。</strong></p>
        <p>答案放 <code>data/${escapeHtml(paperId)}/answers.json</code>，
        逐题解析放 <code>data/${escapeHtml(paperId)}/analysis.json</code>，刷新本页即可显示。</p>
      </div>`;
    return;
  }

  const numbers = [...new Set([
    ...Object.keys(answers ?? {}).filter((k) => /^\d+$/.test(k)),
    ...Object.keys(analysis?.questions ?? {}),
  ])].map(Number).sort((a, b) => a - b);

  const parts = [];
  let lastSection = "";
  for (const q of numbers) {
    const section = sectionName(q);
    if (section && section !== lastSection) { parts.push(`<h4 class="ana-section">${section}</h4>`); lastSection = section; }
    const transcript = transcripts.find((item) => item.from === q);
    if (transcript) {
      parts.push(`
        <details class="ana-card block" data-transcript="${escapeHtml(transcript.id)}">
          <summary><span class="qn">听力原文 · ${escapeHtml(transcript.title)}</span></summary>
          <div class="ana-body">${analysisHtml(transcript.text)}</div>
        </details>`);
    }
    const detail = analysisOf(q);
    const correct = answers?.[q] ?? detail?.answer ?? "";
    const mine = sheetState.answers[q] ?? "";
    const verdict = mine && correct ? (mine === correct.toUpperCase() ? '<span class="ok-text">✔</span>' : '<span class="bad-text">✘</span>') : "";
    parts.push(`
      <details class="ana-card" data-q="${q}">
        <summary>
          <span class="qn">第 ${q} 题</span>
          <span class="ana-ans">${escapeHtml(correct || "—")}</span>
          ${mine ? `<span class="ana-mine">我选 ${escapeHtml(mine)}</span>` : ""}
          ${verdict}
        </summary>
        <div class="ana-body">
          ${detail?.stem ? `<p class="ana-stem">${escapeHtml(detail.stem)}</p>` : ""}
          ${choicesHtml(detail?.choices)}
          ${detail?.text ? analysisHtml(detail.text) : '<p class="muted">这一题还没有解析文本。</p>'}
          ${detail?.note ? `<p class="muted">${escapeHtml(detail.note)}</p>` : ""}
          ${detail?.transcript ? `<div class="ana-transcript"><strong>听力原文</strong>${analysisHtml(detail.transcript)}</div>` : ""}
          <div class="ana-links">
            ${detail?.page && state.paper?.analysisFile ? `<button class="ghost" data-analysis-page="${detail.page}">解析 PDF 第 ${detail.page} 页</button>` : ""}
            ${detail?.source ? `<span class="muted">来源：${escapeHtml(detail.source)}</span>` : ""}
          </div>
        </div>
      </details>`);
  }

  for (const block of analysis?.blocks ?? []) {
    parts.push(`
      <details class="ana-card block" data-block="${escapeHtml(block.id)}">
        <summary><span class="qn">${escapeHtml(block.title)}</span></summary>
        <div class="ana-body">
          ${analysisHtml(block.text)}
          <div class="ana-links">
            ${block.pages?.length && state.paper?.analysisFile ? `<button class="ghost" data-analysis-page="${block.pages[0]}">解析 PDF 第 ${block.pages[0]} 页</button>` : ""}
          </div>
        </div>
      </details>`);
  }

  if (analysis?.note) parts.push(`<p class="muted" style="font-size:12px">${escapeHtml(analysis.note)}</p>`);
  body.innerHTML = parts.join("") || '<p class="muted">没有选择题答案。</p>';

  body.querySelectorAll("[data-analysis-page]").forEach((button) => {
    button.addEventListener("click", () => openAnalysisAt(Number(button.dataset.analysisPage)));
  });
};

/* ---------------- 答题卡（点选） ---------------- */

const sheetState = { count: 55, answers: {}, revealed: new Set() };

const correctAnswers = () => {
  const raw = state.paper?.answers;
  if (!raw || typeof raw !== "object") return null;
  const map = {};
  for (const [key, value] of Object.entries(raw)) {
    if (/^\d+$/.test(key) && typeof value === "string" && value.trim()) map[key] = value.trim().toUpperCase();
  }
  return Object.keys(map).length ? map : null;
};

const LETTERS = "ABCDEFGHIJKLMNO".split("");

/** 选项范围按题型来：听力/仔细阅读 A–D，选词填空与段落匹配 A–O。 */
const optionsFor = (q) => {
  const custom = state.paper?.analysis?.questions?.[String(q)]?.options;
  if (Array.isArray(custom) && custom.length) return custom;
  const count = q >= 26 && q <= 45 ? 15 : 4;
  const correct = correctAnswers()?.[String(q)];
  const extra = correct && LETTERS.indexOf(correct) >= count ? LETTERS.indexOf(correct) + 1 : count;
  return LETTERS.slice(0, Math.max(count, extra));
};

const updateSheetStats = () => {
  const correct = correctAnswers();
  const answered = Object.values(sheetState.answers).filter(Boolean).length;
  if (!correct) {
    $("sheetStats").innerHTML = `已答 <strong>${answered}</strong> / ${sheetState.count} 题 · <span class="muted">本地还没有 answers.json，先只记录作答</span>`;
    return;
  }
  // 只有点过「答案」的题才计入对错，避免统计口径偷偷泄题
  let right = 0;
  let wrong = 0;
  for (const [q, mine] of Object.entries(sheetState.answers)) {
    if (!mine || !correct[q] || !sheetState.revealed.has(q)) continue;
    if (mine === correct[q]) right += 1;
    else wrong += 1;
  }
  const scored = right + wrong;
  const pending = answered - scored;
  const rate = scored ? Math.round((right / scored) * 100) : 0;
  const extra = scored
    ? ` · 正确率 <strong>${rate}%</strong>`
    : " · <span class=\"muted\">还没核对答案</span>";
  $("sheetStats").innerHTML = `已答 <strong>${answered}</strong> / ${sheetState.count} · 对 <strong class="ok-text">${right}</strong> · 错 <strong class="bad-text">${wrong}</strong>${extra}`
    + (pending > 0 ? ` · <span class="muted">${pending} 题未看答案</span>` : "");
};

/** 只更新一行的判分与选中态，不整表重绘。未点「答案」的题一律不显示正误。 */
const refreshRow = (row) => {
  const correct = correctAnswers();
  const q = row.dataset.q;
  const mine = sheetState.answers[q] ?? "";
  const right = correct?.[q];
  const shown = Boolean(right) && sheetState.revealed.has(q);
  const verdict = !shown || !mine ? "" : mine === right ? "ok" : "bad";
  row.className = `q-row ${verdict} ${shown ? "revealed" : ""}`.trim();

  const mark = row.querySelector(".q-verdict");
  if (!shown) mark.textContent = "";
  else if (!mine) mark.textContent = `答案 ${right}`;
  else mark.textContent = verdict === "ok" ? "✔" : `✘ 应选 ${right}`;

  const toggle = row.querySelector(".q-ans");
  if (toggle) {
    toggle.disabled = !right;
    toggle.classList.toggle("on", shown);
    toggle.textContent = shown ? "收起" : "答案";
    toggle.title = right ? (shown ? "隐藏这一题的答案" : "显示这一题的答案") : "本地没有这一题的答案";
  }

  row.querySelectorAll(".q-opts button").forEach((button) => {
    const value = button.dataset.v;
    button.classList.toggle("chosen", value === mine);
    button.classList.toggle("is-correct", shown && value === right && value !== mine);
  });
};

const renderSheet = () => {
  const grid = $("sheetGrid");
  const parts = [];
  let lastSection = "";
  for (let index = 0; index < sheetState.count; index += 1) {
    const q = index + 1;
    const section = sectionName(q);
    if (section !== lastSection) { parts.push(`<h4 class="ana-section">${section}</h4>`); lastSection = section; }
    const hasAnalysis = Boolean(analysisOf(q)?.text);
    parts.push(`
      <div class="q-row" data-q="${q}">
        <div class="q-top">
          <span class="qn">${q}</span>
          <span class="q-verdict"></span>
          <button class="q-ans" data-q="${q}" title="显示这一题的答案">答案</button>
          <button class="q-ana" data-q="${q}" ${hasAnalysis ? "" : "disabled"} title="${hasAnalysis ? "看这一题的解析" : "这一题还没有解析"}">解析</button>
        </div>
        <div class="q-opts ${optionsFor(q).length > 6 ? "many" : ""}">
          ${optionsFor(q).map((value) => `<button type="button" data-v="${value}">${value}</button>`).join("")}
        </div>
      </div>`);
  }
  grid.innerHTML = parts.join("");
  for (const row of grid.querySelectorAll(".q-row")) refreshRow(row);
  updateSheetStats();
  syncRevealButtons();
};

let sheetTimer = null;
const saveSheet = async (announce) => {
  try {
    const response = await api("/api/sheet", { id: paperId, count: sheetState.count, answers: sheetState.answers });
    if (announce) flash(`答题卡已保存 · ${response.answered} 题`);
  } catch (error) {
    flash(`答题卡保存失败：${error.message}`);
  }
};

const scheduleSheetSave = () => {
  window.clearTimeout(sheetTimer);
  sheetTimer = window.setTimeout(() => saveSheet(false), 700);
};

const syncRevealButtons = () => {
  const correct = correctAnswers();
  const keys = correct ? Object.keys(correct) : [];
  const shown = keys.filter((q) => sheetState.revealed.has(q)).length;
  const all = $("sheetRevealAll");
  const none = $("sheetHideAll");
  if (all) {
    all.disabled = keys.length === 0 || shown >= keys.length;
    all.textContent = keys.length && shown >= keys.length ? "答案已全部显示" : "全部显示答案";
  }
  if (none) none.disabled = shown === 0;
};

const redrawSheet = () => {
  for (const row of $("sheetGrid").querySelectorAll(".q-row")) refreshRow(row);
  updateSheetStats();
  syncRevealButtons();
};

const setupSheet = () => {
  const grid = $("sheetGrid");

  grid.addEventListener("click", (event) => {
    const anaButton = event.target.closest(".q-ana");
    if (anaButton) { showAnalysis(anaButton.dataset.q); return; }

    const ansButton = event.target.closest(".q-ans");
    if (ansButton) {
      const q = ansButton.closest(".q-row").dataset.q;
      if (sheetState.revealed.has(q)) sheetState.revealed.delete(q);
      else sheetState.revealed.add(q);
      redrawSheet();
      return;
    }

    const button = event.target.closest(".q-opts button");
    if (!button) return;
    const row = button.closest(".q-row");
    const q = row.dataset.q;
    const value = button.dataset.v;
    // 再点一次同一个选项 = 取消作答
    if (sheetState.answers[q] === value) delete sheetState.answers[q];
    else sheetState.answers[q] = value;
    refreshRow(row);
    updateSheetStats();
    scheduleSheetSave();
    if (state.paper?.analysis) renderAnswers();
  });

  $("sheetRevealAll").addEventListener("click", () => {
    const correct = correctAnswers();
    if (!correct) return flash("本地没有 answers.json，看不到答案");
    sheetState.revealed = new Set(Object.keys(correct));
    redrawSheet();
    flash("已显示全部答案，再点「全部隐藏」可以收回去");
  });

  $("sheetHideAll").addEventListener("click", () => {
    sheetState.revealed.clear();
    redrawSheet();
  });

  $("sheetSave").addEventListener("click", () => saveSheet(true));

  $("sheetClear").addEventListener("click", () => {
    if (!window.confirm("清空本卷的作答记录？（不影响错题本）")) return;
    sheetState.answers = {};
    sheetState.revealed.clear();
    renderSheet();
    saveSheet(true);
  });

  $("sheetMarkWrong").addEventListener("click", async () => {
    const correct = correctAnswers();
    if (!correct) return flash("没有 answers.json，无法判分");
    const wrongs = Object.entries(sheetState.answers)
      .filter(([q, mine]) => mine && correct[q] && mine !== correct[q]);
    if (wrongs.length === 0) return flash("没有判错的题");

    for (const [q, mine] of wrongs) {
      await api("/api/study", {
        collection: "wrong",
        item: {
          key: `${paperId}::${q}`,
          q,
          answer: mine,
          correct: correct[q],
          note: "",
          paper: state.paper?.meta?.title ?? paperId,
          at: new Date().toISOString(),
        },
      });
    }
    study = await api("/api/study");
    renderStudy();
    flash(`已把 ${wrongs.length} 道错题记进错题本`);
  });
};

/* ---------------- 计时器（限时模拟） ---------------- */

const timer = {
  key: "write", duration: 30 * 60, remaining: 30 * 60,
  running: false, fired: false, baseRemaining: 30 * 60, startedAt: 0, tick: null,
};

const timerText = () => {
  const abs = Math.abs(timer.remaining);
  return `${timer.remaining < 0 ? "-" : ""}${String(Math.floor(abs / 60)).padStart(2, "0")}:${String(abs % 60).padStart(2, "0")}`;
};

const renderTimer = () => {
  const button = $("timerPlay");
  button.textContent = `⏱ ${timerText()}`;
  button.classList.toggle("running", timer.running);
  button.classList.toggle("timeup", timer.duration > 0 && timer.remaining <= 0);
  const label = $("timerPreset").selectedOptions[0]?.textContent ?? "";
  button.title = `${timer.running ? "暂停" : "开始"}计时 · ${label}`;
};

const persistTimer = () => {
  try {
    localStorage.setItem("zhenti:timer", JSON.stringify({
      key: timer.key, duration: timer.duration, remaining: timer.remaining, running: timer.running, at: Date.now(),
    }));
  } catch { /* 隐私模式下 localStorage 不可用，忽略 */ }
};

const stopTick = () => { if (timer.tick) window.clearInterval(timer.tick); timer.tick = null; };

const pauseTimer = () => { stopTick(); timer.running = false; renderTimer(); persistTimer(); };

/** 每次都用墙上时间重算：后台标签页会被节流，靠"每秒自减"必然漂。 */
const tickOnce = () => {
  const elapsed = Math.round((Date.now() - timer.startedAt) / 1000);
  timer.remaining = timer.duration === 0
    ? timer.baseRemaining + elapsed
    : Math.max(0, timer.baseRemaining - elapsed);
  if (timer.duration > 0 && timer.remaining === 0 && !timer.fired) {
    timer.fired = true;
    pauseTimer();
    flash("时间到");
    return;
  }
  renderTimer();
  persistTimer();
};

const startTimer = () => {
  stopTick();
  timer.running = true;
  timer.fired = false;
  timer.baseRemaining = timer.remaining;
  timer.startedAt = Date.now();
  timer.tick = window.setInterval(tickOnce, 500);
  renderTimer();
  persistTimer();
};

const setupTimer = () => {
  try {
    const saved = JSON.parse(localStorage.getItem("zhenti:timer") ?? "null");
    if (saved && typeof saved.duration === "number") {
      timer.key = saved.key ?? "write";
      $("timerPreset").value = timer.key;
      timer.duration = saved.duration;
      timer.remaining = Math.max(0, Number(saved.remaining ?? saved.duration));
      if (saved.running && saved.at) {
        const elapsed = Math.round((Date.now() - saved.at) / 1000);
        timer.remaining = timer.duration === 0 ? timer.remaining + elapsed : Math.max(0, timer.remaining - elapsed);
      }
    }
  } catch { /* 忽略坏掉的存档 */ }

  $("timerPlay").addEventListener("click", () => (timer.running ? pauseTimer() : startTimer()));
  $("timerReset").addEventListener("click", () => {
    pauseTimer(); timer.remaining = timer.duration; timer.fired = false; renderTimer(); persistTimer();
  });
  $("timerPreset").addEventListener("change", (event) => {
    const option = event.target.selectedOptions[0];
    timer.key = option.value;
    timer.duration = Number(option.dataset.min ?? 30) * 60;
    pauseTimer(); timer.remaining = timer.duration; timer.fired = false; renderTimer(); persistTimer();
  });
  renderTimer();
};

/* ---------------- 侧栏折叠 ---------------- */

const togglePanel = (hide) => {
  const next = typeof hide === "boolean" ? hide : !document.body.classList.contains("panel-hidden");
  document.body.classList.toggle("panel-hidden", next);
  $("panelExpand").hidden = !next;
  try { localStorage.setItem("zhenti:panel", next ? "hidden" : "shown"); } catch { /* 忽略 */ }
  // 侧栏宽度变了不等于窗口 resize，主动通知阅读器重算适宽
  window.setTimeout(() => window.dispatchEvent(new Event("resize")), 30);
};

/* ---------------- 侧栏宽度拖拽 ---------------- */

const PANEL_MIN = 280;
const PANEL_MAX = 900;
const PANEL_DEFAULT = 380;

/** 上限要跟着窗口走：左侧阅读区至少留 360px，否则缩到小窗口时侧栏会把卷子挤没 */
const panelMax = () => Math.max(PANEL_MIN, Math.min(PANEL_MAX, window.innerWidth - 360));

/** 写宽度。persist=true 时顺手存 localStorage，下次进来还是这个宽度。 */
const setPanelWidth = (width, persist = false) => {
  if (!Number.isFinite(width)) return;
  const clamped = Math.round(Math.max(PANEL_MIN, Math.min(panelMax(), width)));
  document.documentElement.style.setProperty("--panel-w", `${clamped}px`);
  if (persist) {
    try { localStorage.setItem("zhenti:panelW", String(clamped)); } catch { /* 隐私模式忽略 */ }
  }
  // 阅读器自己的 resize 监听带 180ms 防抖，这里可以放心每帧都发
  window.dispatchEvent(new Event("resize"));
};

const setupPanelResizer = () => {
  const grip = $("panelResizer");
  const panel = $("sidePanel");
  let dragging = false;

  const widthOf = () => {
    const width = panel.getBoundingClientRect().width;
    return width > 0 ? width : Number.parseInt(getComputedStyle(document.documentElement).getPropertyValue("--panel-w"), 10) || PANEL_DEFAULT;
  };

  grip.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    dragging = true;
    grip.classList.add("is-dragging");
    document.body.classList.add("panel-resizing");
    try { grip.setPointerCapture(event.pointerId); } catch { /* 忽略 */ }
    event.preventDefault();
  });

  grip.addEventListener("pointermove", (event) => {
    if (!dragging) return;
    setPanelWidth(window.innerWidth - event.clientX);
  });

  const stop = (event, persist) => {
    if (!dragging) return;
    dragging = false;
    grip.classList.remove("is-dragging");
    document.body.classList.remove("panel-resizing");
    try { grip.releasePointerCapture(event.pointerId); } catch { /* 忽略 */ }
    if (persist) setPanelWidth(window.innerWidth - event.clientX, true);
    else setPanelWidth(widthOf(), true);
  };

  grip.addEventListener("pointerup", (event) => stop(event, true));
  grip.addEventListener("pointercancel", (event) => stop(event, false));

  grip.addEventListener("dblclick", () => setPanelWidth(PANEL_DEFAULT, true));

  grip.addEventListener("keydown", (event) => {
    const step = event.shiftKey ? 96 : 24;
    let next = null;
    if (event.key === "ArrowLeft") next = widthOf() + step;      // 把手往左 = 侧栏变宽
    else if (event.key === "ArrowRight") next = widthOf() - step;
    else if (event.key === "Home") next = PANEL_DEFAULT;
    if (next === null) return;
    event.preventDefault();
    setPanelWidth(next, true);
  });

  // 窗口变小后，之前存的宽度可能把阅读区挤没了，这里回收一次
  window.addEventListener("resize", () => {
    if (document.body.classList.contains("panel-hidden")) return;
    const current = widthOf();
    if (current > panelMax()) setPanelWidth(panelMax(), true);
  });
};

/* ---------------- tabs / toolbar ---------------- */

const setupTabs = () => {
  for (const button of document.querySelectorAll(".tabs button")) {
    button.addEventListener("click", () => showTab(button.dataset.tab));
  }
};

const setupToolbar = () => {
  const turnPage = (direction) => {
    const double = viewer.state.mode.startsWith("double");
    const current = double ? viewer.state.page - ((viewer.state.page - 1) % 2) : viewer.state.page;
    viewer.goTo(current + direction * (double ? 2 : 1));
  };
  $("prev").addEventListener("click", () => turnPage(-1));
  $("next").addEventListener("click", () => turnPage(1));
  $("pageInput").addEventListener("change", (event) => viewer.goTo(Number(event.target.value)));
  $("zoomIn").addEventListener("click", () => viewer.zoomBy(1.15));
  $("zoomOut").addEventListener("click", () => viewer.zoomBy(1 / 1.15));
  $("zoomSelect").addEventListener("change", (event) => {
    const value = event.target.value;
    if (value === "fitWidth" || value === "fitHeight" || value === "fitPage") viewer.setZoom(value);
    else viewer.setZoom("percent", Number(value) / 100);
  });
  $("viewMode").addEventListener("change", (event) => viewer.setMode(event.target.value));
  $("openAnalysis").addEventListener("click", () => openAnalysisAt());
  $("backToPaper").addEventListener("click", backToPaper);
  $("anaBack").addEventListener("click", () => { $("anaPane").hidden = true; });
  $("anaFull").addEventListener("click", () => openAnalysisFullscreen(ana.current));
  $("anaZoomIn").addEventListener("click", () => {
    ana.zoom = Math.min(3, Math.round(ana.zoom * 1.2 * 100) / 100);
    renderAnaPages();
  });
  $("anaZoomOut").addEventListener("click", () => {
    ana.zoom = Math.max(0.6, Math.round((ana.zoom / 1.2) * 100) / 100);
    renderAnaPages();
  });
  $("anaScroll").addEventListener("scroll", syncAnaPage, { passive: true });
  $("panelToggle").addEventListener("click", () => togglePanel());
  $("panelExpand").addEventListener("click", () => togglePanel(false));

  document.querySelectorAll(".viewer-toolbar .tool").forEach((button) => {
    button.addEventListener("click", () => {
      viewer.setTool(button.dataset.tool ?? "cursor");
      document.querySelectorAll(".viewer-toolbar .tool").forEach((other) => other.classList.toggle("active", other === button));
    });
  });
  document.querySelectorAll(".swatch").forEach((button) => {
    button.addEventListener("click", () => {
      viewer.setColor(button.dataset.color ?? "#e11d48");
      document.querySelectorAll(".swatch").forEach((item) => item.classList.toggle("active", item === button));
      if (viewer.ink.tool === "cursor" || viewer.ink.tool === "eraser") document.querySelector('.tool[data-tool="pen"]').click();
    });
  });
  document.querySelector('.swatch[data-color="#e11d48"]')?.classList.add("active");
  $("inkUndo").addEventListener("click", viewer.undoInk);
  $("inkClear").addEventListener("click", viewer.clearInk);

  document.addEventListener("keydown", (event) => {
    if (event.target.matches("input, textarea, select")) return;
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") { event.preventDefault(); viewer.undoInk(); return; }
    if (event.key === "Escape") viewer.setTool("cursor");
    const double = viewer.state.mode.startsWith("double");
    const current = double ? viewer.state.page - ((viewer.state.page - 1) % 2) : viewer.state.page;
    const step = double ? 2 : 1;
    if (event.key === "ArrowLeft") viewer.goTo(current - step);
    if (event.key === "ArrowRight") viewer.goTo(current + step);
    if (event.key === " ") { event.preventDefault(); $("play").click(); }
  });

  const notes = $("notes");
  let notesTimer = null;
  notes.addEventListener("input", () => {
    window.clearTimeout(notesTimer);
    $("notesState").textContent = "输入中…";
    notesTimer = window.setTimeout(async () => {
      try {
        await api("/api/notes", { id: paperId, content: notes.value });
        $("notesState").textContent = "已保存";
      } catch (error) {
        $("notesState").textContent = `保存失败：${error.message}`;
      }
    }, 600);
  });

  window.addEventListener("beforeunload", () => {
    const audio = $("audio");
    if (!audio.currentTime || state.viewing !== "paper") return;
    navigator.sendBeacon?.("/api/progress", new Blob([JSON.stringify({
      id: paperId, page: viewer.state.page, audioTime: audio.currentTime, scale: viewer.state.scale,
      view: { mode: viewer.state.mode, zoomKind: viewer.state.zoomKind },
    })], { type: "application/json" }));
  });
};

/* ---------------- boot ---------------- */

const boot = async () => {
  if (!paperId) {
    document.body.innerHTML = "<p style='padding:24px'>缺少 ?id= 参数，请从<a href=\"/\">首页</a>进入。</p>";
    return;
  }
  const [paper, studyData] = await Promise.all([api(`/api/paper?id=${encodeURIComponent(paperId)}`), api("/api/study")]);
  state.paper = paper;
  study = studyData;

  document.title = `${paper.meta.title} · 真题工作台`;
  $("paperTitle").textContent = paper.meta.title;
  $("notes").value = paper.notes ?? "";
  $("pageCount").textContent = "…";
  $("openAnalysis").hidden = !paper.analysisFile;

  try { if (localStorage.getItem("zhenti:panel") === "hidden") { document.body.classList.add("panel-hidden"); $("panelExpand").hidden = false; } } catch { /* 忽略 */ }
  // 侧栏宽度要在阅读器算「适合宽度」之前设好，否则首屏按默认 380px 排版后再跳一下
  try {
    const savedWidth = Number(localStorage.getItem("zhenti:panelW"));
    if (Number.isFinite(savedWidth) && savedWidth > 0) setPanelWidth(savedWidth);
  } catch { /* 忽略 */ }

  setupTabs();
  setupToolbar();
  setupPanelResizer();
  setupTimer();
  setupStudy();
  setupSheet();
  setupAudio();
  renderStudy();

  sheetState.count = paper.sheet?.count
    ?? Math.max(55, ...Object.keys(paper.answers ?? {}).filter((k) => /^\d+$/.test(k)).map(Number));
  sheetState.answers = { ...(paper.sheet?.answers ?? {}) };
  sheetState.revealed = new Set();
  renderSheet();
  renderAnswers();

  if (paper.pdfFile) {
    const view = paper.progress?.view ?? {};
    await viewer.load(`/data/${paperId}/${paper.pdfFile}`, {
      page: paper.progress?.page ?? 1,
      scale: paper.progress?.scale ?? null,
      zoomKind: view.zoomKind ?? (paper.progress?.scale ? "percent" : "fitWidth"),
      mode: view.mode ?? "continuous",
    });
    $("viewMode").value = viewer.state.mode;
    await viewer.loadInk();
  } else {
    // 只有答案解析的套卷：阅读区给出说明，侧栏直接把解析摊开
    renderPaperless();
    if (paper.analysisFile) await openAnalysisAt();
  }
  refreshDownload();
  window.__reader = state;   // 调试用
  window.__viewer = viewer;
};

boot().catch((error) => {
  document.body.innerHTML = `<pre style="padding:24px;color:#b91c1c">加载失败：${escapeHtml(error?.message ?? error)}</pre>`;
});
