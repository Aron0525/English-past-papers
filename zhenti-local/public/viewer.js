/**
 * 多页 PDF 阅读器：整份文档上下连续滚动，可切单页 / 双页排列，缩放、文字层查词、划词、圈画。
 *
 * 结构：scrollEl > pagesEl > .spread（一行）> .page（一页）
 *   .page > canvas（正文）+ canvas.inkLayer（笔迹）+ .textLayer（可选中文字）
 *
 * 两条硬约束（pdf.js 的坑，别改回去）：
 *  - 一个 canvas 同一时间只能有一个 render，渲染全部串行排队；
 *  - 文字层字号是 calc(var(--scale-factor) * Npx)，缩放变了必须重设。
 */
import * as pdfjsLib from "./vendor/pdfjs/pdf.min.mjs";

pdfjsLib.GlobalWorkerOptions.workerSrc = "./vendor/pdfjs/pdf.worker.min.mjs";

const PAGE_GAP = 16;       // 与 .viewer-scroll 的 padding 一致
const WORD_RE = /[A-Za-z][A-Za-z'’-]*/g;

export const VIEW_MODES = [
  { id: "continuous", label: "上下滚动 · 单页" },
  { id: "double-continuous", label: "上下滚动 · 双页" },
];

const normalizeMode = (mode) => (VIEW_MODES.some((item) => item.id === mode) ? mode : "continuous");

const escapeHtml = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));

const wordify = (text) => {
  let out = "";
  let last = 0;
  for (const match of text.matchAll(WORD_RE)) {
    out += escapeHtml(text.slice(last, match.index));
    out += `<aw>${escapeHtml(match[0])}</aw>`;
    last = match.index + match[0].length;
  }
  return out + escapeHtml(text.slice(last));
};

export const createViewer = ({ scrollEl, pagesEl, paperId, api, flash, onChange, onStudyChanged, titleOf }) => {
  const state = {
    doc: null,
    page: 1,
    scale: 1,
    zoomKind: "fitWidth",   // fitWidth | fitHeight | fitPage | percent
    mode: "continuous",
    pages: [],              // PageView[]
    spreads: [],
    ready: false,
  };

  const isDouble = () => state.mode.startsWith("double");
  const isContinuous = () => state.mode === "continuous" || state.mode === "double-continuous";
  const clampPage = (n) => Math.min(Math.max(1, Math.round(n) || 1), state.doc?.numPages ?? 1);

  const notify = () => onChange?.({
    page: state.page, scale: state.scale, mode: state.mode, zoomKind: state.zoomKind,
  });

  /* ---------------- 页面元素 ---------------- */

  const makePage = (num) => {
    const el = document.createElement("div");
    el.className = "page";
    el.dataset.page = String(num);
    el.innerHTML = `<canvas></canvas><canvas class="inkLayer"></canvas><div class="textLayer"></div>`;
    const view = {
      num, el,
      canvas: el.querySelector("canvas"),
      ink: el.querySelector(".inkLayer"),
      textEl: el.querySelector(".textLayer"),
      base: { width: 612, height: 792 },
      renderedScale: 0,
      renderTask: null,
      textTask: null,
      visible: false,
      queued: false,
    };
    setupInkForPage(view);
    return view;
  };

  const buildSpreads = () => {
    pagesEl.replaceChildren();
    state.spreads = [];
    const per = isDouble() ? 2 : 1;
    for (let i = 0; i < state.pages.length; i += per) {
      const spread = document.createElement("div");
      spread.className = "spread";
      const group = state.pages.slice(i, i + per);
      for (const view of group) spread.append(view.el);
      pagesEl.append(spread);
      state.spreads.push({ el: spread, pages: group });
    }
    applyVisibility();
  };

  const spreadOf = (num) => state.spreads.find((s) => s.pages.some((p) => p.num === num));

  /** 非连续模式只显示当前这一行，其余整行隐藏，滚动条自然消失。 */
  const applyVisibility = () => {
    const current = spreadOf(state.page);
    for (const spread of state.spreads) {
      spread.el.style.display = isContinuous() || spread === current ? "" : "none";
    }
    for (const view of state.pages) {
      // 连续模式由 IntersectionObserver 决定谁要渲染，这里只负责非连续的单行显示
      if (!isContinuous()) view.visible = spreadOf(view.num) === current;
    }
  };

  /* ---------------- 尺寸与缩放 ---------------- */

  const applySizes = () => {
    const ratio = window.devicePixelRatio || 1;
    for (const view of state.pages) {
      const width = Math.max(1, Math.floor(view.base.width * state.scale));
      const height = Math.max(1, Math.floor(view.base.height * state.scale));
      view.el.style.width = `${width}px`;
      view.el.style.height = `${height}px`;
      view.canvas.style.width = `${width}px`;
      view.canvas.style.height = `${height}px`;
      view.textEl.style.width = `${width}px`;
      view.textEl.style.height = `${height}px`;
      view.textEl.style.setProperty("--scale-factor", String(state.scale));
      view.ink.width = Math.max(1, Math.round(width * ratio));
      view.ink.height = Math.max(1, Math.round(height * ratio));
      redrawInk(view);
    }
  };

  const invalidate = () => {
    for (const view of state.pages) {
      view.renderedScale = 0;
      try { view.renderTask?.cancel(); } catch { /* 已经渲完的不用管 */ }
      try { view.textTask?.cancel(); } catch { /* 同上 */ }
    }
  };

  /** 缩放前记住"正在看哪页的哪个位置"，缩放后还停在那儿。 */
  const anchor = () => {
    if (!isContinuous()) return { page: state.page, ratio: 0 };
    const view = state.pages[state.page - 1];
    if (!view) return { page: state.page, ratio: 0 };
    const top = scrollEl.getBoundingClientRect().top;
    const rect = view.el.getBoundingClientRect();
    return { page: view.num, ratio: rect.height ? (top - rect.top) / rect.height : 0 };
  };

  const restoreAnchor = (mark) => {
    if (!isContinuous()) { scrollEl.scrollTop = 0; return; }
    const view = state.pages[mark.page - 1];
    if (!view) return;
    const top = scrollEl.getBoundingClientRect().top;
    const rect = view.el.getBoundingClientRect();
    scrollEl.scrollTop += rect.top - top + mark.ratio * rect.height - PAGE_GAP;
  };

  const fitScale = (kind) => {
    const view = state.pages[state.page - 1] ?? state.pages[0];
    if (!view) return 1;
    const cols = isDouble() ? 2 : 1;
    const availW = scrollEl.clientWidth - PAGE_GAP * 2 - (cols - 1) * 14 - 4;
    const availH = scrollEl.clientHeight - PAGE_GAP * 2 - 4;
    const byWidth = (availW / cols) / view.base.width;
    const byHeight = availH / view.base.height;
    if (kind === "fitHeight") return byHeight;
    if (kind === "fitPage") return Math.min(byWidth, byHeight);
    return byWidth;
  };

  const applyZoom = async (kind, value, { keep = true } = {}) => {
    state.zoomKind = kind;
    if (kind === "percent") state.scale = Math.min(5, Math.max(0.2, value));
    else state.scale = Math.min(5, Math.max(0.05, fitScale(kind)));
    const mark = keep ? anchor() : { page: state.page, ratio: 0 };
    invalidate();
    applySizes();
    restoreAnchor(mark);
    await renderVisible();
    updateChrome();
    notify();
  };

  const setZoom = (kind, value) => applyZoom(kind, value);
  const zoomBy = (factor) => applyZoom("percent", Math.min(5, Math.max(0.2, state.scale * factor)));

  const setMode = async (mode) => {
    if (!VIEW_MODES.some((m) => m.id === mode)) return;
    const mark = anchor();
    state.mode = mode;
    buildSpreads();
    if (state.zoomKind !== "percent") state.scale = Math.min(5, Math.max(0.05, fitScale(state.zoomKind)));
    invalidate();
    applySizes();
    applyVisibility();
    restoreAnchor(mark);
    observePages();
    await renderVisible();
    updateChrome();
    notify();
  };

  /* ---------------- 渲染（串行队列） ---------------- */

  let rendering = false;
  let renderAgain = false;

  const renderVisible = async () => {
    // 渲染途中又来了新需求（滚动/缩放）就打标记，结束后补一轮，别直接丢掉
    if (rendering) { renderAgain = true; return; }
    rendering = true;
    try {
      for (;;) {
        renderAgain = false;
        for (;;) {
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

  const renderOne = async (view) => {
    if (!state.doc) return;
    const scaleAtStart = state.scale;
    const page = await state.doc.getPage(view.num);
    if (scaleAtStart !== state.scale) return;
    const viewport = page.getViewport({ scale: scaleAtStart });
    const ratio = window.devicePixelRatio || 1;
    const canvas = view.canvas;
    canvas.width = Math.floor(viewport.width * ratio);
    canvas.height = Math.floor(viewport.height * ratio);
    view.el.classList.add("rendering");
    try {
      view.renderTask = page.render({
        canvasContext: canvas.getContext("2d"),
        viewport,
        transform: ratio === 1 ? undefined : [ratio, 0, 0, ratio, 0, 0],
      });
      await view.renderTask.promise;
    } catch (error) {
      if (error?.name !== "RenderingCancelledException") console.warn(`第 ${view.num} 页渲染失败`, error);
      return;
    } finally {
      view.renderTask = null;
      view.el.classList.remove("rendering");
    }
    view.renderedScale = scaleAtStart;
    await renderText(view, page, viewport);
  };

  const renderText = async (view, page, viewport) => {
    view.textEl.replaceChildren();
    try { view.textTask?.cancel(); } catch { /* 忽略 */ }
    try {
      view.textTask = new pdfjsLib.TextLayer({
        textContentSource: page.streamTextContent(),
        container: view.textEl,
        viewport,
      });
      await view.textTask.render();
    } catch (error) {
      const name = String(error?.name ?? "");
      if (name !== "AbortException" && !/cancel/i.test(name)) console.warn("文字层渲染失败:", error);
      return;
    }
    // 只切叶子节点：带子元素的 span 是定位容器，动了会乱版
    for (const span of view.textEl.querySelectorAll("span")) {
      if (span.children.length > 0) continue;
      const text = span.textContent ?? "";
      if (text.length < 2 || !/[A-Za-z]{2}/.test(text)) continue;
      span.innerHTML = wordify(text);
    }
  };

  /* ---------------- 滚动联动 ---------------- */

  let observer = null;
  const observePages = () => {
    observer?.disconnect();
    observer = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        const view = state.pages[Number(entry.target.dataset.page) - 1];
        if (view) view.visible = isContinuous()
          ? entry.isIntersecting
          : spreadOf(view.num) === spreadOf(state.page);
      }
      renderVisible();
    }, { root: scrollEl, rootMargin: "700px 0px" });
    for (const view of state.pages) observer.observe(view.el);
  };

  let scrollScheduled = false;
  const syncPageFromScroll = () => {
    if (!isContinuous() || !state.ready) return;
    const top = scrollEl.getBoundingClientRect().top;
    const bottom = top + scrollEl.clientHeight;
    let best = null;
    let bestArea = 0;
    for (const view of state.pages) {
      const rect = view.el.getBoundingClientRect();
      const area = Math.max(0, Math.min(rect.bottom, bottom) - Math.max(rect.top, top));
      if (area > bestArea) { bestArea = area; best = view; }
    }
    if (best && best.num !== state.page) {
      state.page = best.num;
      updateChrome();
      notify();
    }
  };

  scrollEl.addEventListener("scroll", () => {
    hideWordPop();
    closeDict();
    if (scrollScheduled) return;
    scrollScheduled = true;
    requestAnimationFrame(() => { scrollScheduled = false; syncPageFromScroll(); });
  }, { passive: true });

  const goTo = async (num) => {
    if (!state.doc) return;
    state.page = clampPage(num);
    if (isContinuous()) {
      const view = state.pages[state.page - 1];
      const top = scrollEl.getBoundingClientRect().top;
      const rect = view.el.getBoundingClientRect();
      scrollEl.scrollTop += rect.top - top - PAGE_GAP;
      view.visible = true;
    } else {
      applyVisibility();
      scrollEl.scrollTop = 0;
    }
    updateChrome();
    await renderVisible();
    notify();
  };

  const updateChrome = () => {
    document.getElementById("pageInput").value = String(state.page);
    const spread = spreadOf(state.page);
    const first = spread?.pages[0]?.num ?? state.page;
    const last = spread?.pages.at(-1)?.num ?? state.page;
    document.getElementById("pageLabel").textContent = isDouble() && first !== last
      ? `第 ${first}–${last} 页`
      : `第 ${state.page} 页`;
    document.getElementById("zoomLabel").textContent = `${Math.round(state.scale * 100)}%`;
    const modeSelect = document.getElementById("viewMode");
    if (modeSelect) modeSelect.value = state.mode;
    const select = document.getElementById("zoomSelect");
    if (select) {
      const custom = document.getElementById("zoomCustom");
      const value = state.zoomKind === "percent" ? String(Math.round(state.scale * 100)) : state.zoomKind;
      const preset = [...select.options].some((option) => option.value === value);
      if (custom) {
        custom.hidden = preset;
        custom.textContent = `${Math.round(state.scale * 100)}%`;
      }
      select.value = preset ? value : "custom";
    }
  };

  /* ---------------- 圈画 ---------------- */

  const ink = { tool: "cursor", color: "#e11d48", pages: {}, current: null, drawing: false, saveTimer: null, view: null };
  const strokesOf = (num) => {
    const key = String(num);
    if (!ink.pages[key]) ink.pages[key] = [];
    return ink.pages[key];
  };

  function paintStroke(ctx, stroke, width, height) {
    const points = stroke.p ?? [];
    if (points.length < 2) return;
    ctx.save();
    ctx.strokeStyle = stroke.c;
    ctx.lineWidth = Math.max(0.6, stroke.w * width);
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.globalAlpha = stroke.t === "hl" ? 0.35 : 1;
    ctx.beginPath();
    ctx.moveTo(points[0][0] * width, points[0][1] * height);
    for (let i = 1; i < points.length - 1; i += 1) {
      const [x1, y1] = points[i];
      const [x2, y2] = points[i + 1];
      const mx = ((x1 + x2) / 2) * width;
      const my = ((y1 + y2) / 2) * height;
      ctx.quadraticCurveTo(x1 * width, y1 * height, mx, my);
    }
    const last = points[points.length - 1];
    ctx.lineTo(last[0] * width, last[1] * height);
    ctx.stroke();
    ctx.restore();
  }

  function redrawInk(view) {
    if (!view) return;
    const canvas = view.ink;
    const ctx = canvas.getContext("2d");
    const ratio = window.devicePixelRatio || 1;
    const width = canvas.width / ratio;
    const height = canvas.height / ratio;
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, height);
    for (const stroke of strokesOf(view.num)) paintStroke(ctx, stroke, width, height);
    if (ink.current && ink.view === view) paintStroke(ctx, ink.current, width, height);
  }

  const pointOf = (event, view) => {
    const box = view.el.getBoundingClientRect();
    const x = (event.clientX - box.left) / box.width;
    const y = (event.clientY - box.top) / box.height;
    return [Math.min(Math.max(x, -0.02), 1.02), Math.min(Math.max(y, -0.02), 1.02)];
  };

  const distanceToStroke = (stroke, point) => {
    let best = Infinity;
    const { p: points } = stroke;
    for (let i = 1; i < points.length; i += 1) {
      const [x1, y1] = points[i - 1];
      const [x2, y2] = points[i];
      const dx = x2 - x1;
      const dy = y2 - y1;
      const lengthSq = dx * dx + dy * dy;
      const t = lengthSq === 0 ? 0 : Math.min(Math.max(((point[0] - x1) * dx + (point[1] - y1) * dy) / lengthSq, 0), 1);
      best = Math.min(best, Math.hypot(point[0] - (x1 + t * dx), point[1] - (y1 + t * dy)));
    }
    return best;
  };

  const eraseAt = (point, view) => {
    const strokes = strokesOf(view.num);
    for (let i = strokes.length - 1; i >= 0; i -= 1) {
      if (distanceToStroke(strokes[i], point) <= 0.012 + strokes[i].w) {
        strokes.splice(i, 1);
        redrawInk(view);
        scheduleInkSave();
        return true;
      }
    }
    return false;
  };

  // 保存排队：两次 POST 同时在路上时，先发的可能后到，会把新笔迹覆盖成旧的
  let inkQueue = Promise.resolve();
  const scheduleInkSave = () => {
    window.clearTimeout(ink.saveTimer);
    ink.saveTimer = window.setTimeout(() => {
      inkQueue = inkQueue
        .then(() => api("/api/ink", { id: paperId, pages: ink.pages }))
        .then(() => flash("笔迹已保存"))
        .catch((error) => flash(`笔迹保存失败：${error.message}`));
    }, 700);
  };

  function setupInkForPage(view) {
    const canvas = view.ink;
    canvas.addEventListener("pointerdown", (event) => {
      if (ink.tool === "cursor") return;
      event.preventDefault();
      canvas.setPointerCapture(event.pointerId);
      ink.view = view;
      ink.drawing = true;
      if (ink.tool === "eraser") { eraseAt(pointOf(event, view), view); return; }
      ink.current = {
        t: ink.tool === "hl" ? "hl" : "pen",
        c: ink.color,
        w: ink.tool === "hl" ? 0.02 : 0.0022,
        p: [pointOf(event, view)],
      };
    });
    canvas.addEventListener("pointermove", (event) => {
      if (!ink.drawing || ink.view !== view) return;
      if (ink.tool === "eraser") { eraseAt(pointOf(event, view), view); return; }
      if (!ink.current) return;
      const point = pointOf(event, view);
      const last = ink.current.p[ink.current.p.length - 1];
      if (Math.hypot(point[0] - last[0], point[1] - last[1]) < 0.0015) return;
      ink.current.p.push(point);
      redrawInk(view);
    });
    const finish = () => {
      if (!ink.drawing || ink.view !== view) return;
      ink.drawing = false;
      if (ink.current) {
        if (ink.current.p.length > 1) strokesOf(view.num).push(ink.current);
        ink.current = null;
        redrawInk(view);
        scheduleInkSave();
      }
    };
    canvas.addEventListener("pointerup", finish);
    canvas.addEventListener("pointercancel", finish);
    canvas.addEventListener("pointerleave", finish);
  }

  const setTool = (tool) => {
    ink.tool = tool;
    for (const view of state.pages) view.el.classList.toggle("drawing", tool !== "cursor");
    if (tool !== "cursor") closeDict();
  };
  const setColor = (color) => { ink.color = color; };
  const undoInk = () => {
    const strokes = strokesOf(state.page);
    if (!strokes.length) return flash("本页没有可撤销的笔迹");
    strokes.pop();
    redrawInk(state.pages[state.page - 1]);
    scheduleInkSave();
    return undefined;
  };
  const clearInk = () => {
    const strokes = strokesOf(state.page);
    if (!strokes.length) return flash("本页本来就没有笔迹");
    if (!window.confirm(`清空第 ${state.page} 页的全部笔迹？`)) return undefined;
    ink.pages[String(state.page)] = [];
    redrawInk(state.pages[state.page - 1]);
    scheduleInkSave();
    return flash(`已清空第 ${state.page} 页笔迹`);
  };

  /* ---------------- 点词查词 ---------------- */

  const dictPop = () => document.getElementById("dictPop");
  let dictToken = 0;

  const placeDict = (rect) => {
    const pop = dictPop();
    const gap = 10;
    let top = rect.bottom + gap;
    if (top + pop.offsetHeight > window.innerHeight - 12) top = Math.max(12, rect.top - pop.offsetHeight - gap);
    const left = Math.min(Math.max(rect.left + rect.width / 2 - pop.offsetWidth / 2, 12), window.innerWidth - pop.offsetWidth - 12);
    pop.style.left = `${Math.round(left)}px`;
    pop.style.top = `${Math.round(top)}px`;
  };

  function closeDict() {
    dictPop().hidden = true;
    pagesEl.querySelectorAll("aw.is-looked").forEach((el) => el.classList.remove("is-looked"));
  }

  const showDict = async (word, anchorEl) => {
    const token = ++dictToken;
    anchorEl?.classList.add("is-looked");
    const pop = dictPop();
    pop.hidden = false;
    pop.dataset.word = word;
    document.getElementById("dictWord").textContent = word;
    document.getElementById("dictPhonetic").textContent = "";
    document.getElementById("dictBody").innerHTML = '<p class="dict-empty">查词中…</p>';
    const fallback = { left: window.innerWidth / 2, top: 80, bottom: 80, width: 0 };
    placeDict(anchorEl ? anchorEl.getBoundingClientRect() : fallback);

    let data = null;
    try {
      data = await api(`/api/dict?word=${encodeURIComponent(word)}`);
    } catch (error) {
      data = { hit: false, error: error.message };
    }
    if (token !== dictToken) return;

    const body = document.getElementById("dictBody");
    if (!data?.hit) {
      const guesses = Array.isArray(data?.guesses) ? data.guesses.filter((g) => g !== word).slice(0, 4) : [];
      body.innerHTML = `<p class="dict-empty">${guesses.length
        ? `词库里没有这个词。是不是 ${guesses.map((g) => `<button class="dict-guess" data-w="${escapeHtml(g)}">${escapeHtml(g)}</button>`).join(" ")} ？`
        : `词库里没有这个词${data?.error ? `（${escapeHtml(data.error)}）` : "，可能是人名或专名"}。可以手动加进生词本。`}</p>`;
      placeDict(anchorEl ? anchorEl.getBoundingClientRect() : fallback);
      return;
    }

    document.getElementById("dictWord").textContent = data.word ?? word;
    document.getElementById("dictPhonetic").textContent = data.k ? `/${data.k.replace(/ә/g, "ə").replace(/'/g, "ˈ")}/` : "";
    pop.dataset.word = data.word ?? word;

    const lines = String(data.t ?? "").split(/[；;\n]+/).map((s) => s.trim()).filter(Boolean);
    const html = [];
    if (data.f && data.f !== word) html.push(`<p class="dict-lemma">${escapeHtml(word)} → 原形 ${escapeHtml(data.f)}</p>`);
    const tagLabel = { zk: "中考", gk: "高考", cet4: "四级", cet6: "六级", ky: "考研", toefl: "托福", ielts: "雅思", gre: "GRE" };
    const tags = String(data.tag ?? "").split(/\s+/).filter((t) => tagLabel[t]).map((t) => tagLabel[t]);
    if (tags.length) html.push(`<p class="dict-tags">${tags.map((t) => `<span>${t}</span>`).join("")}</p>`);
    for (const line of lines.slice(0, 12)) {
      const match = line.match(/^([a-z]+\.)\s*(.*)$/i);
      html.push(match
        ? `<p><i style="color:var(--muted);font-style:normal">${escapeHtml(match[1])}</i> ${escapeHtml(match[2])}</p>`
        : `<p>${escapeHtml(line)}</p>`);
    }
    body.innerHTML = html.join("") || '<p class="dict-empty">这条没有中文释义。</p>';
    placeDict(anchorEl ? anchorEl.getBoundingClientRect() : fallback);
  };

  const addWord = async (word) => {
    if (!word) return;
    await api("/api/study", {
      collection: "wordbook",
      item: { key: `${paperId}::${word.toLowerCase()}`, word, paper: titleOf?.() ?? paperId, at: new Date().toISOString() },
    });
    await onStudyChanged?.();
    flash(`已加入生词本：${word}`);
  };

  pagesEl.addEventListener("click", (event) => {
    if (ink.tool !== "cursor") return;
    const node = event.target.closest?.("aw");
    if (!node) return;
    const selection = window.getSelection();
    if (selection && !selection.isCollapsed && selection.toString().trim().length > 0) return;
    showDict(node.textContent.trim(), node);
  });

  document.getElementById("dictClose").addEventListener("click", closeDict);
  document.getElementById("dictBody").addEventListener("click", (event) => {
    const guess = event.target.closest?.(".dict-guess");
    if (guess) showDict(guess.dataset.w, null);
  });
  document.getElementById("dictSpeak").addEventListener("click", () => {
    const word = dictPop().dataset.word ?? "";
    if (!word || !window.speechSynthesis) return;
    const utter = new SpeechSynthesisUtterance(word);
    utter.lang = "en-US";
    utter.rate = 0.9;
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utter);
  });
  document.getElementById("dictAdd").addEventListener("click", () => {
    addWord(dictPop().dataset.word ?? "").catch((error) => flash(`加入失败：${error.message}`));
  });
  document.addEventListener("mousedown", (event) => {
    if (event.target.closest?.("#dictPop") || event.target.closest?.("aw")) return;
    closeDict();
  });
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeDict(); });

  /* ---------------- 划词入生词本 ---------------- */

  const wordPop = () => document.getElementById("wordPop");
  function hideWordPop() { wordPop().hidden = true; }

  scrollEl.addEventListener("mouseup", () => {
    window.setTimeout(() => {
      const selection = window.getSelection();
      const text = selection?.toString().replace(/\s+/g, " ").trim() ?? "";
      if (!text || text.length > 40 || !selection.rangeCount) return hideWordPop();
      const rect = selection.getRangeAt(0).getBoundingClientRect();
      const pop = wordPop();
      pop.textContent = `加入生词本：${text.length > 16 ? `${text.slice(0, 16)}…` : text}`;
      pop.dataset.word = text;
      pop.hidden = false;
      pop.style.left = `${Math.min(Math.max(rect.left + rect.width / 2, 90), window.innerWidth - 90)}px`;
      pop.style.top = `${Math.max(rect.top - 38, 8)}px`;
      return undefined;
    }, 0);
  });
  document.addEventListener("mousedown", (event) => { if (!event.target.closest("#wordPop")) hideWordPop(); });
  wordPop().addEventListener("click", () => {
    const word = wordPop().dataset.word ?? "";
    hideWordPop();
    addWord(word).then(() => window.getSelection()?.removeAllRanges()).catch((error) => flash(`加入失败：${error.message}`));
  });

  /* ---------------- 窗口尺寸 ---------------- */

  let resizeTimer = null;
  window.addEventListener("resize", () => {
    window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(() => {
      if (!state.ready) return;
      if (state.zoomKind === "percent") { applySizes(); renderVisible(); }
      else applyZoom(state.zoomKind);
    }, 180);
  });

  /* ---------------- 加载 ---------------- */

  /** 换一份 PDF（试题 ↔ 解析）时调用，页码与缩放由调用方决定。 */
  const load = async (url, { page = 1, scale = null, zoomKind = "fitWidth", mode = state.mode } = {}) => {
    state.ready = false;
    state.doc = await pdfjsLib.getDocument(url).promise;
    state.pages = [];
    for (let num = 1; num <= state.doc.numPages; num += 1) {
      const view = makePage(num);
      const pdfPage = await state.doc.getPage(num);
      const base = pdfPage.getViewport({ scale: 1 });
      view.base = { width: base.width, height: base.height };
      state.pages.push(view);
    }
    state.mode = normalizeMode(mode);
    state.page = clampPage(page);
    state.zoomKind = zoomKind;
    state.scale = zoomKind === "percent" && scale ? scale : fitScale(zoomKind);
    buildSpreads();
    applySizes();
    observePages();
    state.ready = true;
    await renderVisible();
    if (isContinuous()) await goTo(state.page);
    updateChrome();
    document.getElementById("pageCount").textContent = String(state.doc.numPages);
    return state;
  };

  const loadInk = async () => {
    try {
      const data = await api(`/api/ink?id=${encodeURIComponent(paperId)}`);
      ink.pages = data?.pages ?? {};
    } catch {
      ink.pages = {};
    }
    for (const view of state.pages) redrawInk(view);
  };

  return {
    state, load, loadInk, goTo, setZoom, zoomBy, setMode,
    setTool, setColor, undoInk, clearInk, closeDict,
    get ink() { return ink; },
    zoomLabel: () => (state.zoomKind === "percent" ? `${Math.round(state.scale * 100)}%` : state.zoomKind),
  };
};
