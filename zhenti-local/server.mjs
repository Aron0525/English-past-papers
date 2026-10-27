#!/usr/bin/env node
/**
 * zhenti-local —— 本地真题备考工作台
 *
 * 零依赖：只用 Node 内置模块。
 *  - 静态资源：public/（阅读器前端）
 *  - 题库文件：data/（PDF、听力，支持 Range，便于音频拖动进度）
 *  - 学习数据：笔记、生词本、错题本、阅读/听力进度
 *
 * 用法：
 *   node server.mjs [--port 8787]
 */
import { createServer } from "node:http";
import { createReadStream, existsSync } from "node:fs";
import { mkdir, readFile, readdir, rename, stat, writeFile } from "node:fs/promises";
import { extname, join, normalize, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(fileURLToPath(new URL(".", import.meta.url)));
const PUBLIC_DIR = join(ROOT, "public");
const DATA_DIR = join(ROOT, "data");
const STUDY_DIR = join(DATA_DIR, "study");

const portArg = process.argv.indexOf("--port");
const PORT = portArg >= 0 ? Number(process.argv[portArg + 1]) : 8787;

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".webp": "image/webp",
  ".jpg": "image/jpeg",
  ".ico": "image/x-icon",
  ".pdf": "application/pdf",
  ".mp3": "audio/mpeg",
  // 采集来的听力大多是 M4A：URL 写着 .mp3、文件头却是 ftyp，按 URL 后缀给 audio/mpeg 会播不了
  ".m4a": "audio/mp4",
  ".wav": "audio/wav",
  ".woff2": "font/woff2",
  ".txt": "text/plain; charset=utf-8",
};

const json = (res, status, body) => {
  const payload = JSON.stringify(body);
  res.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "content-length": Buffer.byteLength(payload),
  });
  res.end(payload);
};

const readJsonBody = async (req) => {
  const chunks = [];
  let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > 1_000_000) throw new Error("body too large");
    chunks.push(chunk);
  }
  if (chunks.length === 0) return {};
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
};

/** Resolve a path and refuse anything that escapes its base directory. */
const safeJoin = (base, relative) => {
  const target = resolve(base, normalize(relative).replace(/^([/\\])+/, ""));
  if (target !== base && !target.startsWith(base + sep)) return null;
  return target;
};

/** Paper id looks like cet6/2025-12/01 — never a path traversal. */
const validPaperId = (id) => typeof id === "string" && /^[a-z0-9]+\/\d{4}-\d{2}\/[0-9a-z]+$/i.test(id);

const paperDir = (id) => (validPaperId(id) ? safeJoin(DATA_DIR, id) : null);

const readText = async (path, fallback = "") => {
  try {
    return await readFile(path, "utf8");
  } catch {
    return fallback;
  }
};

const readJson = async (path, fallback) => {
  try {
    return JSON.parse(await readFile(path, "utf8"));
  } catch {
    return fallback;
  }
};

/**
 * 词库有两种形态：
 *   - dict.db（ECDICT 全量，77 万词条）：按需查，不加载全表
 *   - dict.json（只有卷内词，2 万条）：老格式，兜底用
 * 优先用 db，没有才退回 json。
 */
let dictDb = null;
let dictPrepared = null;
let dictJson = null;

const openDict = async () => {
  if (dictPrepared) return dictPrepared;
  const dbPath = join(DATA_DIR, "dict.db");
  if (existsSync(dbPath)) {
    try {
      const { DatabaseSync } = await import("node:sqlite");
      dictDb = new DatabaseSync(dbPath, { readOnly: true });
      dictPrepared = {
        word: dictDb.prepare("SELECT word, k, t, d, pos, tag, collins, oxford FROM w WHERE word = ?"),
        form: dictDb.prepare("SELECT lemma FROM f WHERE form = ?"),
        like: dictDb.prepare("SELECT word FROM w WHERE word LIKE ? ORDER BY length(word) LIMIT 8"),
        count: dictDb.prepare("SELECT COUNT(*) AS n FROM w"),
      };
      return dictPrepared;
    } catch (error) {
      console.warn("词典库打不开，退回 dict.json：", error.message);
    }
  }
  dictJson = dictJson ?? (await readJson(join(DATA_DIR, "dict.json"), { words: {}, forms: {} }));
  return null;
};

/** 查一个词，返回 { hit, word, k, t, d, f } ；f 是原形（变形词才有）。 */
const lookupWord = async (raw) => {
  const word = raw.trim().toLowerCase();
  const stmt = await openDict();
  if (stmt) {
    const row = stmt.word.get(word);
    if (row && (row.t || row.d)) return { hit: true, ...row };
    const form = stmt.form.get(word);
    if (form) {
      const lemma = stmt.word.get(form.lemma);
      if (lemma && (lemma.t || lemma.d)) return { hit: true, ...lemma, f: form.lemma };
    }
    // 复数/时态没进变形表时，退一步做前缀匹配，给几个候选
    const guesses = stmt.like.all(`${word}%`).map((r) => r.word);
    return { hit: false, word, guesses };
  }

  const dict = dictJson ?? { words: {}, forms: {} };
  const direct = dict.words?.[word];
  if (direct) return { hit: true, ...direct };
  const lemma = dict.forms?.[word];
  const viaLemma = lemma ? dict.words?.[lemma] : null;
  if (viaLemma) return { hit: true, ...viaLemma, f: lemma };
  return { hit: false, word };
};

/** 先写临时文件再 rename，避免写到一半崩掉把数据文件写坏。 */
const writeFileAtomic = async (path, text) => {
  await mkdir(resolve(path, ".."), { recursive: true });
  const temp = `${path}.tmp`;
  await writeFile(temp, text, "utf8");
  await rename(temp, path);
};

const writeJson = (path, value) => writeFileAtomic(path, `${JSON.stringify(value, null, 2)}\n`);

/** Byte-range aware file response; audio seeking depends on this. */
const serveFile = (req, res, path, download = false) => {
  const contentType = MIME[extname(path).toLowerCase()] ?? "application/octet-stream";
  const stream = (start, end) =>
    createReadStream(path, { start, end }).pipe(res);
  // ?download=1 时按附件发，浏览器直接存盘，不新开标签页（弹窗会被拦截）
  const disposition = download ? { "content-disposition": `attachment; filename="${encodeURIComponent(path.split(sep).pop())}"` } : {};

  stat(path)
    .then((info) => {
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
          "cache-control": "no-cache",
        });
        stream(start, end);
        return;
      }
      res.writeHead(200, {
        "content-type": contentType,
        "content-length": info.size,
        "accept-ranges": "bytes",
        "cache-control": "no-cache",
        ...disposition,
      });
      if (req.method === "HEAD") res.end();
      else stream(0, info.size - 1);
    })
    .catch(() => {
      res.writeHead(404, { "content-type": "text/plain; charset=utf-8" });
      res.end("not found");
    });
};

/** 听力文件按真实格式命名，扩展名不固定，所以挨个候选着找。 */
const AUDIO_FILES = ["listen.mp3", "listen.m4a", "listen.wav"];

/**
 * 找这一套的听力文件。官方多套卷共用同一份听力素材，采集源里第 2、3 套常常压根没有
 * 单独音频，所以允许 meta.audioRef 指向同考次的另一套（ingest 落盘时自动补）。
 */
const resolveAudio = async (dir, meta) => {
  const own = AUDIO_FILES.find((name) => existsSync(join(dir, name)));
  if (own) return { name: own, from: null };
  const ref = meta?.audioRef;
  if (typeof ref === "string" && validPaperId(ref)) {
    const refDir = paperDir(ref);
    const shared = refDir ? AUDIO_FILES.find((name) => existsSync(join(refDir, name))) : null;
    if (shared) return { name: shared, from: ref };
  }
  return { name: null, from: null };
};

/** 「已开始」= 真的读进去了：翻过页或听过一段，而不是只打开过。 */
const isStarted = (progress) => Boolean(progress) && ((progress.page ?? 1) > 1 || (progress.audioTime ?? 0) > 5);

/** 每套卷在本地有什么：正文 / 听力 / 答案 / 封面 / 进度。 */
const localState = async (paper) => {
  const dir = paperDir(paper.id);
  if (!dir || !existsSync(dir)) return { ...paper, local: { pdf: false, audio: false, answers: false, analysis: false, audioName: null, cover: null }, progress: null, started: false };

  const meta = await readJson(join(dir, "meta.json"), null);
  const audioHit = await resolveAudio(dir, meta);
  const audioName = audioHit.name;
  const [pdf, answers] = [
    existsSync(join(dir, "read.clean.pdf")) || existsSync(join(dir, "read.pdf")),
    existsSync(join(dir, "answers.json")),
  ];
  const audio = Boolean(audioName);
  const analysis = existsSync(join(dir, "analysis.pdf"));
  const cover = ["cover.webp", "cover.jpg", "cover.png"].find((name) => existsSync(join(dir, name))) ?? null;
  const progress = pdf ? await readJson(join(dir, "progress.json"), null) : null;
  const sheet = pdf ? await readJson(join(dir, "sheet.json"), null) : null;
  const answered = sheet?.answers ? Object.values(sheet.answers).filter(Boolean).length : 0;

  return {
    ...paper,
    local: { pdf, audio, answers, analysis, audioName, audioFrom: audioHit.from, cover: cover ? `/data/${paper.id}/${cover}` : null },
    progress: progress ? { page: progress.page ?? 1, audioTime: progress.audioTime ?? 0, updatedAt: progress.updatedAt ?? null } : null,
    started: isStarted(progress),
    sheet: sheet ? { count: sheet.count ?? 55, answered, updatedAt: sheet.updatedAt ?? null } : null,
  };
};

const api = async (req, res, url) => {
  const route = url.pathname;

  if (route === "/api/papers" && req.method === "GET") {
    const index = await readJson(join(DATA_DIR, "papers.json"), { exams: [], papers: [] });
    const papers = await Promise.all((index.papers ?? []).map(localState));
    return json(res, 200, { ...index, papers, counts: {
      total: papers.length,
      local: papers.filter((p) => p.local.pdf).length,
      withAudio: papers.filter((p) => p.local.audio).length,
      started: papers.filter((p) => p.started).length,
    } });
  }

  if (route === "/api/paper" && req.method === "GET") {
    const id = url.searchParams.get("id") ?? "";
    const dir = paperDir(id);
    if (!dir || !existsSync(dir)) return json(res, 404, { error: "unknown paper" });
    const [meta, notes, progress, answers, sheet, analysis] = await Promise.all([
      readJson(join(dir, "meta.json"), { id }),
      readText(join(dir, "notes.md"), ""),
      readJson(join(dir, "progress.json"), { page: 1, audioTime: 0, scale: 1 }),
      readJson(join(dir, "answers.json"), null),
      readJson(join(dir, "sheet.json"), null),
      // 逐题详细解析（analysis.json，由 tools/build-analysis.py 生成）；没有就是 null
      readJson(join(dir, "analysis.json"), null),
    ]);
    // 文件名不固定（听力可能是 m4a，也可能复用同考次另一套），让前端别去猜
    const audioHit = await resolveAudio(dir, meta);
    const audioFile = audioHit.name
      ? (audioHit.from ? `/data/${audioHit.from}/${audioHit.name}` : audioHit.name)
      : null;
    const analysisFile = existsSync(join(dir, "analysis.pdf")) ? "analysis.pdf" : null;
    // 重排版过的卷子放 read.clean.pdf，原扫描件继续留着不动；
    // 只有答案解析的套卷（比如大部分专八）压根没有原卷，pdfFile 得是 null 而不是假文件名
    const pdfFile = existsSync(join(dir, "read.clean.pdf"))
      ? "read.clean.pdf"
      : existsSync(join(dir, "read.pdf")) ? "read.pdf" : null;
    const hasPaper = Boolean(pdfFile);
    return json(res, 200, {
      meta, notes, progress, answers, sheet, analysis, pdfFile, audioFile,
      audioFrom: audioHit.from, analysisFile, hasPaper,
    });
  }

  /**
   * 点词查词。先按原词查，查不到再走"词形→原形"映射（books→book、went→go）。
   * 词库里没有的（人名、缩写）如实返回 hit:false，不让前端假装查到了。
   */
  if (route === "/api/dict" && req.method === "GET") {
    const word = (url.searchParams.get("word") ?? "").trim().toLowerCase();
    if (!word || word.length > 48) return json(res, 400, { error: "bad word" });
    return json(res, 200, await lookupWord(word));
  }

  // 圈画：按套存一份，坐标是相对页面的 0~1，缩放后不用重算
  if (route === "/api/ink" && req.method === "GET") {
    const id = url.searchParams.get("id") ?? "";
    const dir = paperDir(id);
    if (!dir) return json(res, 400, { error: "bad id" });
    const ink = await readJson(join(dir, "ink.json"), { pages: {} });
    return json(res, 200, ink);
  }

  if (route === "/api/ink" && req.method === "POST") {
    const { id, pages } = await readJsonBody(req);
    const dir = paperDir(id);
    if (!dir) return json(res, 400, { error: "bad id" });
    if (!existsSync(dir)) return json(res, 404, { error: "unknown paper" });

    const clean = {};
    for (const [page, strokes] of Object.entries(pages ?? {})) {
      const number = Number(page);
      if (!Number.isInteger(number) || number < 1 || number > 999) continue;
      if (!Array.isArray(strokes)) continue;
      const kept = [];
      for (const stroke of strokes.slice(0, 2000)) {
        const points = (stroke?.p ?? []).filter(
          (point) => Array.isArray(point) && point.length === 2 && point.every((n) => Number.isFinite(n)),
        ).slice(0, 20_000);
        if (points.length < 2) continue;
        kept.push({
          t: stroke.t === "hl" ? "hl" : "pen",
          c: /^#[0-9a-f]{6}$/i.test(stroke.c ?? "") ? stroke.c : "#e11d48",
          // 线宽存的是"占页宽的比例"（约 0.001~0.01），这样放大缩小笔迹跟着纸一起变粗
          w: Math.min(Math.max(Number(stroke.w) || 0.002, 0.0002), 0.05),
          p: points.map(([x, y]) => [Math.round(x * 1e4) / 1e4, Math.round(y * 1e4) / 1e4]),
        });
      }
      if (kept.length) clean[String(number)] = kept;
    }
    // 只留存过的页；全擦干净了就写空对象，别留一堆空数组
    await writeFileAtomic(join(dir, "ink.json"), JSON.stringify({ pages: clean, updatedAt: new Date().toISOString() }));
    return json(res, 200, { ok: true, pages: Object.keys(clean).length });
  }

  if (route === "/api/sheet" && req.method === "POST") {
    const { id, count, answers } = await readJsonBody(req);
    const dir = paperDir(id);
    if (!dir) return json(res, 400, { error: "bad id" });
    await mkdir(dir, { recursive: true });
    // 题量只决定界面上排多少格；作答数据一律保留（题量调小不该丢答案）
    const limit = Math.min(Math.max(Number(count) || 55, 1), 300);
    const clean = {};
    for (const [key, value] of Object.entries(answers ?? {})) {
      const number = Number(key);
      if (!Number.isInteger(number) || number < 1 || number > 1000) continue;
      const text = String(value ?? "").trim().toUpperCase().slice(0, 4);
      if (text) clean[String(number)] = text;
    }
    const next = { count: limit, answers: clean, updatedAt: new Date().toISOString() };
    await writeJson(join(dir, "sheet.json"), next);
    return json(res, 200, { ok: true, answered: Object.keys(clean).length });
  }

  if (route === "/api/notes" && req.method === "POST") {
    const { id, content } = await readJsonBody(req);
    const dir = paperDir(id);
    if (!dir) return json(res, 400, { error: "bad id" });
    await writeFileAtomic(join(dir, "notes.md"), String(content ?? ""));
    return json(res, 200, { ok: true });
  }

  if (route === "/api/progress" && req.method === "POST") {
    const { id, page, audioTime, scale, view } = await readJsonBody(req);
    const dir = paperDir(id);
    if (!dir) return json(res, 400, { error: "bad id" });
    const current = await readJson(join(dir, "progress.json"), {});
    const next = {
      page: Number(page) || current.page || 1,
      audioTime: Number(audioTime) || current.audioTime || 0,
      scale: Number(scale) || current.scale || 1,
      // 页面模式与缩放方式（连续/单页/双页、适宽/适高/固定比例）一起记住
      view: {
        mode: typeof view?.mode === "string" ? view.mode : current.view?.mode ?? "continuous",
        zoomKind: typeof view?.zoomKind === "string" ? view.zoomKind : current.view?.zoomKind ?? "fitWidth",
      },
      updatedAt: new Date().toISOString(),
    };
    await writeJson(join(dir, "progress.json"), next);
    return json(res, 200, next);
  }

  // 生词本 / 错题本：跨套共享的两个集合
  if (route === "/api/study" && req.method === "GET") {
    const [wordbook, wrong] = await Promise.all([
      readJson(join(STUDY_DIR, "wordbook.json"), []),
      readJson(join(STUDY_DIR, "wrong.json"), []),
    ]);
    return json(res, 200, { wordbook, wrong });
  }

  if (route === "/api/study" && req.method === "POST") {
    const { collection, item, remove } = await readJsonBody(req);
    if (collection !== "wordbook" && collection !== "wrong") return json(res, 400, { error: "bad collection" });
    const path = join(STUDY_DIR, `${collection}.json`);
    const list = await readJson(path, []);
    let next;
    if (remove) {
      next = list.filter((entry) => entry.key !== remove);
    } else if (item && typeof item.key === "string") {
      const index = list.findIndex((entry) => entry.key === item.key);
      next = index >= 0 ? list.map((entry, i) => (i === index ? { ...entry, ...item } : entry)) : [...list, item];
    } else {
      return json(res, 400, { error: "bad item" });
    }
    await writeJson(path, next);
    return json(res, 200, { ok: true, count: next.length });
  }

  if (route === "/api/overview" && req.method === "GET") {
    const [wordbook, wrong] = await Promise.all([
      readJson(join(STUDY_DIR, "wordbook.json"), []),
      readJson(join(STUDY_DIR, "wrong.json"), []),
    ]);
    const papers = await readJson(join(DATA_DIR, "papers.json"), { papers: [] });
    const progress = (await Promise.all((papers.papers ?? []).map(async (paper) => {
      const state = await readJson(join(DATA_DIR, paper.id, "progress.json"), null);
      return isStarted(state) ? { id: paper.id, title: paper.title, ...state } : null;
    }))).filter(Boolean);
    return json(res, 200, { words: wordbook.length, wrong: wrong.length, progress });
  }

  return json(res, 404, { error: "unknown route" });
};

const server = createServer(async (req, res) => {
  const url = new URL(req.url ?? "/", `http://${req.headers.host ?? "localhost"}`);
  try {
    if (url.pathname.startsWith("/api/")) return await api(req, res, url);
    if (url.pathname === "/") {
      res.writeHead(302, { location: "/index.html" });
      return res.end();
    }
    const base = url.pathname.startsWith("/data/") ? DATA_DIR : PUBLIC_DIR;
    const relative = url.pathname.startsWith("/data/") ? url.pathname.slice("/data/".length) : url.pathname;
    const target = safeJoin(base, decodeURIComponent(relative));
    if (!target) {
      res.writeHead(403).end("forbidden");
      return;
    }
    if (!existsSync(target)) {
      res.writeHead(404, { "content-type": "text/plain; charset=utf-8" });
      res.end("not found");
      return;
    }
    const info = await stat(target);
    if (info.isDirectory()) {
      const entries = await readdir(target);
      return json(res, 200, { directory: relative, entries });
    }
    serveFile(req, res, target, url.searchParams.get("download") === "1");
  } catch (error) {
    json(res, 500, { error: String(error?.message ?? error) });
  }
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`zhenti-local → http://127.0.0.1:${PORT}/`);
  console.log(`题库目录 ${DATA_DIR}`);
});
