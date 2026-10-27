#!/usr/bin/env node
/**
 * 灌入 2013.06 — 2015.12 旧考次六级真题（主采集脚本只覆盖 2016.06 起）。
 *
 * 数据源是 cet6/cache/1e5e11.paths.txt（1e5e11/CET46-Resources 仓库目录树）。
 * 这个仓库的 `六级真题/` 目录下其实一直有 2013.06 起的旧考次，只是当初
 * probe_all.py 的 SESSIONS 列表从 2016.06 才开始，把旧的跳过了。
 *
 * 与 ingest.mjs 同一套约定：
 *   - 每个套次挑一条最优直链（试题 / 解析），落盘 data/cet6/<年-月>/<套号>/
 *   - 只给 data/papers.json 补 files 字段，不重建、不删除
 *   - 文件名按真实格式（嗅探），不是 URL 扩展名
 *
 * 旧考次现实：这些仓库里 2013—2015 的六级真题只有试题 + 解析，没有听力音频
 * （听力音频从 2016.06 才开始收录）。2012 和 2014.12 两个考次整个仓库都没有六级卷。
 *
 * 用法
 *   node tools/ingest-legacy.mjs --dry
 *   node tools/ingest-legacy.mjs --jobs 3
 */
import { mkdir, readFile, rename, writeFile, stat } from "node:fs/promises";
import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(here, "..");
const DATA_DIR = join(ROOT, "data");
const CET6_DIR = join(DATA_DIR, "cet6");

const argv = process.argv.slice(2);
const flag = (name) => argv.includes(name);
const option = (name, fallback) => {
  const i = argv.indexOf(name);
  return i >= 0 && argv[i + 1] ? argv[i + 1] : fallback;
};
const DRY = flag("--dry");
const CONCURRENCY = Math.min(Math.max(Number(option("--jobs", "3")), 1), 6);

const PATHS_FILE = resolve(ROOT, "../cet6/cache/1e5e11.paths.txt");
const REPO = "1e5e11/CET46-Resources";
const BRANCH = "main";

// 本次要补的旧考次（2012 与 2014.12 在这仓库里没有六级卷，见文件头注释）
const SESSIONS = ["2013.06", "2013.12", "2014.06", "2015.06", "2015.12"];

const CN_NUM = { 一: 1, 二: 2, 三: 3 };

/* ---------------- 从目录树推导直链 ---------------- */

const ghRaw = (path) =>
  `https://raw.githubusercontent.com/${REPO}/${BRANCH}/${encodeURIComponent(path).replace(/%2F/g, "/")}`;

const parsePaths = (text) => text.split(/\r?\n/).filter((l) => l.trim());

/** 从文件名认出第几套：`（一）`/`（二）`/`（三）` 或 `第1套`/`第一套`。认不出返回 null。 */
const setOfName = (name) => {
  let m = name.match(/[（(]\s*([一二三1-3])\s*[)）]/);
  if (m) return CN_NUM[m[1]] ?? Number(m[1]);
  m = name.match(/第\s*([一二三1-3])\s*套/);
  if (m) return CN_NUM[m[1]] ?? Number(m[1]);
  return null;
};

/* ---------------- 格式嗅探与下载（同 ingest.mjs） ---------------- */

const sniff = async (url) => {
  try {
    const res = await fetch(url, { headers: { Range: "bytes=0-15" }, signal: AbortSignal.timeout(60_000) });
    if (!res.ok && res.status !== 206) return null;
    const buf = Buffer.from(await res.arrayBuffer());
    const total = Number(res.headers.get("content-range")?.split("/")[1] ?? res.headers.get("content-length") ?? 0);
    return { magic: buf, bytes: total };
  } catch {
    return null;
  }
};

const formatOf = (buf) => {
  if (buf.length < 8) return "unknown";
  if (buf.subarray(0, 4).toString("latin1") === "%PDF") return "pdf";
  if (buf.subarray(4, 8).toString("latin1") === "ftyp") return "m4a";
  if (buf.subarray(0, 3).toString("latin1") === "ID3") return "mp3";
  if (buf[0] === 0xff && (buf[1] & 0xe0) === 0xe0) return "mp3";
  return "unknown";
};

const sha256 = (buf) => createHash("sha256").update(buf).digest("hex");

const download = async (url, dest) => {
  if (existsSync(dest)) {
    const buf = await readFile(dest);
    return { skipped: true, bytes: buf.length, sha256: sha256(buf), format: formatOf(buf.subarray(0, 16)) };
  }
  let lastError;
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
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError;
};

const human = (bytes) => {
  if (!bytes) return "?";
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${bytes} B`;
};

/* ---------------- 主流程 ---------------- */

const index = JSON.parse(await readFile(join(DATA_DIR, "papers.json"), "utf8"));
const papers = index.papers ?? [];
const byId = new Map(papers.map((p) => [p.id, p]));

const paths = parsePaths(await readFile(PATHS_FILE, "utf8"));

// 归集：key = sess#set，收集 试题 / 解析 两条直链
const grouped = new Map();
for (const p of paths) {
  for (const sess of SESSIONS) {
    if (!p.startsWith(`六级真题/${sess}/`)) continue;
    const rel = p.slice(`六级真题/${sess}/`.length);
    const [sub, ...rest] = rel.split("/");
    const name = rest[rest.length - 1];
    let cat = null;
    if (sub === "真题PDF" || sub === "真题Word") cat = "试题";
    else if (sub === "答案解析") cat = "解析";
    if (!cat) continue;
    if (sub === "真题Word") continue; // 只要 PDF
    const set = setOfName(name);
    if (!set) continue;
    const key = `${sess}#${set}`;
    if (!grouped.has(key)) grouped.set(key, { sess, set, 试题: [], 解析: [] });
    grouped.get(key)[cat].push({ url: ghRaw(p), name });
  }
}

const candidates = [];
for (const g of grouped.values()) {
  const period = g.sess.replace(".", "-");
  const setId = String(g.set).padStart(2, "0");
  const id = `cet6/${period}/${setId}`;
  const paper = byId.get(id);
  if (!paper) continue;
  candidates.push({ id, period, set: setId, title: paper.title, paper, group: g });
}
candidates.sort((a, b) => a.id.localeCompare(b.id));

console.log(`候选 ${candidates.length} 套（数据源 ${PATHS_FILE}）\n`);

// 嗅探挑最优
const targets = [];
const probeQueue = [...candidates];
const probeWorkers = Array.from({ length: Math.min(CONCURRENCY, 4) }, async () => {
  for (;;) {
    const item = probeQueue.shift();
    if (!item) return;
    const pickPdf = async (rows) => {
      if (!rows.length) return null;
      const probed = await Promise.all(rows.map(async (r) => {
        const hit = await sniff(r.url);
        return { row: r, format: hit ? formatOf(hit.magic) : "unknown", bytes: hit?.bytes ?? 0 };
      }));
      const usable = probed.filter((e) => e.format === "pdf");
      const pool = usable.length ? usable : probed;
      pool.sort((a, b) => (b.format === "pdf" ? 0 : 1) - (a.format === "pdf" ? 0 : 1));
      return pool[0] ?? null;
    };
    const [pdf, analysis] = await Promise.all([
      pickPdf(item.group.试题),
      pickPdf(item.group.解析),
    ]);
    targets.push({ ...item, pdf, analysis });
  }
});
await Promise.all(probeWorkers);
targets.sort((a, b) => a.id.localeCompare(b.id));

let plannedBytes = 0;
for (const t of targets) {
  const cell = (entry, label) => (entry ? `${label}✓${entry.format}(${human(entry.bytes)})` : `${label}✗`);
  plannedBytes += (t.pdf?.bytes ?? 0) + (t.analysis?.bytes ?? 0);
  console.log(`  ${t.id}  ${cell(t.pdf, "试题")}  ${cell(t.analysis, "解析")}`);
}
console.log(`\n预计下载 ${human(plannedBytes)}`);

if (DRY) {
  console.log("--dry 只探测，未下载");
  process.exit(0);
}

let ok = 0;
let failed = 0;
const errors = [];

const runOne = async (t) => {
  const dir = join(CET6_DIR, t.period, t.set);
  await mkdir(dir, { recursive: true });
  const files = {};
  const jobs = [
    ["pdf", t.pdf, "read.pdf"],
    ["analysis", t.analysis, "analysis.pdf"],
  ];
  for (const [kind, entry, filename] of jobs) {
    if (!entry) continue;
    if (entry.format !== "pdf") { errors.push(`${t.id}/${filename} 非 PDF，跳过`); continue; }
    const dest = join(dir, filename);
    try {
      const result = await download(entry.row.url, dest);
      files[kind] = {
        name: filename,
        bytes: result.bytes,
        sha256: result.sha256 ?? "(已有文件，未重算)",
        format: "pdf",
        source: "A",
        url: entry.row.url,
        originalName: entry.row.name,
      };
      console.log(`  ${result.skipped ? "跳过" : "下载"} ${t.id}/${filename} ${human(result.bytes)}`);
    } catch (error) {
      failed += 1;
      errors.push(`${t.id}/${filename} 失败 ${error.message}`);
      console.log(`  失败 ${t.id}/${filename} ${error.message}`);
    }
  }

  const metaPath = join(dir, "meta.json");
  const oldMeta = existsSync(metaPath) ? JSON.parse(await readFile(metaPath, "utf8")) : {};
  const meta = {
    ...oldMeta,
    id: t.id,
    exam: "cet6",
    period: t.period,
    set: t.set,
    title: t.title,
    source: t.paper.source,
    files,
    assets: {
      ...(oldMeta.assets ?? {}),
      pdfUrl: files.pdf?.url ?? oldMeta.assets?.pdfUrl,
      analysisUrl: files.analysis?.url ?? oldMeta.assets?.analysisUrl,
    },
    capabilities: {
      answers: existsSync(join(dir, "answers.json")),
      listeningText: false,
      sentenceTranslation: false,
    },
    ingestedFrom: "1e5e11/CET46-Resources (legacy)",
    ingestedAt: new Date().toISOString(),
  };
  await writeFile(`${metaPath}.tmp`, `${JSON.stringify(meta, null, 2)}\n`, "utf8");
  await rename(`${metaPath}.tmp`, metaPath);

  if (files.pdf || files.analysis) {
    t.paper.files = {
      ...(t.paper.files ?? {}),
      ...(files.pdf ? { pdf: { name: files.pdf.name, bytes: files.pdf.bytes, sha256: files.pdf.sha256 } } : {}),
      ...(files.analysis ? { analysis: { name: files.analysis.name, bytes: files.analysis.bytes, sha256: files.analysis.sha256 } } : {}),
    };
    t.paper.verifiedAt = new Date().toISOString();
  }
  ok += 1;
};

const queue = [...targets];
const workers = Array.from({ length: CONCURRENCY }, async () => {
  for (;;) {
    const next = queue.shift();
    if (!next) return;
    await runOne(next);
  }
});
await Promise.all(workers);

const indexPath = join(DATA_DIR, "papers.json");
await writeFile(`${indexPath}.tmp`, `${JSON.stringify(index, null, 2)}\n`, "utf8");
await rename(`${indexPath}.tmp`, indexPath);

console.log(`\n完成 ${ok} 套，失败 ${failed} 项，索引仍是 ${papers.length} 套`);
if (errors.length) {
  console.log("\n失败明细");
  for (const line of errors) console.log(`  ${line}`);
}
