const state = {
  index: null,
  overview: null,
  filter: "all",
  exam: "all",
  query: "",
};

const $ = (id) => document.getElementById(id);

const escapeHtml = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));

const fetchJson = async (url) => (await fetch(url)).json();

const clock = (seconds) => {
  const total = Math.floor(Number(seconds) || 0);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
};

/* ---------------- 考试类型 ---------------- */

const EXAM_FALLBACK = [
  { id: "cet6", name: "大学英语六级", short: "六级" },
  { id: "cet4", name: "大学英语四级", short: "四级" },
  { id: "tem4", name: "英语专业四级", short: "专四" },
  { id: "tem8", name: "英语专业八级", short: "专八" },
];

const examList = () => {
  const declared = state.index?.exams ?? [];
  const order = state.index?.groupOrder ?? [];
  const merged = declared.map((exam) => {
    // 索引里只写了全名，简称从兜底表补，页签上用小字
    const fallback = EXAM_FALLBACK.find((e) => e.id === exam.id);
    return { ...exam, short: exam.short ?? fallback?.short ?? exam.name };
  });
  for (const fallback of EXAM_FALLBACK) {
    if (!merged.some((e) => e.id === fallback.id)) merged.push(fallback);
  }
  merged.sort((a, b) => {
    const ia = order.indexOf(a.id);
    const ib = order.indexOf(b.id);
    if (ia !== ib) return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
    return EXAM_FALLBACK.findIndex((e) => e.id === a.id) - EXAM_FALLBACK.findIndex((e) => e.id === b.id);
  });
  return merged;
};

const examMeta = (id) => examList().find((e) => e.id === id) ?? { id, name: id, short: id };

/** 按当前选中的考试类型过滤；"all" 时不过滤。 */
const papersInExam = () => {
  const papers = state.index?.papers ?? [];
  return state.exam === "all" ? papers : papers.filter((p) => p.exam === state.exam);
};

/* ---------------- 过滤 ---------------- */

const matchesFilter = (paper) => {
  if (state.filter === "local" && !paper.local.pdf && !paper.local.analysis) return false;
  if (state.filter === "started" && !paper.started) return false;
  if (state.query) {
    const exam = examMeta(paper.exam);
    const haystack = `${paper.title} ${paper.period} ${paper.set} 第${paper.set}套 ${exam.name} ${exam.short}`.toLowerCase();
    if (!haystack.includes(state.query)) return false;
  }
  return true;
};

/* ---------------- 未收录提示 ---------------- */

const showAddHint = (paper) => {
  const box = $("addHint");
  const dir = `zhenti-local/data/${paper.id}/`;
  box.hidden = false;
  box.innerHTML = `
    <div class="add-hint-head">
      <strong>${escapeHtml(paper.title)}</strong>
      <button class="ghost" id="hintClose" title="关闭">✕</button>
    </div>
    <p class="muted">这套还没收录。把它放进下面这个目录就能在本地打开（需要 <code>read.pdf</code>，有听力再加 <code>listen.mp3</code> 或 <code>listen.m4a</code>，想看解析再放 <code>analysis.pdf</code>）：</p>
    <div class="copyrow">
      <code>${escapeHtml(dir)}</code>
      <button class="ghost" data-copy="${escapeHtml(dir)}">复制目录</button>
    </div>
    <div class="copyrow">
      <code>${escapeHtml(paper.source)}</code>
      <button class="ghost" data-copy="${escapeHtml(paper.source)}">复制来源</button>
    </div>`;
  box.querySelector("#hintClose").addEventListener("click", () => { box.hidden = true; });
  for (const button of box.querySelectorAll("[data-copy]")) {
    button.addEventListener("click", async () => {
      await navigator.clipboard.writeText(button.dataset.copy);
      button.textContent = "已复制";
      window.setTimeout(() => { button.textContent = button.dataset.copy.startsWith("http") ? "复制来源" : "复制目录"; }, 1200);
    });
  }
};

/* ---------------- 渲染 ---------------- */

const localCard = (paper) => {
  const progress = paper.progress;
  const paperless = !paper.local.pdf;
  const setLabel = String(Number(paper.set) || paper.set);
  const cover = paper.local.cover
    ? `<img class="cover" src="${escapeHtml(paper.local.cover)}" alt="" loading="lazy">`
    : `<div class="cover placeholder"><span>${escapeHtml(paper.period)}</span><strong>第 ${escapeHtml(setLabel)} 套</strong></div>`;
  const badges = [
    paper.latest ? `<span class="badge new">最新</span>` : "",
    paperless ? `<span class="badge warn">仅解析</span>` : "",
    paper.local.answers ? `<span class="badge">有答案</span>` : "",
    paperless || paper.local.audio ? "" : `<span class="badge warn">缺听力</span>`,
  ].join("");
  const progressLine = paper.started
    ? `读到第 ${progress.page} 页 · 听力 ${clock(progress.audioTime)}`
    : paperless ? "没有原卷，只有答案解析" : "尚未开始";
  const sheetLine = paper.sheet ? ` · 已答 ${paper.sheet.answered}/${paper.sheet.count}` : "";

  return `
    <a class="set local${paperless ? " paperless" : ""}" href="/read.html?id=${encodeURIComponent(paper.id)}">
      ${cover}
      <div class="body">
        <div class="t">${escapeHtml(paper.title)}</div>
        <div class="m">${escapeHtml(paper.groupLabel ?? paper.period)} · 第 ${escapeHtml(setLabel)} 套 ${badges}</div>
        <div class="m progress">${escapeHtml(progressLine)}${escapeHtml(sheetLine)}</div>
      </div>
    </a>`;
};

const missingChip = (paper) => `
  <button class="chip missing" data-id="${escapeHtml(paper.id)}" title="未收录：点一下看要放到哪儿">
    第 ${escapeHtml(paper.set)} 套
  </button>`;

/** 一个考次块（比如「2024年 - 上半年」）：有收录的排卡片，没收录的压成一行 */
const renderGroupBlock = (container, label, items) => {
  const local = items.filter((p) => p.local.pdf || p.local.analysis);
  const missing = items.filter((p) => !p.local.pdf && !p.local.analysis);

  if (local.length === 0) {
    const row = document.createElement("div");
    row.className = "group-row";
    row.innerHTML = `
      <span class="group-name">${escapeHtml(label)}</span>
      <span class="chip-row">${missing.map(missingChip).join("")}</span>`;
    container.appendChild(row);
    return;
  }

  const card = document.createElement("section");
  card.className = "card group";
  card.innerHTML = `
    <h3>
      ${escapeHtml(label)}
      <span class="pill">${local.length}/${items.length} 已收录</span>
    </h3>
    <div class="sets">${local.map(localCard).join("")}</div>
    ${missing.length ? `<div class="chips missing-row">${missing.map(missingChip).join("")}</div>` : ""}`;
  container.appendChild(card);
};

/** 一门考试整体：标题 + 各个考次块 */
const renderExamBlock = (container, examId, papers) => {
  const exam = examMeta(examId);
  const section = document.createElement("section");
  section.className = "exam-section";

  const total = papers.length;
  const local = papers.filter((p) => p.local.pdf || p.local.analysis).length;
  const started = papers.filter((p) => p.started).length;
  const totalAll = (state.index?.papers ?? []).filter((p) => p.exam === examId).length;

  section.innerHTML = `
    <h2 class="exam-title">
      ${escapeHtml(exam.name)}
      <span class="pill">收录 ${local}/${totalAll}</span>
      ${started ? `<span class="pill">已开始 ${started}</span>` : ""}
    </h2>`;

  // 保持索引顺序（新 → 旧），按考次切块
  const groups = new Map();
  for (const paper of papers) {
    const key = paper.groupLabel ?? paper.period;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(paper);
  }
  for (const [label, items] of groups) renderGroupBlock(section, label, items);

  container.appendChild(section);
};

const render = () => {
  const container = $("exams");
  container.innerHTML = "";
  const papers = papersInExam().filter(matchesFilter);

  if (papers.length === 0) {
    container.innerHTML = `<section class="card muted">没有匹配的套卷。</section>`;
    return;
  }

  if (state.exam === "all") {
    const byExam = new Map();
    for (const paper of papers) {
      if (!byExam.has(paper.exam)) byExam.set(paper.exam, []);
      byExam.get(paper.exam).push(paper);
    }
    // 按 examList 的顺序输出，没套卷的考试直接跳过
    for (const exam of examList()) {
      const items = byExam.get(exam.id);
      if (items?.length) renderExamBlock(container, exam.id, items);
    }
  } else {
    renderExamBlock(container, state.exam, papers);
  }

  for (const chip of container.querySelectorAll(".chip.missing")) {
    chip.addEventListener("click", () => {
      const paper = state.index.papers.find((p) => p.id === chip.dataset.id);
      if (paper) showAddHint(paper);
    });
  }
};

const renderOverview = () => {
  const node = $("overview");
  const overview = state.overview;
  if (!overview) {
    node.textContent = "暂无学习数据";
    return;
  }
  const perExam = examList()
    .map((exam) => {
      const all = (state.index?.papers ?? []).filter((p) => p.exam === exam.id);
      if (!all.length) return null;
      const local = all.filter((p) => p.local.pdf || p.local.analysis).length;
      return { exam, local, total: all.length };
    })
    .filter(Boolean);

  const rows = (overview.progress ?? [])
    .filter((entry) => entry.updatedAt)
    .map((entry) => `<div class="row"><span>${escapeHtml(entry.title ?? entry.id)}</span>
      <span class="muted">第 ${entry.page ?? 1} 页 · 听力 ${clock(entry.audioTime)} · ${escapeHtml((entry.updatedAt ?? "").slice(0, 16).replace("T", " "))}</span></div>`);

  node.innerHTML = `
    ${perExam.map(({ exam, local, total }) => `<div class="row"><span>${escapeHtml(exam.name)}</span><span class="muted">已收录 ${local} / ${total} 套</span></div>`).join("")}
    <div class="row"><span>生词本</span><span class="muted">${overview.words} 条</span></div>
    <div class="row"><span>错题本</span><span class="muted">${overview.wrong} 条</span></div>
    ${rows.join("") || '<div class="row"><span>套卷进度</span><span class="muted">还没有记录</span></div>'}`;
};

const buildExamTabs = () => {
  const nav = $("examTabs");
  if (!nav) return;
  const papers = state.index?.papers ?? [];
  const items = [{ id: "all", short: "全部", name: "全部考试", count: papers.length }]
    .concat(examList().map((exam) => ({
      id: exam.id,
      short: exam.short ?? exam.name,
      name: exam.name,
      count: papers.filter((p) => p.exam === exam.id).length,
    })))
    // 一门都没有的考试不占位置（比如还没导入的专八）
    .filter((item) => item.id === "all" || item.count > 0);

  nav.innerHTML = items
    .map((item) => `<button class="chip-btn${item.id === state.exam ? " active" : ""}" data-exam="${escapeHtml(item.id)}" title="${escapeHtml(item.name)}">
      ${escapeHtml(item.short)} <span class="chip-count">${item.count}</span>
    </button>`)
    .join("");

  nav.querySelectorAll(".chip-btn").forEach((button) => {
    button.addEventListener("click", () => {
      state.exam = button.dataset.exam;
      nav.querySelectorAll(".chip-btn").forEach((other) => other.classList.toggle("active", other === button));
      renderStats();
      render();
    });
  });
};

const renderStats = () => {
  const papers = papersInExam();
  const local = papers.filter((p) => p.local.pdf || p.local.analysis).length;
  const started = papers.filter((p) => p.started).length;
  $("stats").textContent = `已收录 ${local} / ${papers.length} 套 · 生词 ${state.overview.words} · 错题 ${state.overview.wrong}`;
  $("filters").querySelectorAll(".chip-btn").forEach((button) => {
    const count = button.dataset.filter === "all"
      ? papers.length
      : button.dataset.filter === "local"
        ? local
        : started;
    button.textContent = `${button.dataset.filter === "all" ? "全部" : button.dataset.filter === "local" ? "已收录" : "已开始"} ${count}`;
  });
};

/* ---------------- boot ---------------- */

const boot = async () => {
  const [index, overview] = await Promise.all([fetchJson("/api/papers"), fetchJson("/api/overview")]);
  state.index = index;
  state.overview = overview;

  renderStats();
  renderOverview();
  buildExamTabs();
  render();

  $("filters").addEventListener("click", (event) => {
    const button = event.target.closest(".chip-btn");
    if (!button) return;
    state.filter = button.dataset.filter;
    $("filters").querySelectorAll(".chip-btn").forEach((other) => other.classList.toggle("active", other === button));
    render();
  });

  let searchTimer = null;
  $("search").addEventListener("input", (event) => {
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(() => {
      state.query = event.target.value.trim().toLowerCase();
      render();
    }, 160);
  });
};

boot().catch((error) => {
  document.body.innerHTML = `<pre style="padding:24px;color:#b91c1c">加载失败：${escapeHtml(error?.message ?? error)}</pre>`;
});
